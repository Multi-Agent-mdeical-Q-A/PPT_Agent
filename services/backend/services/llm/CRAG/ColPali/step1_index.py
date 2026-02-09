import os
import sys
from pathlib import Path

# ================= 配置模型保存路径 (核心修改) =================
# 1. 获取当前脚本所在的目录 (ColPali)
current_file_path = Path(__file__).resolve()
# 2. 获取项目根目录 (Agentic_RAG) - 假设 ColPali 是根目录下的子文件夹
project_root = current_file_path.parent.parent 
# 3. 定义你的模型文件夹路径 (例如 Agentic_RAG/models)
local_model_path = project_root / "models"

# 4. 关键：设置环境变量 HF_HOME
# 这行代码必须在 import transformers 或 byaldi 之前执行
# 这样 HuggingFace 就会把下载的 15GB 文件存到这里
os.environ["HF_HOME"] = str(local_model_path)

print(f"🚀 模型将被下载并保存到: {local_model_path}")
# =============================================================

from byaldi import RAGMultiModalModel

# 加载 ColQwen2 模型
# 第一次运行会自动下载，现在它会下载到你上面设置的 model 文件夹里
print("正在加载模型...")
RAG = RAGMultiModalModel.from_pretrained("vidore/colqwen2-v0.1")

# ... 后面的索引代码不变 ...
print("开始索引 PDF (这可能需要几分钟)...")

# 💡 小建议：索引文件默认会存到 .byaldi 文件夹。
# 如果你想把索引文件存到截图里的 'data_layer' 文件夹，可以加 index_root 参数
# 比如：index_root=str(project_root / "data_layer")
RAG.index(
    input_path="biology_textbook.pdf", 
    index_name="biology_course_index",
    store_collection_with_index=True,
    overwrite=True
)

print("索引完成！")