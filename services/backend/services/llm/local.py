# local.py（替换你的 LocalLLM）
import aiohttp
import asyncio
import json
from typing import Optional, List, Dict, Any
from .base import LLMProvider

def _extract_text(data: Any) -> str:
    """Try best-effort extraction across common local LLM server schemas."""
    if data is None:
        return ""

    # direct string
    if isinstance(data, str):
        return data

    if isinstance(data, dict):
        # common keys
        for k in ("content", "completion", "text", "response", "output"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v

        # OpenAI-like
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            c0 = choices[0]
            if isinstance(c0, dict):
                # completions
                v = c0.get("text")
                if isinstance(v, str) and v.strip():
                    return v
                # chat.completions
                msg = c0.get("message")
                if isinstance(msg, dict):
                    v = msg.get("content")
                    if isinstance(v, str) and v.strip():
                        return v

        # llama.cpp server sometimes returns {"content": "..."} or {"results":[{"text":"..."}]}
        results = data.get("results")
        if isinstance(results, list) and results:
            r0 = results[0]
            if isinstance(r0, dict):
                v = r0.get("text")
                if isinstance(v, str) and v.strip():
                    return v

    return ""

class LocalLLM(LLMProvider):
    def __init__(self, api_url: str = "http://localhost:8080/completion", timeout_s: int = 60):
        self.api_url = api_url
        self.timeout = aiohttp.ClientTimeout(total=timeout_s)

    async def generate(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        **kwargs
    ) -> str:
        payload = {
            "prompt": prompt,
            "n_predict": int(kwargs.get("n_predict", 256)),
            "temperature": float(kwargs.get("temperature", 0.7)),
            "stop": kwargs.get("stop", ["User:", "\n\n"]),
            # 有些服务需要显式 stream=false
            "stream": False,
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(self.api_url, json=payload) as resp:
                    raw = await resp.text()

                    if resp.status != 200:
                        return f"Error: LLM Server returned {resp.status}: {raw[:200]}"

                    # Try parse json, fallback to raw text
                    try:
                        data = json.loads(raw)
                        out = _extract_text(data)
                        return out.strip()
                    except Exception:
                        # some servers return plain text
                        return raw.strip()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            return f"Error calling Local LLM: {e}"
