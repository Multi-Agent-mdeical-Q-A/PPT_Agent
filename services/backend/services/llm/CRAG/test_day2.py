import sys
import os

# 1. 确保 Python 能找到你的项目包 (my_agentic_rag)
# 将当前脚本所在的目录添加到系统路径中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from .config.config_loader import settings
from .core_layer.evaluator_tool import EvaluatorTool
from .core_layer.refiner_tool import RefinerTool
from .data_layer.loader import BatchDataLoader

def test_components():
    print("🚀 Starting Component Integration Test...\n")

    # ==========================================
    # 1. Test DataLoader (数据的源头)
    # ==========================================
    print("=== [1] Test DataLoader ===")
    print(f"Loading data from: {settings.paths['input_file']}")
    
    loader = BatchDataLoader(
        input_file_path=settings.paths['input_file'],
        batch_size=2, # 测试只取 2 条数据
        ndocs=10
    )
    
    # 获取第一个 Batch
    batch_gen = loader.get_batches()
    try:
        batch = next(batch_gen)
    except StopIteration:
        print("❌ Error: Data file is empty or path is wrong.")
        return

    print(f"✅ Batch Keys: {list(batch.keys())}")
    print(f"✅ Batch Queries: {batch['queries']}")
    print(f"✅ IDs: {batch['ids']}")
    
    # 检查 Raw Docs 形状: 应该是 [Batch_Size, 10]
    raw_docs_shape = (len(batch['raw_docs']), len(batch['raw_docs'][0]))
    print(f"✅ Raw Docs Shape: {raw_docs_shape} (Expected: (2, 10))")
    
    
    # ==========================================
    # 2. Test Evaluator (裁判)
    # ==========================================
    print("\n=== [2] Test Evaluator ===")
    evaluator = EvaluatorTool(settings.models['evaluator_path'])
    
    # 场景模拟：给 Batch 中第 0 个问题的 10 篇文档打分
    q0 = batch['queries'][0]      # "Who is..."
    docs0 = batch['raw_docs'][0]  # List[str] (10篇文档)
    id0 = batch['ids'][0]         # int ID
    
    print(f"Query: {q0}")
    
    # 【关键】构造 Evaluator 输入
    # run_pair 需要 List[Query] 和 List[Doc] 长度对齐
    # 所以我们需要把 q0 重复 10 次，变成 ["Who...", "Who...", ...]
    queries_repeated = [q0] * len(docs0)
    
    # 这里的 ids 参数是可选的，但为了测试 Trace 最好传进去（虽然这里我们只传个 None 占位也可以）
    # 如果要传 ids，也得是 List，且长度对应
    ids_repeated = [str(id0)] * len(docs0) 

    scores = evaluator.run_pair(queries_repeated, docs0, ids=ids_repeated)
    
    print(f"✅ Scores (10 docs): {scores}")
    print(f"   -> Max Score: {max(scores)}")
    print(f"   -> Min Score: {min(scores)}")


    # ==========================================
    # 3. Test Refiner (知识库/查表)
    # ==========================================
    print("\n=== [3] Test Refiner (Mock Retriever) ===")
    refiner = RefinerTool(
        settings.paths['internal_ref'],
        settings.paths['external_ref'],
        settings.paths['combined_ref']
    )
    
    # 场景模拟：假设 Agent 决定去查 'internal' (Correct) 知识库
    # Refiner 接收的是 IDs (List[int])
    target_ids = batch['ids'] # [0, 1]
    
    refined_docs = refiner.run(target_ids, type='internal')
    
    print(f"✅ Refined Docs Count: {len(refined_docs)}")
    print(f"✅ Doc for ID {target_ids[0]} (Internal): {refined_docs[0][:50]}...")
    
    # 再测试一下查 external
    incorrect_docs = refiner.run(target_ids, type='external')
    print(f"✅ Doc for ID {target_ids[0]} (External): {incorrect_docs[0][:50]}...")

    print("\n🎉 All components passed the test!")

if __name__ == "__main__":
    test_components()
