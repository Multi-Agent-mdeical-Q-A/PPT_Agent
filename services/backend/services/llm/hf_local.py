import asyncio
from pathlib import Path
from typing import Optional, List, Dict

from .base import LLMProvider

class HFLocalLLM(LLMProvider):
    def __init__(
        self,
        model_dir: str = "models/selfrag_llama2_7b",
        max_new_tokens: int = 256,
        temperature: float = 0.7,
    ):
        # 延迟导入，避免没装 torch/transformers 时直接炸
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM

        self.model_dir = str(Path(model_dir))
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir, use_fast=False)
        # 设备选择：有 CUDA 就尽量上 GPU；没有就 CPU（会慢）
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # 简化：先用最直白的加载方式（你后面可以加 4bit/8bit 量化）
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_dir,
            torch_dtype=dtype,
            device_map="auto" if self.device == "cuda" else None,
        )
        if self.device == "cpu":
            self.model.to(self.device)

    def _format_prompt(self, prompt: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        # v0.1：先极简，不引入复杂 chat template
        # 你之后做多轮再把 history 拼进去
        return f"User: {prompt}\nAssistant:"

    def _generate_sync(self, prompt: str, history=None) -> str:
        import torch

        text = self._format_prompt(prompt, history)
        inputs = self.tokenizer(text, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            out = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=True,
                temperature=self.temperature,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        full = self.tokenizer.decode(out[0], skip_special_tokens=True)
        # 只截取 Assistant: 之后的内容
        idx = full.rfind("Assistant:")
        return full[idx + len("Assistant:"):].strip() if idx != -1 else full.strip()

    async def generate(self, prompt: str, history=None, **kwargs) -> str:
        # 把同步重计算挪到线程，避免阻塞 event loop
        # 注意：to_thread 不能硬中断，只能等它算完再丢弃结果（你 ws.py 已经用 turn_id 丢弃了）
        return await asyncio.to_thread(self._generate_sync, prompt, history)
