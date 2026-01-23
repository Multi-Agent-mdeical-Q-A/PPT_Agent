from typing import Protocol,AsyncIterator, runtime_checkable

@runtime_checkable
class TTSProvider(Protocol):
    """Streaming TTS provider that yields audio bytes chunks."""
    mime_type: str  # e.g. "audio/mpeg" or "audio/L16"
    # Optional PCM metadata for audio_begin
    format: str | None
    sample_rate: int | None
    channels: int | None

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield audio bytes chunks."""
        ...
