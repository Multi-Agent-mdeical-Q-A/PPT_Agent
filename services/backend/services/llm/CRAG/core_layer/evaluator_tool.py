import torch
from typing import List, Optional
from transformers import AutoTokenizer, T5ForSequenceClassification
from .base_tool import BaseTool

class EvaluatorTool(BaseTool):
    def __init__(self, model_path: str, device: str = "cuda:0"):
        print(f"⚖️ [Evaluator] Loading T5 from {model_path}...")
        self.device = device
        
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = T5ForSequenceClassification.from_pretrained(model_path, num_labels=1)
        self.model.to(device)
        self.model.eval()
        
        print("✅ [Evaluator] Loaded successfully.")

    def _run_batch(self, inputs: List[str], ids: Optional[List[str]] = None, **kwargs) -> List[float]:
        """
        inputs: 已经是拼接好的 "Query [SEP] Doc" 字符串列表
        """
        # Tokenize
        tokenized = self.tokenizer(
            inputs, 
            return_tensors="pt",
            padding=True, 
            truncation=True, 
            max_length=512
        ).to(self.device)

        # Inference
        with torch.no_grad():
            outputs = self.model(
                input_ids=tokenized.input_ids,
                attention_mask=tokenized.attention_mask
            )
            # CRAG Inference.py 第 175 行: scores.append(float(outputs["logits"].cpu()))
            # 直接取 logits，不经过 sigmoid
            logits = outputs.logits.squeeze(-1).cpu().tolist()
            
        return logits
    
    def run_pair(self, queries: List[str], docs: List[str], ids: Optional[List[str]] = None) -> List[float]:
        """
        【修正】完全对齐官方 CRAG_Inference.py 的拼接逻辑
        """
        if len(queries) != len(docs):
            raise ValueError(f"Batch mismatch: Queries({len(queries)}) vs Docs({len(docs)})")
        
        # 官方代码逻辑：Query + ' [SEP] ' + Doc
        # 注意：[SEP] 前后各有一个空格
        inputs = [f"{q} [SEP] {d}" for q, d in zip(queries, docs)]
        
        return self.run(inputs, ids=ids)