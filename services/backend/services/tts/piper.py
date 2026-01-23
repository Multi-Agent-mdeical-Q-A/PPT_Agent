# services/tts/piper.py
import asyncio
import json
import os
import threading
import time
import audioop
import inspect
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Dict, Any, Iterable

from .base import TTSProvider

# ---------- Piper import (robust) ----------
_PIPER_IMPORT_ERR: Exception | None = None
PiperVoice = None  # type: ignore
SynthesisConfig = None  # type: ignore

try:
    # preferred in piper-tts
    from piper.voice import PiperVoice as _PV, SynthesisConfig as _SC  # type: ignore
    PiperVoice = _PV  # type: ignore
    SynthesisConfig = _SC  # type: ignore
except Exception as e1:
    try:
        # fallback import style
        from piper import PiperVoice as _PV2, SynthesisConfig as _SC2  # type: ignore
        PiperVoice = _PV2  # type: ignore
        SynthesisConfig = _SC2  # type: ignore
    except Exception as e2:
        _PIPER_IMPORT_ERR = e2


# ---------- Voice cache ----------
@dataclass(frozen=True)
class _VoiceKey:
    model_path: str
    config_path: Optional[str]
    use_cuda: bool


_VOICE_CACHE: Dict[_VoiceKey, Any] = {}
_VOICE_CACHE_LOCK = threading.Lock()


def _default_config_path(model_path: str) -> Optional[str]:
    # Piper voices often ship with "<model>.onnx.json"
    cand1 = model_path + ".json"
    cand2 = model_path + ".onnx.json"
    if os.path.exists(cand1):
        return cand1
    if os.path.exists(cand2):
        return cand2
    return None


def _read_sample_rate_from_config(config_path: Optional[str]) -> Optional[int]:
    if not config_path or not os.path.exists(config_path):
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        sr = cfg.get("audio", {}).get("sample_rate")
        return int(sr) if sr else None
    except Exception:
        return None


def _as_pcm_bytes(chunk: Any) -> Optional[bytes]:
    """
    Convert possible Piper outputs to PCM16LE bytes.
    Supports:
      - bytes / bytearray / memoryview
      - AudioChunk-like object with audio_int16_bytes
      - any object with .tobytes()
    """
    if chunk is None:
        return None

    if isinstance(chunk, (bytes, bytearray)):
        return bytes(chunk)
    if isinstance(chunk, memoryview):
        return chunk.tobytes()

    b = getattr(chunk, "audio_int16_bytes", None)
    if b is not None:
        if isinstance(b, memoryview):
            return b.tobytes()
        if isinstance(b, bytearray):
            return bytes(b)
        if isinstance(b, bytes):
            return b
        try:
            return bytes(b)
        except Exception:
            return None

    tb = getattr(chunk, "tobytes", None)
    if callable(tb):
        try:
            out = tb()
            if isinstance(out, (bytes, bytearray)):
                return bytes(out)
        except Exception:
            return None

    return None


def _call_with_supported_kwargs(fn, **kwargs):
    """
    Call fn(**kwargs) but drop kwargs not supported by fn signature.
    This makes us compatible across piper-tts versions.
    """
    try:
        sig = inspect.signature(fn)
        supported = set(sig.parameters.keys())
    except Exception:
        # If signature inspection fails, just call without risky kwargs.
        supported = set()

    if supported:
        filtered = {k: v for k, v in kwargs.items() if k in supported and v is not None}
        return fn(**filtered)

    # Unknown signature: safest is to pass only essential known arg styles.
    # We will try without optional kwargs.
    essential = {}
    for k in ("text",):
        if k in kwargs:
            essential[k] = kwargs[k]
    # But our callers usually pass positional text already; so just call raw
    return fn(*[])


class PiperTTS(TTSProvider):
    """
    Local/offline TTS via piper-tts Python API.
    Output: PCM16LE mono bytes for WebAudio streaming.
    """
    mime_type = "audio/L16"
    format = "pcm_s16le"
    channels = 1

    def __init__(
        self,
        model_path: str,
        config_path: Optional[str] = None,
        *,
        use_cuda: bool = False,
        target_sample_rate: Optional[int] = None,
        # synthesis knobs
        length_scale: float = 1.0,
        noise_scale: float = 0.667,
        noise_w: float = 0.8,
        normalize_audio: bool = True,
        # multi-speaker (optional; many builds do NOT support)
        speaker_id: Optional[int] = None,
        # streaming knobs
        out_chunk_bytes: int = 4096,
        log_every_sec: float = 2.0,
    ):
        if _PIPER_IMPORT_ERR is not None or PiperVoice is None:
            raise RuntimeError(
                f"piper-tts import failed: {_PIPER_IMPORT_ERR}. Run: pip install -U piper-tts"
            )

        self.model_path = model_path
        self.config_path = config_path or _default_config_path(model_path)
        self.use_cuda = use_cuda

        # Some piper builds use speaker, some use speaker_id, some don't support any.
        self.speaker_id = speaker_id

        # Model native sample rate (what voice produces)
        self.voice_sample_rate = _read_sample_rate_from_config(self.config_path) or 22050

        # Output sample rate (what we send to frontend)
        self.sample_rate = int(target_sample_rate) if target_sample_rate else int(self.voice_sample_rate)
        self._target_sample_rate = self.sample_rate

        self._out_chunk_bytes = int(out_chunk_bytes)
        self._log_every_sec = float(log_every_sec)

        self._syn_config = SynthesisConfig(
            length_scale=length_scale,
            noise_scale=noise_scale,
            noise_w_scale=noise_w,
            normalize_audio=normalize_audio,
        )

        self._voice = self._load_voice()

        print(f"[PiperTTS] ready model={self.model_path}")
        print(f"[PiperTTS] cfg={self.config_path}")
        print(
            f"[PiperTTS] voice_sr={self.voice_sample_rate} -> out_sr={self._target_sample_rate} "
            f"(resample={self._target_sample_rate != self.voice_sample_rate})"
        )
        print(f"[PiperTTS] stream_raw={'yes' if hasattr(self._voice, 'synthesize_stream_raw') else 'no'}")

    def _load_voice(self):
        key = _VoiceKey(self.model_path, self.config_path, self.use_cuda)
        with _VOICE_CACHE_LOCK:
            v = _VOICE_CACHE.get(key)
            if v is not None:
                return v
            v = PiperVoice.load(self.model_path, config_path=self.config_path, use_cuda=self.use_cuda)
            _VOICE_CACHE[key] = v
            return v

    def _iter_piper_chunks(self, text: str) -> Iterable[Any]:
        """
        Yield chunks from Piper.
        - Prefer synthesize_stream_raw if available.
        - Else use synthesize.
        NOTE: We DO NOT assume speaker_id kw exists; we auto-filter by signature.
        """
        # build kwargs (only pass if supported)
        # Some builds use 'speaker', some 'speaker_id'. We'll offer both; filter will keep supported one.
        base_kwargs = {
            "speaker_id": self.speaker_id,
            "speaker": self.speaker_id,
            "syn_config": self._syn_config,
        }

        if hasattr(self._voice, "synthesize_stream_raw"):
            fn = getattr(self._voice, "synthesize_stream_raw")
            try:
                # some implementations expect (text, **kwargs)
                out = _call_with_supported_kwargs(fn, **base_kwargs, text=text)  # for signature(text=...)
            except TypeError:
                # fallback: pass text positionally, kwargs filtered
                out = _call_with_supported_kwargs(lambda **kw: fn(text, **kw), **base_kwargs)
            yield from out
            return

        print("[PiperTTS] Falling back to synthesize()")
        fn = getattr(self._voice, "synthesize")
        try:
            out = _call_with_supported_kwargs(fn, **base_kwargs, text=text)
        except TypeError:
            out = _call_with_supported_kwargs(lambda **kw: fn(text, **kw), **base_kwargs)

        # out may be iterable of AudioChunk, or sometimes a single object
        if isinstance(out, (bytes, bytearray, memoryview)):
            yield out
            return
        try:
            for ch in out:
                yield ch
        except TypeError:
            yield out

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if not text or not text.strip():
            return

        loop = asyncio.get_running_loop()
        q: asyncio.Queue[object] = asyncio.Queue(maxsize=256)
        stop_flag = threading.Event()

        in_rate = int(self.voice_sample_rate)
        out_rate = int(self._target_sample_rate)
        need_resample = (out_rate != in_rate)

        OUT_CHUNK = self._out_chunk_bytes
        LOG_EVERY = self._log_every_sec

        def _put(item: object) -> None:
            if stop_flag.is_set():
                return
            fut = asyncio.run_coroutine_threadsafe(q.put(item), loop)
            try:
                fut.result(timeout=5.0)
            except Exception as e:
                stop_flag.set()
                try:
                    asyncio.run_coroutine_threadsafe(q.put(e), loop)
                except Exception:
                    pass

        def producer():
            t0 = time.perf_counter()
            last_log = t0
            produced_bytes = 0
            produced_chunks = 0
            first_byte_ts: float | None = None
            rate_state = None

            try:
                print(f"[PiperTTS] Start streaming text (len={len(text)})")
                print(f"[PiperTTS] in_rate={in_rate} out_rate={out_rate} need_resample={need_resample} out_chunk={OUT_CHUNK}B")

                for raw in self._iter_piper_chunks(text):
                    if stop_flag.is_set():
                        break

                    data = _as_pcm_bytes(raw)
                    if not data:
                        now = time.perf_counter()
                        if now - last_log >= LOG_EVERY:
                            print("[PiperTTS] ... got empty chunk, still running ...")
                            last_log = now
                        continue

                    if need_resample:
                        data, rate_state = audioop.ratecv(data, 2, 1, in_rate, out_rate, rate_state)

                    if first_byte_ts is None:
                        first_byte_ts = time.perf_counter()
                        print(f"[PiperTTS] first_pcm_bytes after {(first_byte_ts - t0)*1000:.0f}ms (len={len(data)})")

                    mv = memoryview(data)
                    for off in range(0, len(mv), OUT_CHUNK):
                        if stop_flag.is_set():
                            break
                        part = mv[off:off + OUT_CHUNK].tobytes()
                        produced_bytes += len(part)
                        produced_chunks += 1
                        _put(part)

                    now = time.perf_counter()
                    if now - last_log >= LOG_EVERY:
                        dt = (now - t0) * 1000
                        print(f"[PiperTTS] ... running ... t={dt:.0f}ms chunks={produced_chunks} bytes={produced_bytes}")
                        last_log = now

                t1 = time.perf_counter()
                print(f"[PiperTTS] Producer finished. dt={(t1 - t0)*1000:.0f}ms chunks={produced_chunks} bytes={produced_bytes}")

            except Exception as e:
                print(f"[PiperTTS] Producer exception: {type(e).__name__}: {e}")
                _put(e)
            finally:
                _put(None)

        prod_task = asyncio.create_task(asyncio.to_thread(producer))

        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item  # bytes
        finally:
            stop_flag.set()
            if not prod_task.done():
                prod_task.cancel()
                try:
                    await prod_task
                except Exception:
                    pass
