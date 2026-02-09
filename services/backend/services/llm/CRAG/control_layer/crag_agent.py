import time
from .state import AgentState
from .nodes import CragNodes
from ..config.config_loader import settings


class CragAgent:
    def __init__(self, tools, method: str | None = None):
        """
        åˆå§‹åŒ?Agentï¼ŒåŠ è½½å·¥å…·èŠ‚ç‚?
        """
        self.nodes = CragNodes(tools)
        # æ”¯æŒ?å¤–éƒ¨æŒ‡å®šæ–¹æ³•
        self.method = (method or settings.params.get('method', 'crag')).strip().lower()
        print(f"ðŸ¤– [Agent] Initialized. Method: {self.method}")

    def run_batch(self, batch_data: dict, *, method: str | None = None):
        """
        æ‰§è¡Œ Batch æŽ¨ç†çš„ä¸»å¾ªçŽ¯
        batch_data: åŒ…å« 'ids', 'queries', 'raw_docs' çš„å­—å…?
        """
        start_time = time.time()

        run_method = (method or self.method or "crag").strip().lower()

        queries = batch_data.get("queries") or []
        if not queries:
            raise ValueError("batch_data['queries'] is required")
        ids = batch_data.get("ids") or list(range(len(queries)))

        raw_docs = batch_data.get("raw_docs")
        if raw_docs is None:
            raw_docs = [[] for _ in ids]
        raw_docs = list(raw_docs)
        if len(raw_docs) < len(ids):
            raw_docs = raw_docs + ([[]] * (len(ids) - len(raw_docs)))
        elif len(raw_docs) > len(ids):
            raw_docs = raw_docs[: len(ids)]

        ctx_override = batch_data.get("final_contexts")
        if isinstance(ctx_override, str):
            ctx_override = [ctx_override]
        if ctx_override is not None:
            ctx_override = list(ctx_override)
            if len(ctx_override) < len(ids):
                ctx_override = ctx_override + ([""] * (len(ids) - len(ctx_override)))
            elif len(ctx_override) > len(ids):
                ctx_override = ctx_override[: len(ids)]

        # 1. åˆå§‹åŒ–çŠ¶æ€?(Memory Backpack)
        state = AgentState(
            ids=ids,
            queries=queries,
            raw_docs=raw_docs
        )

        batch_size = len(state.ids)

        # 2. çŠ¶æ€æœºè°ƒåº¦ (Graph Execution)
        if run_method == 'crag':
            # === CRAG æ ‡å‡†æµç¨‹ ===
            # Step 1: è£åˆ¤æ‰“åˆ† (T5)
            state = self.nodes.evaluate_node(state)

            # Step 2: å†³ç­–è·¯ç”± (Correct / Ambiguous / Incorrect)
            state = self.nodes.decide_node(state)

            # Step 3: çŸ¥è¯†ä¿®æ­£ (Mock Retrieval)
            state = self.nodes.refine_node(state)

            # Step 4: ç”Ÿæˆå›žç­” (Self-RAG / Llama)
            state = self.nodes.generate_node(state)

        elif run_method == 'rag':
            # === Standard RAG (Naive) ===
            # è·³è¿‡è¯„ä¼°å’Œä¿®æ­£ï¼Œç›´æŽ?æŠŠæ£€ç´¢åˆ°çš„åŽŸå§‹æ–‡æ¡£æ‹¼èµ·æ¥å–‚ç»™æ¨¡åž‹
            # raw_docs æ˜?[[d1..d10], [d1..d10]]ï¼Œæˆ‘ä»¬éœ€è¦æ‹¼æˆå­—ç¬¦ä¸²
            if ctx_override is not None:
                state.final_contexts = ctx_override
            else:
                state.final_contexts = [" ".join(docs) for docs in state.raw_docs]
            state = self.nodes.generate_node(state)

        elif run_method in ('no_retrieval', 'context_only'):
            # === No Retrieval ===
            # ä¸Šä¸‹æ–‡å…¨ç©ºï¼Œé æ¨¡åž‹çžŽç¼?
            state.final_contexts = ctx_override or ["" for _ in state.queries]
            state = self.nodes.generate_node(state)

        else:
            raise ValueError(f"Unknown method: {run_method}")

        end_time = time.time()
        cost = end_time - start_time

        # ç®€å•æ‰“å°ä¸€ä¸‹è¿›åº¦ï¼Œé˜²æ­¢çœ‹èµ·æ¥åƒå¡æ­»äº?
        print(f"âœ?Batch finished in {cost:.2f}s (Avg: {cost/batch_size:.2f}s/q)")

        # è¿”å›žæœ€ç»ˆç­”æ¡ˆåˆ—è¡?
        return state.final_answers
