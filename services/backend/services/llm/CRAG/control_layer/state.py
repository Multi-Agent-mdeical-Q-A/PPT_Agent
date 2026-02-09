from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class AgentState:
    """
    Agent 在一次 Batch 执行中的上下文状态。
    """
    # 1. 基础输入 (必填)
    ids: List[int]
    queries: List[str]
    raw_docs: List[List[str]] # 维度: [Batch, 10]
       
    # 2. 中间状态 (过程中填充)
    scores: Optional[List[List[float]]] = None # Evaluator 打分
    flags: Optional[List[str]] = None          # Correct/Incorrect/Ambiguous
    search_queries: Optional[List[str]] = None # (未来) 搜索词
    final_contexts: Optional[List[str]] = None # 最终选定的知识片段
    
    # 3. 最终输出
    final_answers: Optional[List[str]] = None