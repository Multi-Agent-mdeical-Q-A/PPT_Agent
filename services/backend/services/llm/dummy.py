import asyncio
from .base import LLMProvider
from typing import Optional, List, Dict

class DummyLLM(LLMProvider):
    async def generate(self, prompt: str, history: Optional[List[Dict[str, str]]] = None, **kwargs) -> str:
        # Simulate thinking delay
        try:
            await asyncio.sleep(1.0)
            return f"Echo: {prompt} (This is a dummy response)"
        except asyncio.CancelledError:
            # Cleanup if needed
            raise
