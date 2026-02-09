# services/backend/routers/ws.py
import asyncio, json, uuid, os
from pathlib import Path
from datetime import date
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import traceback

from core.session import TurnMetrics, SessionState

# ✅ 统一由 config.py 加载 .env，这里只读 settings
from config import settings
from services.tts.edge import EdgeTTS
try:
    from services.tts.piper import PiperTTS
except Exception:
    PiperTTS = None  # type: ignore

from services.llm.crag_agent_llm import CRAGAgentLLM
from services.llm.hf_local import HFLocalLLM

router = APIRouter()
SERVER_INSTANCE_ID = settings.SERVER_INSTANCE_ID or uuid.uuid4().hex

# ------------------------
# Metrics (backend-only)
# ------------------------
LOG_DIR: Path = settings.LOG_DIR
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
# WebSocket send helpers
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
# TTS selection (zh/en)
# ------------------------
def _make_piper(model_path: Path, cfg_path: Path | None, *, target_sr: int | None):
    if PiperTTS is None:
        raise RuntimeError("PiperTTS import failed (pip install piper-tts)")

    return PiperTTS(
        model_path=str(model_path),
        config_path=str(cfg_path) if cfg_path else None,
        use_cuda=bool(settings.PIPER_USE_CUDA),
        target_sample_rate=target_sr,
    )

def _make_tts_pair():
    backend = (settings.TTS_BACKEND or "edge").strip().lower()
    print(f"DEBUG: backend from settings: [{backend}]")

    if backend != "piper":
        # Edge path: zh/en 都用 edge（你也可以未来替换成不同 voice）
        return EdgeTTS(), EdgeTTS()

    target_sr = settings.PIPER_TARGET_SAMPLE_RATE  # e.g. 16000

    # settings 里已经 resolve 成 Path 了
    model_zh = settings.PIPER_MODEL_PATH_ZH
    cfg_zh = settings.PIPER_CONFIG_PATH_ZH

    model_en = settings.PIPER_MODEL_PATH_EN
    cfg_en = settings.PIPER_CONFIG_PATH_EN

    if model_zh is None:
        raise RuntimeError("PIPER_MODEL_PATH_ZH is missing (check .env / config.py defaults)")

    print(f"[TTS] Loading Piper ZH: {model_zh}")
    tts_zh = _make_piper(model_zh, cfg_zh, target_sr=target_sr)

    # EN 未配置就复用 ZH，保证不炸
    if (model_en is None) or (str(model_en) == str(model_zh)):
        print("[TTS] EN model not set; reuse ZH model.")
        tts_en = tts_zh
    else:
        print(f"[TTS] Loading Piper EN: {model_en}")
        tts_en = _make_piper(model_en, cfg_en, target_sr=target_sr)

    return tts_zh, tts_en

tts_zh, tts_en = _make_tts_pair()

def _lang_score(sample: str) -> tuple[int, int]:
    # cheap heuristic: count CJK vs Latin letters
    cjk = 0
    lat = 0
    for ch in sample:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF:
            cjk += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            lat += 1
    return cjk, lat

def _pick_tts_by_sample(sample: str):
    cjk, lat = _lang_score(sample)
    return tts_zh if cjk >= lat else tts_en

# ------------------------
# LLM
# ------------------------
llm = CRAGAgentLLM(method=os.getenv("CRAG_AGENT_METHOD", "no_retrieval"))
# llm = HFLocalLLM(model_dir=settings.LLM_MODEL_DIR)
# ------------------------
# Strong interrupt helper
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
# Main workflow: LLM streaming + segmented TTS
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
    # segmentation
    MIN_CHARS = 70
    SOFT_MIN_CHARS = 30
    MAX_CHARS = 260
    END_PUNCTS = set("。！？.!?")

    # auto tts selection
    AUTO_LANG = bool(settings.TTS_AUTO_LANG)
    DECIDE_CHARS = int(settings.TTS_LANG_DECIDE_CHARS or 120)

    def _is_cancelled() -> bool:
        return cancel_event.is_set() or (turn_id != state.turn_id)

    def _find_boundary(buf: str, start: int) -> int:
        # earliest end punct index at/after start
        best = -1
        for p in END_PUNCTS:
            i = buf.find(p, start)
            if i != -1 and (best == -1 or i < best):
                best = i
        return best

    def _pop_segment(buf: str) -> tuple[str | None, str]:
        """
        更自然的版本：
        1) len < SOFT_MIN: 不切
        2) 如果在 MIN-1 之后出现句末标点：切（自然）
        3) 否则如果在 SOFT_MIN-1 之后出现句末标点 且 < MIN：允许早切（解决短英文）
        4) 否则 len >= MAX：硬切
        5) 否则不切
        """
        n = len(buf)
        if n < SOFT_MIN_CHARS:
            return None, buf

        # prefer natural cut at/after MIN
        idx = _find_boundary(buf, MIN_CHARS - 1) if n >= MIN_CHARS else -1
        if idx != -1:
            cut = idx + 1
            return buf[:cut], buf[cut:]

        # early cut for short answers (SOFT..MIN-1)
        idx2 = _find_boundary(buf, SOFT_MIN_CHARS - 1)
        if idx2 != -1 and (idx2 + 1) >= SOFT_MIN_CHARS and (idx2 + 1) < MIN_CHARS:
            cut = idx2 + 1
            return buf[:cut], buf[cut:]

        if n >= MAX_CHARS:
            return buf[:MAX_CHARS], buf[MAX_CHARS:]

        return None, buf

    tts_queue: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()
    tts_seq = 0
    audio_started = False

    chosen_tts = tts_zh  # default
    decided = False
    decided_event = asyncio.Event()
    sample_buf = ""

    async def tts_worker():
        nonlocal tts_seq, audio_started
        try:
            if AUTO_LANG:
                await decided_event.wait()

            while True:
                if _is_cancelled():
                    return
                item = await tts_queue.get()
                if item is None:
                    break

                _, seg_text = item
                if not seg_text.strip():
                    continue
                if _is_cancelled():
                    return

                if not audio_started:
                    await send_json(ws, lock, {"type": "state_update", "turn_id": turn_id, "state": "speaking"})
                    await send_json(ws, lock, {
                        "type": "audio_begin",
                        "turn_id": turn_id,
                        "mime": getattr(chosen_tts, "mime_type", "audio/L16"),
                        "format": getattr(chosen_tts, "format", "pcm_s16le"),
                        "sample_rate": getattr(chosen_tts, "sample_rate", 16000),
                        "channels": getattr(chosen_tts, "channels", 1),
                    })
                    print("SEND audio_begin", turn_id, getattr(chosen_tts, "format", ""), getattr(chosen_tts, "sample_rate", ""))
                    audio_started = True

                async for chunk in chosen_tts.stream(seg_text):
                    if _is_cancelled():
                        return
                    header = b"AUD0" + int(turn_id).to_bytes(4, "little") + int(tts_seq).to_bytes(4, "little")
                    ok = await safe_send_bytes(ws, lock, header + chunk, tag=f"turn={turn_id} seq={tts_seq}")
                    if not ok:
                        cancel_event.set()
                        return
                    if metrics.t_first_audio is None:
                        metrics.t_first_audio = time.perf_counter()
                    tts_seq += 1
        finally:
            if (not _is_cancelled()) and audio_started:
                await send_json(ws, lock, {"type": "audio_end", "turn_id": turn_id})
                print("SEND audio_end", turn_id)

    def _maybe_decide_tts(force: bool = False):
        nonlocal decided, chosen_tts, sample_buf
        if decided or (not AUTO_LANG):
            if not decided:
                decided = True
                decided_event.set()
            return

        # decide by fixed length or force at stream end
        if (len(sample_buf) >= DECIDE_CHARS) or force:
            chosen_tts = _pick_tts_by_sample(sample_buf[:DECIDE_CHARS])
            decided = True
            decided_event.set()
            print(f"[TTS] auto_lang decided: chosen={'zh' if chosen_tts is tts_zh else 'en'}")
            return

        # early decide when short answer already has boundary
        if len(sample_buf) >= SOFT_MIN_CHARS:
            b = _find_boundary(sample_buf, SOFT_MIN_CHARS - 1)
            if b != -1:
                chosen_tts = _pick_tts_by_sample(sample_buf[: max(b + 1, SOFT_MIN_CHARS)])
                decided = True
                decided_event.set()
                print(f"[TTS] auto_lang decided by early boundary: chosen={'zh' if chosen_tts is tts_zh else 'en'}")

    async def llm_worker():
        nonlocal sample_buf
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

                if AUTO_LANG and (not decided) and len(sample_buf) < DECIDE_CHARS:
                    sample_buf += delta
                    sample_buf = sample_buf[: max(DECIDE_CHARS, 256)]
                    _maybe_decide_tts(force=False)

                if metrics.t_first_delta is None:
                    metrics.t_first_delta = time.perf_counter()

                await send_json(ws, lock, {"type": "assistant_delta", "turn_id": turn_id, "delta": delta})

                # 不决定语言就不入队（tts_worker 会 wait）
                if AUTO_LANG and (not decided):
                    continue

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

            if AUTO_LANG and (not decided):
                sample_buf = full_text[:DECIDE_CHARS]
                _maybe_decide_tts(force=True)

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

        # stream ended: ensure we decide language at least once
        if AUTO_LANG and (not decided):
            _maybe_decide_tts(force=True)

        # flush tail
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
        real_cancel = cancel_event.is_set() or (turn_id != state.turn_id)
        if real_cancel:
            metrics.outcome = "cancelled"
        return
    except Exception as e:
        tb = traceback.format_exc()
        print("[run_turn_workflow] exception:", type(e).__name__, repr(e))
        print(tb)
        await send_json(ws, lock, {"type": "error", "turn_id": turn_id, "msg": f"Workflow failed: {type(e).__name__}: {repr(e)}"})
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
                await send_json(ws, send_lock, {"type": "error", "turn_id": state.turn_id, "msg": f"unknown type: {mtype}"})

    except WebSocketDisconnect:
        print("[ws] WebSocketDisconnect")
        if state.cancel_event and not state.cancel_event.is_set():
            state.cancel_event.set()
        if state.workflow_task:
            state.workflow_task.cancel()
