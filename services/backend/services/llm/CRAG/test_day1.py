from .config.config_loader import settings
from .core_layer.generator_tool import GeneratorTool

def test_generator():
    # 1. 打印配置，检查是否正确加载
    print("Model Path:", settings.models['generator_path'])
    
    # 2. 初始化 Generator
    gen = GeneratorTool(
        model_path=settings.models['generator_path'],
        max_model_len=settings.params['max_model_len']
    )
    
    # 3. 测试单条
    print("\n--- Testing Single Input ---")
    res1 = gen.run("What is the capital of France?")
    print("Result 1:", res1)
    
    # 4. 测试 Batch
    print("\n--- Testing Batch Input ---")
# 模拟从 Loader 拿到的数据
    batch_prompts = [
        "Who is Michael Jordan?", 
        "Tell me a joke."
    ]
    batch_ids = [
        "popqa_001", 
        "popqa_002"
    ]
    # 透传 IDs (虽然 Generator 暂时不用它，但要确保管道畅通)
    res2 = gen.run(batch_prompts, ids=batch_ids)
    # 打印结果时，可以把 ID 带上，方便调试
    for i, res in enumerate(res2):
        print(f"[{batch_ids[i]}] Answer: {res[:50]}...") # 只打前50个字符

if __name__ == "__main__":
    test_generator()
