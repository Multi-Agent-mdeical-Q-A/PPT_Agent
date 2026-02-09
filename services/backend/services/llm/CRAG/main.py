import os
from tqdm import tqdm

# 1. 导入配置
from .config.config_loader import settings

# 2. 导入组件
from .core_layer.generator_tool import GeneratorTool
from .core_layer.evaluator_tool import EvaluatorTool
from .core_layer.refiner_tool import RefinerTool
from .data_layer.loader import BatchDataLoader
from .control_layer.crag_agent import CragAgent

def main():
    # --- 0. 启动日志 (不再需要 argparse) ---
    print(f"🚀 Starting Agentic CRAG...")
    print(f"   Task:   {settings.task_name}")
    print(f"   Method: {settings.params.get('method')}")
    print(f"   Device: {settings.params.get('device')}")

    # --- 1. 初始化 Core Layer ---
    print("\n[1/4] Initializing Core Tools...")
    
    # Generator: 显式传递显存参数
    generator = GeneratorTool(
        model_path=settings.models['generator_path'],
        max_model_len=settings.params.get('max_model_len', 2048),
        # 读取 yaml 中的 gpu_memory_utilization，如果没有则默认 0.7
        gpu_utilization=settings.params.get('gpu_memory_utilization', 0.7)
    )
    
    # Evaluator: 传递 Device 参数
    evaluator = EvaluatorTool(
        model_path=settings.models['evaluator_path'],
        device=settings.params.get('device', 'cuda:0')
    )
    
    refiner = RefinerTool(
        internal_path=settings.paths['internal_ref'],
        external_path=settings.paths['external_ref'],
        combined_path=settings.paths['combined_ref']
    )
    
    tools = {
        "generator": generator,
        "evaluator": evaluator,
        "refiner": refiner
    }

    # --- 2. 初始化 Control Layer ---
    print("\n[2/4] Initializing Agent...")
    agent = CragAgent(tools)

    # --- 3. 初始化 Data Layer ---
    print("\n[3/4] Loading Data...")
    loader = BatchDataLoader(
        input_file_path=settings.paths['input_file'],
        batch_size=settings.params.get('batch_size', 8),
        ndocs=settings.params.get('ndocs', 10) # 动态读取 ndocs
    )

    # --- 4. 主循环 ---
    print(f"\n[4/4] Running Inference (Batch Size={loader.batch_size})...")
    
    all_predictions = []
    # 防止除零错误
    if loader.batch_size > 0:
        total_batches = (len(loader.data) + loader.batch_size - 1) // loader.batch_size
    else:
        total_batches = 0

    # 在 main.py 的循环里
    for batch_data in tqdm(loader.get_batches(), total=total_batches, desc="Processing Batches"):
        try:
            batch_answers = agent.run_batch(batch_data)
            
            # 【调试代码】检查长度是否对齐
            input_len = len(batch_data['ids'])
            output_len = len(batch_answers)
            
            if input_len != output_len:
                print(f"\n🚨 Data Mismatch in batch {batch_data['ids'][0]}!")
                print(f"   Input: {input_len}, Output: {output_len}")
                # 强行补齐，防止错位
                diff = input_len - output_len
                batch_answers.extend(["Error"] * diff)
            
            all_predictions.extend(batch_answers)
            
        except Exception as e:
            print(f"\n❌ Error in batch {batch_data.get('ids', 'unknown')}: {e}")
            # 错误填充
            if 'ids' in batch_data:
                all_predictions.extend(["Error"] * len(batch_data['ids']))
                
    # --- 5. 保存结果 ---
    output_file = settings.paths['output_file']
    print(f"\n💾 Saving {len(all_predictions)} predictions to {output_file}...")
    
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_predictions))
        
    print("✨ Inference Complete!")

if __name__ == "__main__":
    main()
