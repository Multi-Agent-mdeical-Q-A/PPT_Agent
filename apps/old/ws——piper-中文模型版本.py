# services/backend/routers/ws.py
import asyncio, json, uuid
import os
from pathlib import Path
from datetime import datetime, date
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import traceback

from core.session import TurnMetrics, SessionState

# --- .env load (optional) ---
try:
    from dotenv import load_dotenv  # type: ignore
    _HERE = Path(__file__).resolve()
    _BACKEND_DIR = _HERE.parent.parent  # .../services/backend
    _ENV_PATH = _BACKEND_DIR / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except Exception:
    pass

from services.tts.edge import EdgeTTS

try:
    from services.tts.piper import PiperTTS
except Exception:
    PiperTTS = None  # type: ignore

from services.llm.hf_local import HFLocalLLM


router = APIRouter()
SERVER_INSTANCE_ID = uuid.uuid4().hex


# ------------------------
# TTS select
# ------------------------
def _make_tts():
    backend = (os.getenv("TTS_BACKEND", "edge") or "edge").strip().lower()
    print(f"DEBUG: backend found via env: [{backend}]")

    if backend == "piper":
        if PiperTTS is None:
            raise RuntimeError("TTS_BACKEND=piper but PiperTTS import failed (pip install piper-tts)")

        backend_dir = Path(__file__).resolve().parent.parent
        raw_model = os.getenv("PIPER_MODEL_PATH", "models/voices/zh_CN-huayan-x_low.onnx")
        model_path = Path(raw_model)
        if not model_path.is_absolute():
            model_path = backend_dir / raw_model

        raw_cfg = os.getenv("PIPER_CONFIG_PATH")
        cfg_path = None
        if raw_cfg:
            p = Path(raw_cfg)
            cfg_path = p if p.is_absolute() else (backend_dir / raw_cfg)

        use_cuda = (os.getenv("PIPER_USE_CUDA", "0") or "0").strip().lower() in ("1", "true", "yes")
        target_sr_raw = (os.getenv("PIPER_TARGET_SAMPLE_RATE") or "").strip()
        target_sr = int(target_sr_raw) if target_sr_raw.isdigit() else None

        print(f"[TTS] Loading Piper model from: {model_path}")
        return PiperTTS(
            model_path=str(model_path),
            config_path=str(cfg_path) if cfg_path else None,
            use_cuda=use_cuda,
            target_sample_rate=target_sr,
        )

    return EdgeTTS()


tts = _make_tts()
llm = HFLocalLLM(model_dir="models/selfrag_llama2_7b")


# ------------------------
# Metrics (backend-only jsonl)
# ------------------------
LOG_DIR = (Path(__file__).resolve().parent.parent / "logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

def _metrics_path() -> Path:
    return LOG_DIR / f"metrics_{date.today().isoformat()}.jsonl"

def _append_line(path: Path, line: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

async def append_metrics(record: dict):
    try:
        line = json.dumps(record, ensure_ascii=False)
        await asyncio.to_thread(_append_line, _metrics_path(), line)
    except Exception:
        pass


# ------------------------
# WS send helpers
# ------------------------
async def send_json(ws: WebSocket, lock: asyncio.Lock, payload: dict):
    async with lock:
        await ws.send_json(payload)

async def safe_send_json(ws: WebSocket, lock: asyncio.Lock, payload: dict):
    try:
        await asyncio.shield(send_json(ws, lock, payload))
    except Exception:
        pass

async def safe_send_bytes(ws: WebSocket, lock: asyncio.Lock, payload: bytes, *, tag: str = "") -> bool:
    try:
        async with lock:
            await ws.send_bytes(payload)
        return True
    except Exception as e:
        print(f"[ws] send_bytes failed {tag}: {type(e).__name__}: {e}")
        return False


# ------------------------
# Strong cancel
# ------------------------
async def cancel_workflow(
    ws: WebSocket,
    lock: asyncio.Lock,
    state: SessionState,
    old_turn: int,
    *,
    send_audio_cancel: bool = True,
    reason: str = "interrupt",
):
    if state.cancel_event and not state.cancel_event.is_set():
        state.cancel_event.set()

    m: TurnMetrics | None = None
    if state.metrics is not None:
        m = state.metrics.get(old_turn)
        if m is not None and m.t_interrupt_recv is None:
            m.t_interrupt_recv = time.perf_counter()

    task = state.workflow_task
    state.workflow_task = None
    state.cancel_event = None

    if task and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=0.2)
        except Exception:
            pass

    if m is not None and m.t_interrupt_recv is not None and m.t_interrupt_done is None:
        m.t_interrupt_done = time.perf_counter()
        if m.outcome == "ok":
            m.outcome = "cancelled"

    if send_audio_cancel:
        print("SEND audio_cancel", old_turn, "reason=", reason)
        await safe_send_json(ws, lock, {"type": "audio_cancel", "turn_id": old_turn})


# ------------------------
# Workflow: LLM streaming + segmented TTS worker
# ------------------------
async def run_turn_workflow(
    ws: WebSocket,
    lock: asyncio.Lock,
    state: SessionState,
    turn_id: int,
    user_text: str,
    cancel_event: asyncio.Event,
    metrics: TurnMetrics,
):
    MIN_CHARS = 70
    MAX_CHARS = 260

    # ✅ 支持中文句号 + 英文句号（你提到 LLM 结尾是 '.'）
    SENTENCES = ["。", ".", "！", "!", "？", "?", "\n"]

    def _is_cancelled() -> bool:
        return cancel_event.is_set() or (turn_id != state.turn_id)

    def _pop_segment(buf: str) -> tuple[str | None, str]:
        """
        规则：
        - < MIN_CHARS：不切（等更自然）
        - >= MIN_CHARS：在 MIN_CHARS-1 之后找最早的句末符（。 或 . 等）
        - 找不到且 >= MAX_CHARS：硬切 MAX_CHARS
        """
        if len(buf) < MIN_CHARS:
            return None, buf

        best_idx = None
        for p in SENTENCES:
            idx = buf.find(p, MIN_CHARS - 1)
            if idx != -1:
                if best_idx is None or idx < best_idx:
                    best_idx = idx

        if best_idx is not None:
            seg = buf[: best_idx + 1]
            rest = buf[best_idx + 1 :]
            return seg, rest

        if len(buf) >= MAX_CHARS:
            return buf[:MAX_CHARS], buf[MAX_CHARS:]

        return None, buf

    tts_queue: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()
    tts_seq = 0

    audio_started = False  # whether we've sent audio_begin
    sent_any_audio_chunk = False

    async def tts_worker():
        nonlocal tts_seq, audio_started, sent_any_audio_chunk
        try:
            while True:
                if _is_cancelled():
                    return

                item = await tts_queue.get()
                if item is None:
                    break

                seg_id, seg_text = item
                seg_text = seg_text.strip()
                if not seg_text:
                    continue

                if _is_cancelled():
                    return

                # ✅ 关键改动：先“探测”这一段是否真的能产出音频
                agen = tts.stream(seg_text)

                try:
                    first_chunk = await agen.__anext__()  # type: ignore[attr-defined]
                except StopAsyncIteration:
                    # 这一段 TTS 产出为空：跳过，不发 begin/end
                    continue

                if _is_cancelled():
                    return

                # ✅ 第一个音频 chunk 真正到手了，才开始 speaking + audio_begin
                if not audio_started:
                    await send_json(ws, lock, {"type": "state_update", "turn_id": turn_id, "state": "speaking"})
                    await send_json(ws, lock, {
                        "type": "audio_begin",
                        "turn_id": turn_id,
                        "mime": getattr(tts, "mime_type", "audio/L16"),
                        "format": getattr(tts, "format", "pcm_s16le"),
                        "sample_rate": getattr(tts, "sample_rate", 24000),
                        "channels": getattr(tts, "channels", 1),
                    })
                    print("SEND audio_begin", turn_id, getattr(tts, "format", ""), getattr(tts, "sample_rate", ""))
                    audio_started = True

                async def _send_chunk(chunk: bytes):
                    nonlocal tts_seq, sent_any_audio_chunk
                    header = b"AUD0" + int(turn_id).to_bytes(4, "little") + int(tts_seq).to_bytes(4, "little")
                    ok = await safe_send_bytes(ws, lock, header + chunk, tag=f"turn={turn_id} seq={tts_seq}")
                    if not ok:
                        cancel_event.set()
                        return False
                    if metrics.t_first_audio is None:
                        metrics.t_first_audio = time.perf_counter()
                    tts_seq += 1
                    sent_any_audio_chunk = True
                    return True

                # 先发探测到的首 chunk
                if not await _send_chunk(first_chunk):
                    return

                # 再继续把剩下的 chunk 发完
                async for chunk in agen:
                    if _is_cancelled():
                        return
                    if not await _send_chunk(chunk):
                        return

        finally:
            # ✅ 只在真正开始过音频后，才发 audio_end
            if (not _is_cancelled()) and audio_started:
                await send_json(ws, lock, {"type": "audio_end", "turn_id": turn_id})
                print("SEND audio_end", turn_id)

    async def llm_worker():
        full_text = ""
        buf = ""
        seg_id = 0

        await send_json(ws, lock, {"type": "state_update", "turn_id": turn_id, "state": "thinking"})
        if _is_cancelled():
            return full_text

        if hasattr(llm, "generate_stream"):
            async for delta in llm.generate_stream(user_text):
                if _is_cancelled():
                    return full_text
                if not delta:
                    continue

                full_text += delta
                buf += delta

                if metrics.t_first_delta is None:
                    metrics.t_first_delta = time.perf_counter()

                await send_json(ws, lock, {"type": "assistant_delta", "turn_id": turn_id, "delta": delta})

                while True:
                    seg, buf2 = _pop_segment(buf)
                    if seg is None:
                        break
                    buf = buf2
                    await tts_queue.put((seg_id, seg))
                    seg_id += 1
        else:
            txt = await llm.generate(user_text)
            if _is_cancelled():
                return full_text

            full_text = txt or ""
            buf = full_text

            if metrics.t_first_delta is None:
                metrics.t_first_delta = time.perf_counter()

            await send_json(ws, lock, {"type": "assistant_delta", "turn_id": turn_id, "delta": full_text})

            while True:
                seg, buf2 = _pop_segment(buf)
                if seg is None:
                    break
                buf = buf2
                await tts_queue.put((seg_id, seg))
                seg_id += 1

        # ✅ 最后 tail：哪怕 < MIN_CHARS 也必须入队（否则短回答永远没声音）
        tail = buf.strip()
        if tail:
            await tts_queue.put((seg_id, tail))
            seg_id += 1

        if not _is_cancelled():
            await send_json(ws, lock, {"type": "assistant_final", "turn_id": turn_id, "text": full_text})

        return full_text

    llm_task: asyncio.Task | None = None
    tts_task: asyncio.Task | None = None

    try:
        tts_task = asyncio.create_task(tts_worker())
        llm_task = asyncio.create_task(llm_worker())

        await llm_task
        await tts_queue.put(None)
        await tts_task

        if not _is_cancelled():
            await send_json(ws, lock, {"type": "state_update", "turn_id": turn_id, "state": "idle"})

    except asyncio.CancelledError:
        # ✅ 只认“真 cancel”
        real_cancel = cancel_event.is_set() or (turn_id != state.turn_id)
        if real_cancel:
            metrics.outcome = "cancelled"
        return

    except Exception as e:
        tb = traceback.format_exc()
        print("[run_turn_workflow] exception:", type(e).__name__, repr(e))
        print(tb)

        await send_json(ws, lock, {
            "type": "error",
            "turn_id": turn_id,
            "msg": f"Workflow failed: {type(e).__name__}: {repr(e)}",
        })
        metrics.outcome = "error"
        metrics.err_type = type(e).__name__
        metrics.err_repr = repr(e)

        if turn_id == state.turn_id:
            await send_json(ws, lock, {"type": "state_update", "turn_id": turn_id, "state": "idle"})

    finally:
        for t in (llm_task, tts_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except Exception:
                    pass

        if metrics.t_done is None:
            metrics.t_done = time.perf_counter()
        await append_metrics(metrics.to_record())
        if state.metrics is not None:
            state.metrics.pop(turn_id, None)


# ------------------------
# WS endpoint
# ------------------------
@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    send_lock = asyncio.Lock()
    session_id = uuid.uuid4().hex
    state = SessionState(turn_id=0, workflow_task=None, session_id=session_id, metrics={})

    await send_json(ws, send_lock, {
        "type": "hello",
        "msg": "connected",
        "session_id": session_id,
        "server_instance_id": SERVER_INSTANCE_ID,
        "turn_id_reset": 0,
    })

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "user_text":
                recv_ts = time.perf_counter()

                old_turn = state.turn_id
                state.turn_id = old_turn + 1
                turn_id = state.turn_id

                if state.workflow_task:
                    await cancel_workflow(ws, send_lock, state, old_turn, send_audio_cancel=True, reason="new_turn")

                m = TurnMetrics(session_id=session_id, turn_id=turn_id, t0=recv_ts)
                state.metrics[turn_id] = m

                state.cancel_event = asyncio.Event()
                state.workflow_task = asyncio.create_task(
                    run_turn_workflow(ws, send_lock, state, turn_id, msg.get("text", ""), state.cancel_event, m)
                )

                def _done(_t: asyncio.Task):
                    if state.workflow_task is _t:
                        state.workflow_task = None
                        state.cancel_event = None

                state.workflow_task.add_done_callback(_done)

            elif mtype == "interrupt":
                recv_ts = time.perf_counter()

                old_turn = state.turn_id
                state.turn_id = old_turn + 1
                new_turn = state.turn_id

                if state.workflow_task:
                    if state.metrics is not None and old_turn in state.metrics:
                        if state.metrics[old_turn].t_interrupt_recv is None:
                            state.metrics[old_turn].t_interrupt_recv = recv_ts
                    await cancel_workflow(ws, send_lock, state, old_turn, send_audio_cancel=True, reason="interrupt")
                else:
                    await safe_send_json(ws, send_lock, {"type": "audio_cancel", "turn_id": old_turn})

                await send_json(ws, send_lock, {"type": "state_update", "turn_id": new_turn, "state": "idle"})

            else:
                await send_json(ws, send_lock, {
                    "type": "error",
                    "turn_id": state.turn_id,
                    "msg": f"unknown type: {mtype}"
                })

    except WebSocketDisconnect:
        print("[ws] WebSocketDisconnect")
        if state.cancel_event and not state.cancel_event.is_set():
            state.cancel_event.set()
        if state.workflow_task:
            state.workflow_task.cancel()
