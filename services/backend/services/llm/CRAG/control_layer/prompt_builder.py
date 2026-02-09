from typing import Optional
from ..config.config_loader import settings

class PromptBuilder:
    # 从官方代码提取的任务指令字典
    TASK_INST = {
        "wow": "Given a chat history separated by new lines, generates an informative, knowledgeable and engaging response. ",
        "pubqa": "Is the following statement correct or not? Say true if it's correct; otherwise say false.",
        "eli5": "Provide a paragraph-length response using simple words to answer the following question.",
        "obqa": "Given four answer candidates, A, B, C and D, choose the best answer choice.",
        "arc_easy": "Given four answer candidates, A, B, C and D, choose the best answer choice.",
        "arc_challenge": "Given four answer candidates, A, B, C and D, choose the best answer choice.",
        "asqa": "Answer the following question. The question may be ambiguous and have multiple correct answers..."
    }

    @staticmethod
    def build(task: str, question: str, context: Optional[str] = None, model_name: str = "selfrag_llama2_7b") -> str:
        """
        统一入口：根据 task 和 model_name 自动分发 Prompt 逻辑
        """
        task = task.lower()

        if task == "popqa":
            # PopQA 在官方代码中格式比较特殊，通常不依赖模型区分
            return PromptBuilder._format_popqa(question, context)
        elif task == "pubqa":
            return PromptBuilder._format_pubqa(question, context, model_name)
        else:
            return PromptBuilder._format_default(question, context, task)

    @staticmethod
    def _format_popqa(question: str, context: Optional[str] = None) -> str:
        """
        PopQA 模板
        """
        # 【修复】同步获取截断长度配置
        limit = settings.params.get('context_max_len', 4000)
        
        # 【修复】增加截断逻辑，防止 vLLM 报错
        if context and len(context) > limit:
            context = context[:limit]
            
        if context and len(context.strip()) > 0:
            prompt = (
                f"Refer to the following documents, follow the instruction and answer the question.\n\n"
                f"Documents: {context}\n\n"
                f"Instruction: Answer the question: {question}"
            )
        else:
            prompt = f"Instruction: Answer the question: {question}"
        return prompt

    @staticmethod
    def _format_pubqa(question: str, context: Optional[str] = None, model_name: str = "selfrag_llama2_7b") -> str:
        """
        PubQA 模板: 严格区分 Llama 和 Self-RAG 格式
        """

        limit = settings.params.get('context_max_len', 4000)
        # 1. 截断逻辑 (CRAG 官方限制)
        if context and len(context) > limit:
            context = context[:limit]

        # 2. 判断是否是 Self-RAG 模型
        # 只要模型名字里带 "selfrag"，就走特殊格式
        is_selfrag = "selfrag" in model_name.lower()

        if not is_selfrag:
            # === 普通 Llama 格式 ===
            if context:
                prompt = (
                    f"Read the documents and answer the question: Is the following statement correct or not? \n\n"
                    f"Documents: {context}\n\n"
                    f"Statement: {question}\n\n"
                    f"Only say true if the statement is true; otherwise say false."
                )
            else:
                prompt = (
                    f"Is the following statement correct or not? \n\n"
                    f"Statement: {question}\n\n"
                    f"Only say true if the statement is true; otherwise say false."
                )
        else:
            # === Self-RAG 专用格式 (CRAG_Inference.py lines 64-69) ===
            # 格式解析: 
            # ### Instruction:
            # [Task Instruction]
            # ## Input:
            # [Question]
            # ### Response:
            # [Retrieval]<paragraph>[Context]</paragraph>
            
            base_instruction = PromptBuilder.TASK_INST.get("pubqa")
            # 拼接 Instruction 和 Input
            full_instruction = f"{base_instruction}\n\n## Input:\n\n{question}"
            
            prompt = f"### Instruction:\n{full_instruction}\n\n### Response:\n"
            
            if context:
                # Self-RAG 的核心：必须用 [Retrieval]<paragraph> 包裹内容
                prompt += f"[Retrieval]<paragraph>{context}</paragraph>"
        
        return prompt

    @staticmethod
    def _format_default(question: str, context: Optional[str] = None, task: str = None) -> str:
        instruction = PromptBuilder.TASK_INST.get(task, "Answer the question.")
        if context:
            prompt = (
                f"Refer to the following documents, follow the instruction and answer the question.\n\n"
                f"Documents: {context}\n\n"
                f"Instruction: {instruction}\nInput: {question}"
            )
        else:
            prompt = f"Instruction: {instruction}\nInput: {question}"
        return prompt
