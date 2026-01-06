from typing import Protocol, Optional, List, Dict

class LLMProvider(Protocol):
    async def generate(self, prompt: str, history: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        """
        Generate a response for the given prompt and history.
        Should return the complete response string (non-streaming for v0.1).
        Should support cancellation via asyncio.CancelledError.
        """
        ...
