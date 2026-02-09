import os
from typing import List, Optional, Union
from .base_tool import BaseTool

class RefinerTool(BaseTool):
    def __init__(self, internal_path: str, external_path: str, combined_path: str):
        """
        Mock Retriever: 预加载所有知识库文件到内存。
        依赖于数据行的严格对齐 (Line-aligned)。
        """
        print("📚 [Refiner] Loading knowledge bases into memory...")
        
        # 1. 检查文件是否存在 (防御性编程)
        for name, path in [("internal", internal_path), ("external", external_path), ("combined", combined_path)]:
            if not os.path.exists(path):
                raise FileNotFoundError(f"Knowledge file not found: {path}")

        # 2. 加载文件
        self.knowledge_base = {
            "internal": self._load_file(internal_path),
            "external": self._load_file(external_path),
            "combined": self._load_file(combined_path)
        }
        
        # 3. 打印统计信息，确认加载无误
        # 假设三个文件行数应该一致，或者至少 internal 不为空
        count = len(self.knowledge_base['internal'])
        print(f"✅ [Refiner] Loaded successfully. (Approx {count} docs per file)")

    def _load_file(self, path: str) -> List[str]:
        with open(path, 'r', encoding='utf-8') as f:
            # 同样保留原始格式，strip掉换行符
            return [line.strip() for line in f.readlines()]

    def _run_batch(self, inputs: List[int], ids: Optional[List[str]] = None, **kwargs) -> List[str]:
        """
        【特殊】这里的 inputs 接收的是数据的 Index (List[int])，而不是查询字符串。
        
        参数 kwargs['type']: 必须指定 'internal' | 'external' | 'combined'
        """
        # 1. 获取知识类型，默认为 internal (Correct)
        k_type = kwargs.get('type', 'internal')
        target_kb = self.knowledge_base.get(k_type)
        
        if target_kb is None:
             # 防御性编程：防止传入错误的 type
            valid_keys = list(self.knowledge_base.keys())
            raise ValueError(f"[Refiner] Unknown knowledge type: '{k_type}'. Valid types: {valid_keys}")

        results = []
        for idx in inputs:
            # 2. 这里的 input 必须是 int
            if not isinstance(idx, int):
                # 如果传入了 query string，说明调用方搞错了，这里做个转换或报错
                # 暂时报错，强制要求上游传入 index
                raise TypeError(f"Refiner tool expects List[int] indices, got {type(idx)}")

            # 3. 查表获取文档
            if 0 <= idx < len(target_kb):
                results.append(target_kb[idx])
            else:
                # 越界兜底：通常不应该发生，除非 input_file 和 ref 文件行数不一致
                print(f"⚠️ [Refiner] Index {idx} out of bounds for {k_type} (len={len(target_kb)})")
                results.append("") 
                
        return results