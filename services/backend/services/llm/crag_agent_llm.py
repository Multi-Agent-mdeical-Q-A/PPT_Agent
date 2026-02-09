import asyncio
import functools
import os
from typing import Optional, List, Dict, AsyncIterator, Any

from .base import LLMProvider
from .CRAG.config.config_loader import settings as crag_settings
from .CRAG.control_layer.crag_agent import CragAgent
from .CRAG.core_layer.generator_tool import GeneratorTool
from .CRAG.core_layer.evaluator_tool import EvaluatorTool
from .CRAG.core_layer.refiner_tool import RefinerTool


class CRAGAgentLLM(LLMProvider):
    """
    Async-friendly wrapper that adapts the CRAG Agent pipeline to the LLMProvider
    interface used by ws.py.
    """

    def __init__(self, method: str | None = None):
        self.settings = crag_settings
        # allow overriding default method via ctor or env
        self.method = (method or os.getenv("CRAG_AGENT_METHOD") or self.settings.params.get("method", "no_retrieval")).strip().lower()
        self.tools = self._init_tools(self.method)
        self.agent = CragAgent(self.tools, method=self.method)
        self._lock = asyncio.Lock()
        self._stream_chunk_chars = 80

    def _init_tools(self, method: str):
        tools: Dict[str, Any] = {}
        gen_path = self.settings.models.get("generator_path", "")
        if not gen_path:
            raise ValueError("CRAG generator_path is not configured in settings.yaml.")

        tools["generator"] = GeneratorTool(
            model_path=gen_path,
            max_model_len=self.settings.params.get("max_model_len", 2048),
            gpu_utilization=self.settings.params.get("gpu_memory_utilization", 0.7),
        )

        # evaluator / refiner are only needed for full CRAG or RAG workflows
        if method != "no_retrieval":
            eval_path = self.settings.models.get("evaluator_path", "")
            if not eval_path:
                raise ValueError("CRAG evaluator_path is not configured in settings.yaml.")

            tools["evaluator"] = EvaluatorTool(
                model_path=eval_path,
                device=self.settings.params.get("device", "cuda:0"),
            )
            tools["refiner"] = RefinerTool(
                internal_path=self.settings.paths.get("internal_ref", ""),
                external_path=self.settings.paths.get("external_ref", ""),
                combined_path=self.settings.paths.get("combined_ref", ""),
            )

        return tools

    def _build_batch(
        self,
        prompt: str,
        *,
        raw_docs: Optional[List[List[str]]] = None,
        contexts: Optional[List[str] | str] = None,
    ) -> Dict[str, Any]:
        batch = {
            "ids": [0],
            "queries": [prompt],
            "raw_docs": raw_docs if raw_docs is not None else [[]],
        }

        if contexts is not None:
            if isinstance(contexts, str):
                contexts = [contexts]
            batch["final_contexts"] = contexts
        return batch

    def _run_sync(
        self,
        prompt: str,
        *,
        method: str,
        raw_docs: Optional[List[List[str]]] = None,
        contexts: Optional[List[str] | str] = None,
    ) -> str:
        batch = self._build_batch(prompt, raw_docs=raw_docs, contexts=contexts)
        answers = self.agent.run_batch(batch, method=method)
        if answers and len(answers) > 0:
            return answers[0]
        return ""

    async def generate(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        **kwargs,
    ) -> str:
        run_method = (kwargs.get("method") or self.method).strip().lower()
        raw_docs = kwargs.get("raw_docs")
        contexts = kwargs.get("contexts")

        if run_method != self.method and run_method != "no_retrieval":
            if ("evaluator" not in self.tools) or ("refiner" not in self.tools):
                raise RuntimeError(
                    f"CRAGAgentLLM initialized without retrieval tools; cannot run method '{run_method}'. "
                    "Recreate with method='crag' (or set CRAG_AGENT_METHOD) to enable full pipeline."
                )

        async with self._lock:
            loop = asyncio.get_running_loop()
            fut = loop.run_in_executor(
                None,
                functools.partial(
                    self._run_sync,
                    prompt,
                    method=run_method,
                    raw_docs=raw_docs,
                    contexts=contexts,
                ),
            )
            try:
                return await fut
            except asyncio.CancelledError:
                fut.cancel()
                raise

    async def generate_stream(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        # reuse generate but yield small deltas to keep websocket UX unchanged
        text = await self.generate(prompt, history=history, **kwargs)
        if not text:
            return

        for i in range(0, len(text), self._stream_chunk_chars):
            chunk = text[i : i + self._stream_chunk_chars]
            yield chunk
            await asyncio.sleep(0)
