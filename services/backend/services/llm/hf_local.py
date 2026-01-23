import asyncio
import threading
from pathlib import Path
from typing import Optional, List, Dict, AsyncIterator

import torch
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TextIteratorStreamer,
    StoppingCriteria,
    StoppingCriteriaList,
)

from .base import LLMProvider


class StopOnEventCriteria(StoppingCriteria):
    """If stop_event is set, stop generation early."""
    def __init__(self, stop_event: threading.Event):
        self.stop_event = stop_event

    def __call__(self, input_ids, scores, **kwargs) -> bool:
        return self.stop_event.is_set()


class HFLocalLLM(LLMProvider):
    def __init__(
        self,
        model_dir: str = "models/selfrag_llama2_7b",
        max_new_tokens: int = 256,
        temperature: float = 0.7,
    ):
        self.model_dir = str(Path(model_dir))
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature

        # tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir, use_fast=False)

        # device + dtype
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if self.device == "cuda" else torch.float32

        # model
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_dir,
            dtype=torch_dtype,   # ✅ 注意：用 torch_dtype，不要用 dtype
            device_map="auto" if self.device == "cuda" else None,
            low_cpu_mem_usage=True,
        )
        self.model.eval()

        # 输入应放到与模型第一块参数相同的 device（兼容 device_map=auto 的情况）
        try:
            self.input_device = next(self.model.parameters()).device
        except StopIteration:
            self.input_device = torch.device(self.device)

        # pad_token 兜底（很多 Llama 系 tokenizer 没 pad_token）
        if self.tokenizer.pad_token_id is None and self.tokenizer.eos_token_id is not None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

    def _format_prompt(self, prompt: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        # v0.2 先极简：后续你做多轮再把 history 拼进去
        return f"User: {prompt}\nAssistant:"

    async def generate_stream(self, prompt: str, history=None) -> AsyncIterator[str]:
        """
        Stream text deltas using TextIteratorStreamer.
        Cancellation: if caller cancels this async generator, we set a stop_event
        to stop model.generate as soon as possible.
        """
        text = self._format_prompt(prompt, history)
        inputs = self.tokenizer(text, return_tensors="pt")
        inputs = {k: v.to(self.input_device) for k, v in inputs.items()}

        streamer = TextIteratorStreamer(
            self.tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        stop_event = threading.Event()
        stopping = StoppingCriteriaList([StopOnEventCriteria(stop_event)])

        gen_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=self.max_new_tokens,
            do_sample=True,
            temperature=self.temperature,
            eos_token_id=self.tokenizer.eos_token_id,
            pad_token_id=self.tokenizer.pad_token_id,
            stopping_criteria=stopping,
        )

        def _run_generate():
            # 在后台线程里跑 generate，避免阻塞 asyncio loop
            with torch.no_grad():
                try:
                    self.model.generate(**gen_kwargs)
                except Exception:
                    # 线程内异常不直接 raise 到主线程；主线程消费 streamer 会自然结束或超时
                    pass

        t = threading.Thread(target=_run_generate, daemon=True)
        t.start()

        it = iter(streamer)

        try:
            while True:
                # ✅ 关键：把阻塞的 next(it) 放到线程里，避免卡住 event loop
                piece = await asyncio.to_thread(next, it,None)
                if piece is None:
                    break
                if piece:
                    yield piece

                # 让出控制权，提升 interrupt/heartbeat 响应
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            # ✅ 让 generate 尽快停
            stop_event.set()
            raise
        finally:
            # 如果外部提前结束，也设置 stop_event（尽快停掉后台生成）
            stop_event.set()
            # 不强制 join，避免卡住；daemon thread 会自行退出

    async def generate(self, prompt: str, history=None, **kwargs) -> str:
        """
        兼容旧接口：把 stream 拼起来得到完整文本。
        v0.2 你可以不依赖这个接口，但保留不碍事。
        """
        chunks: List[str] = []
        async for d in self.generate_stream(prompt, history=history):
            chunks.append(d)
        return "".join(chunks).strip()
