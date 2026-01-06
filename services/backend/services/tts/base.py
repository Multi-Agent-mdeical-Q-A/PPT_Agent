from typing import AsyncIterator, Protocol

class TTSProvider(Protocol):
    mime_type: str  # e.g. "audio/mpeg" or "audio/wav"

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield audio bytes chunks."""
        ...
