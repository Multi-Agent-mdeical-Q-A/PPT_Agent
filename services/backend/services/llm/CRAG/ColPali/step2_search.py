import os
import sys
import base64
import io
from pathlib import Path
from PIL import Image

# ================= 配置模型保存路径 (和 Step 1 保持完全一致) =================
# 1. 获取当前脚本所在的目录
current_file_path = Path(__file__).resolve()
# 2. 获取项目根目录 (Agentic_RAG)
project_root = current_file_path.parent.parent 
# 3. 定义你的模型文件夹路径
local_model_path = project_root / "models"

# 4. 关键：再次设置环境变量 HF_HOME
# 这样 step2 就会去这个文件夹找模型，而不是去下载
os.environ["HF_HOME"] = str(local_model_path)

print(f"🚀 使用本地模型路径: {local_model_path}")
# =========================================================================

from byaldi import RAGMultiModalModel

# 加载索引
# 注意：index_path 默认在当前目录的 .byaldi 文件夹下，只要你是在同级目录运行就不需要改
print("正在加载索引和模型...")
RAG = RAGMultiModalModel.from_index("biology_course_index")

# 用户提问
user_query = "你好"

# 执行检索 (k=1 找最相关的一张)
print(f"正在检索: {user_query}")
results = RAG.search(user_query, k=1)

# 输出结果并保存图片
if len(results) == 0:
    print("❌ 没有找到相关结果")
else:
    for i, result in enumerate(results):
        print(f"\n--- 结果 {i+1} ---")
        print(f"文档 ID: {result.doc_id}")
        print(f"页码: {result.page_num}")
        print(f"相似度: {result.score}")
        
        # === 保存图片逻辑 ===
        # byaldi 的 result 包含 base64 编码的图片数据
        if hasattr(result, 'base64'):
            img_data = base64.b64decode(result.base64)
            image = Image.open(io.BytesIO(img_data))
            
            # 保存到本地看看对不对
            save_name = f"result_page_{result.page_num}.png"
            image.save(save_name)
            print(f"✅ 检索到的图片已保存为: {save_name}")
        else:
            print("⚠️ 结果中未包含图片数据")