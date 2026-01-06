import edge_tts
from .base import TTSProvider
from typing import AsyncIterator

class EdgeTTS(TTSProvider):
    mime_type = "audio/mpeg"

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        com = edge_tts.Communicate(text=text, voice=self.voice)
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
