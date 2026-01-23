from typing import Protocol, Optional, List, Dict, AsyncIterator, runtime_checkable

History = Optional[List[Dict[str, str]]]


@runtime_checkable
class LLMProvider(Protocol):
    async def generate(self, prompt: str, history: History = None, **kwargs) -> str:
        """
        Non-streaming generation.
        Returns the complete response string.
        Should support cancellation via asyncio.CancelledError.
        """
        ...
