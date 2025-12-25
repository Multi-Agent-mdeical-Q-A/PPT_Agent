import io
import wave

def synthesize_wav_stub(text: str, seconds: float = 1.0, sr: int = 16000) -> bytes:
    nframes = int(seconds * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * nframes)  # silence
    return buf.getvalue()
