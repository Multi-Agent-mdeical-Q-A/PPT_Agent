from typing import List, Optional, Any
import re
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

try:
    from vllm import LLM, SamplingParams  # type: ignore
except ModuleNotFoundError:
    LLM = None
    SamplingParams = None

from .base_tool import BaseTool


class GeneratorTool(BaseTool):
    def __init__(self, model_path: str, max_model_len: int = 4096, gpu_utilization: float = 0.9):
        """
        Generator tool with vLLM when available; falls back to transformers.generate on Windows.
        """
        self.backend = "vllm" if LLM is not None else "hf"
        self.max_model_len = max_model_len
        self.max_tokens = 100
        self.temperature = 0.0

        if self.backend == "vllm":
            print(f"🚀 [Generator] Initializing vLLM from: {model_path} ...")
            self.llm = LLM(
                model=model_path,
                dtype="half",
                max_model_len=max_model_len,
            )
            self.default_params = SamplingParams(
                temperature=self.temperature,
                top_p=1.0,
                max_tokens=self.max_tokens,
                skip_special_tokens=False,
            )
            print("✅[Generator] vLLM model loaded successfully.")
        else:
            print("⚠️ [Generator] vLLM not available; using transformers.generate instead.")
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=False)
            self.model = AutoModelForCausalLM.from_pretrained(model_path)
            self.model.to(self.device)
            self.model.eval()

    def _clean_text(self, text: str) -> str:
        clean_text = text.replace("\n", " ").replace("\r", "")
        clean_text = re.sub(r"\[Utility:\d+\]", "", clean_text)
        clean_text = re.sub(r"\[.*?\]", "", clean_text)
        clean_text = re.sub(r"</?paragraph>", "", clean_text)
        return clean_text.strip()

    def _run_batch(self, inputs: List[str], ids: Optional[List[str]] = None, **kwargs) -> List[str]:
        temperature = kwargs.get("temperature", self.temperature)
        max_tokens = int(kwargs.get("max_tokens", self.max_tokens))

        if self.backend == "vllm":
            params = SamplingParams(
                temperature=temperature,
                top_p=1.0,
                max_tokens=max_tokens,
                skip_special_tokens=False,
            )
            outputs = self.llm.generate(inputs, params, use_tqdm=False)

            results = []
            for output in outputs:
                text = output.outputs[0].text
                results.append(self._clean_text(text))

            if len(results) < len(inputs):
                results.extend([""] * (len(inputs) - len(results)))
            return results

        # transformers fallback path (CPU/GPU depending on availability)
        results: List[str] = []
        for prompt in inputs:
            encoded = self.tokenizer(prompt, return_tensors="pt")
            encoded = {k: v.to(self.device) for k, v in encoded.items()}
            with torch.no_grad():
                output_ids = self.model.generate(
                    **encoded,
                    max_new_tokens=max_tokens,
                    do_sample=temperature > 0,
                    temperature=max(temperature, 1e-5),
                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )
            generated = output_ids[0][encoded["input_ids"].shape[1]:]
            text = self.tokenizer.decode(generated, skip_special_tokens=True)
            results.append(self._clean_text(text))

        if len(results) < len(inputs):
            results.extend([""] * (len(inputs) - len(results)))
        return results
