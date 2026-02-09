from typing import List
from .state import AgentState
from ..config.config_loader import settings
# 引入新的 PromptBuilder
from .prompt_builder import PromptBuilder

class CragNodes:
    def __init__(self, tools):
        self.tools = tools

    def evaluate_node(self, state: AgentState) -> AgentState:
        """
        [Node 1] 裁判节点
        """
        print("🤔 [Node] Evaluating retrieval quality...")
        
        all_scores = []
        # 逐个问题处理
        for _id, q, docs in zip(state.ids, state.queries, state.raw_docs):
            
            # 【优化点】
            # 如果 docs 为空 (比如某些数据源缺失)，这里会导致 q_repeated 为空，evaluator 报错。
            # 加一个简单的防御
            if not docs:
                all_scores.append([0.0] * 10) # 填充默认低分
                continue

            q_repeated = [q] * len(docs)
            id_repeated = [str(_id)] * len(docs)
            
            # 调用 EvaluatorTool
            scores = self.tools['evaluator'].run_pair(q_repeated, docs, ids=id_repeated)
            all_scores.append(scores)
            
        state.scores = all_scores
        return state

    def decide_node(self, state: AgentState) -> AgentState:
        """
        [Node 2] 决策节点
        """
        print("⚖️ [Node] Making decisions (Correct/Ambiguous/Incorrect)...")
        upper = settings.params['upper_threshold']
        lower = settings.params['lower_threshold']
        
        flags = []
        # 注意：这里假设 state.scores 和 queries 长度一致
        for scores in state.scores:
            doc_flags = []
            for s in scores:
                if s >= upper: doc_flags.append(2)
                elif s >= lower: doc_flags.append(1)
                else: doc_flags.append(0)
            
            if 2 in doc_flags: 
                final_flag = "internal"
            elif 1 in doc_flags: 
                final_flag = "combined"
            else: 
                final_flag = "external"
            
            flags.append(final_flag)
            
        state.flags = flags
        return state

    def refine_node(self, state: AgentState) -> AgentState:
        """
        [Node 3] 执行节点 (Mock Retrieval)
        """
        print("✂️ [Node] Refining knowledge (Mock Retrieval)...")
        
        contexts = []
        for _id, flag in zip(state.ids, state.flags):
            res = self.tools['refiner'].run([_id], type=flag)
            if res and len(res) > 0:
                contexts.append(res[0])
            else:
                contexts.append("") 
            
        state.final_contexts = contexts
        return state

    def generate_node(self, state: AgentState) -> AgentState:
        """
        [Node 4] 生成节点：组装 Prompt 并调用 LLM
        """
        print("✍️ [Node] Generating answers...")
        prompts = []
        
        # 1. 获取动态配置参数
        # 从 settings 读取 task (popqa/pubqa)
        current_task = settings.task_name
        if not current_task:
            current_task = 'popqa' # 兜底默认值
            
        # 【新增】从 settings 读取 model_type (selfrag/llama)
        # 这解决了你提到的“不要写死”的问题
        gen_type = settings.models.get('generator_type', 'llama')

        # 2. 组装 Batch Prompts
        for q, ctx in zip(state.queries, state.final_contexts):
            
            # 使用 PromptBuilder 工厂构建 Prompt
            # 这里的 model_name 参数现在是动态的了
            prompt = PromptBuilder.build(
                task=current_task, 
                question=q, 
                context=ctx,
                model_name=gen_type 
            )
            prompts.append(prompt)
            
        # 3. 批量生成
        str_ids = [str(i) for i in state.ids]
        answers = self.tools['generator'].run(prompts, ids=str_ids)
        
        state.final_answers = answers
        return state
