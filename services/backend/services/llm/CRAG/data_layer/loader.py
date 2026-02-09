import os
from typing import List, Dict, Generator
from tqdm import tqdm

class BatchDataLoader:
    def __init__(self, input_file_path: str, batch_size: int = 8, ndocs: int = 10):
        """
        input_file_path: 对应 test_popqa.txt
        batch_size: 批处理大小
        ndocs: 每个问题对应的检索文档数 (CRAG 默认为 10)
        """
        self.batch_size = batch_size
        self.ndocs = ndocs
        self.data = self._load_data(input_file_path)
        print(f"📦 [DataLoader] Successfully loaded {len(self.data)} questions from {input_file_path}")

    def _load_data(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"{path} not found")

        samples = []
        
        print(f"⏳ [DataLoader] Parsing file...")
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        # 计算总问题数
        total_questions = len(lines) // self.ndocs
        
        for i in tqdm(range(total_questions), desc="Loading Data"):
            # 取出属于当前问题的 chunk (ndocs行)
            chunk = lines[i*self.ndocs : (i+1)*self.ndocs]
            
            # 1. 提取 Question (取 Chunk 的第一行即可)
            # 格式: "Who is ... [SEP] Doc..."
            first_line = chunk[0].strip()
            parts = first_line.split(" [SEP] ") # 注意空格
            
            if len(parts) >= 1:
                question = parts[0]
            else:
                question = "" # 异常数据兜底

            # 2. 提取 10 个 Pure Docs (不含 Query，不含 [SEP])
            raw_docs = []
            for line in chunk:
                # 去掉行末可能的 label (比如 "\t0")
                line_content = line.strip().split("\t")[0]
                
                # 【关键修正】拆分出 Doc 部分
                # 假设格式严格为 "Query [SEP] Doc"
                seg_parts = line_content.split(" [SEP] ")
                if len(seg_parts) >= 2:
                    # 取 [SEP] 后面的部分作为文档
                    # 有时候文档里也有 [SEP]，所以要取 [1:] 并 join 比较稳妥，或者只取 [1]
                    doc_text = " ".join(seg_parts[1:]) 
                else:
                    # 如果没有 [SEP]，可能这行就是纯文档，或者格式坏了
                    doc_text = line_content
                
                raw_docs.append(doc_text)

            samples.append({
                "id": i,               # int, 用于 RefinerTool 索引
                "query": question,     # str
                "raw_docs": raw_docs,  # List[str], 纯文档内容
                "golds": []            # 预留给标准答案 (如果有的话)
            })
            
        return samples

    def get_batches(self) -> Generator[Dict[str, List], None, None]:
        """
        生成器，每次 yield 一个 batch
        """
        total = len(self.data)
        # 使用 yield 节省内存
        for i in range(0, total, self.batch_size):
            batch_samples = self.data[i : i + self.batch_size]
            
            # 构造 Batch 字典 (Column-oriented format)
            # 这种格式最适合 Agent 批量处理
            batch = {
                "ids": [s["id"] for s in batch_samples],          # List[int]
                "queries": [s["query"] for s in batch_samples],    # List[str]
                "raw_docs": [s["raw_docs"] for s in batch_samples] # List[List[str]] -> [Batch, 10]
            }
            yield batch