from abc import ABC, abstractmethod
from typing import List, Union, Any, Optional

# 假设这是我们之后要写的装饰器，先占个位，或者暂时不引用
# from utils.tracing import trace_tool 

class BaseTool(ABC):
    """
    所有 Agent 工具的基类。
    职责：
    1. 规范接口：必须实现 run 方法。
    2. 统一处理：自动处理单条/批量输入的转换。
    3. 可观测性：(未来) 统一集成日志追踪。
    """

    @abstractmethod
    def _run_batch(self, inputs: List[Any], ids: Optional[List[str]] = None, **kwargs) -> List[Any]:
        """
        【核心逻辑】子类必须实现这个方法，处理 List 输入。
        注意：这里改名叫 _run_batch，强调子类只需要关注“批处理”逻辑。
        """
        pass

    def run(self, inputs: Union[str, List[str]], ids: Union[str, List[str], None] = None, **kwargs) -> Union[Any, List[Any]]:
        """
        【对外接口】外部调用这个方法。
        它负责：适配输入 -> 调用子类逻辑 -> 适配输出
        """
        
        # 1. 输入适配：全部转为 List
        batched_inputs, is_single_input = self._ensure_list(inputs)
        
        # 2. ID 适配：如果有 ID，也得转 List，且长度必须对齐
        batched_ids = None
        if ids is not None:
            batched_ids, is_single_id = self._ensure_list(ids)
            # 【防御性编程】断言：输入数量和ID数量必须一致
            if len(batched_inputs) != len(batched_ids):
                raise ValueError(f"Batch size mismatch: inputs({len(batched_inputs)}) vs ids({len(batched_ids)})")
        
        # 3. 调用子类的核心逻辑 (这里是真正干活的地方)
        # 未来可以在这里加 try-except 捕获所有工具的报错
        try:
            batched_outputs = self._run_batch(batched_inputs, ids=batched_ids, **kwargs)
        except Exception as e:
            # 【防御性编程】简单的错误兜底，防止整个 Batch 崩溃
            print(f"[Error] Tool {self.__class__.__name__} failed: {e}")
            return [] if not is_single_input else None

        # 4. 输出适配：如果进来是单个，出去也要拆包成单个
        if is_single_input:
            if batched_outputs and len(batched_outputs) > 0:
                return batched_outputs[0]
            return None # 或者空字符串，看具体需求
        
        return batched_outputs

    def _ensure_list(self, inputs: Union[str, List[str], Any]) -> tuple[List[Any], bool]:
        """
        辅助函数：实现自适应输入
        返回：(list_data, is_single_flag)
        """
        if isinstance(inputs, str):
            return [inputs], True
        elif isinstance(inputs, list):
            return inputs, False
        else:
            # 允许其他单体对象（如 int, dict），视作单条输入
            return [inputs], True