import asyncio
import subprocess
import shutil
from typing import AsyncIterator, Optional

import edge_tts
from .base import TTSProvider


class EdgeTTS(TTSProvider):
    """
    Stream TTS audio as raw PCM16LE bytes (24kHz mono),
    by forcing edge-tts compressed stream -> ffmpeg transcode.
    """

    mime_type = "audio/L16"
    format = "pcm_s16le"
    sample_rate = 24000
    channels = 1

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Yield PCM16LE bytes.
        NOTE: We do NOT try raw PCM from Edge endpoint (unstable).
        """
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found in PATH; cannot transcode mp3/webm to pcm_s16le")

        async for pcm in self._stream_mp3_and_transcode(text, ffmpeg_path=ffmpeg):
            yield pcm

    async def _stream_mp3_and_transcode(self, text: str, ffmpeg_path: str) -> AsyncIterator[bytes]:
        """
        Read edge_tts compressed audio chunks and transcode to pcm_s16le using ffmpeg.

        Implementation detail:
        - Use subprocess.Popen + asyncio.to_thread to avoid asyncio subprocess NotImplementedError on Windows loops.
        """
        com = edge_tts.Communicate(text=text, voice=self.voice)

        proc = subprocess.Popen(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel", "error",
                "-i", "pipe:0",
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ac", str(self.channels),
                "-ar", str(self.sample_rate),
                "pipe:1",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

        q: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=32)

        async def writer():
            try:
                async for chunk in com.stream():
                    if chunk.get("type") != "audio":
                        continue
                    data = chunk.get("data") or b""
                    if not data:
                        continue
                    # write to ffmpeg stdin in a thread (blocking)
                    await asyncio.to_thread(proc.stdin.write, data)
                    await asyncio.to_thread(proc.stdin.flush)
            finally:
                try:
                    await asyncio.to_thread(proc.stdin.close)
                except Exception:
                    pass

        async def reader():
            try:
                while True:
                    data = await asyncio.to_thread(proc.stdout.read, 4096)
                    if not data:
                        break
                    await q.put(data)
            finally:
                await q.put(None)

        wt = asyncio.create_task(writer())
        rt = asyncio.create_task(reader())

        try:
            produced = 0
            while True:
                item = await q.get()
                if item is None:
                    break
                produced += len(item)
                yield item

            if produced == 0:
                # If no PCM produced, print ffmpeg stderr for debugging
                err = await asyncio.to_thread(proc.stderr.read)
                if err:
                    print("[EdgeTTS] ffmpeg stderr:", err.decode("utf-8", errors="ignore"))

        finally:
            # cancel helper tasks
            for t in (wt, rt):
                if not t.done():
                    t.cancel()

            # kill process
            try:
                await asyncio.to_thread(proc.kill)
            except Exception:
                pass
            try:
                await asyncio.to_thread(proc.wait)
            except Exception:
                pass
