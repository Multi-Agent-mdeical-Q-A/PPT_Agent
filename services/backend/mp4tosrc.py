import whisper
import datetime
import torch
import os

def format_timestamp(seconds: float):
    """将秒数转换为 [HH:MM:SS] 格式"""
    td = datetime.timedelta(seconds=seconds)
    return str(td).split('.')[0].zfill(8)

def extract_dialogue(video_path, output_file="transcript_large_v3.txt"):
    # 1. 环境检测
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"检测到设备: {device.upper()}")
    
    # 2. 加载模型 (指定 large-v3)
    # 提示：首次运行会下载约 3GB 的模型文件
    print("正在加载 Whisper large-v3 模型... 请稍候")
    model = whisper.load_model("large-v3", device=device)

    # 3. 针对性 Prompt (根据你提供的文本特征定制)
    # 加上了老师提到的具体的插件名和技术方案
    my_prompt = (
        "这是一段关于 AI Agent 和 PPT 系统开发的专业对话。关键词：Cursor, Claude, "
        "Markdown, Slides, NotebookLM, Fallback, 降级方案, Superpowers 插件, "
        "重构, 兼容性, 扩充性, Context Window, 决策能力, 自动化配音, 提示词。"
    )

    if not os.path.exists(video_path):
        print(f"错误：找不到文件 {video_path}")
        return

    print(f"正在使用 large-v3 处理: {video_path}...")

    # 4. 执行转录
    # beam_size=5 增加搜索宽度，能提高准确率但略微减慢速度
    result = model.transcribe(
        video_path,
        language='zh',
        initial_prompt=my_prompt,
        beam_size=5,
        best_of=5,
        temperature=0,
        verbose=False # 设置为 False 不会在控制台刷屏，我们后面自己打印
    )

    # 5. 格式化输出
    with open(output_file, "w", encoding="utf-8") as f:
        print("\n--- 提取内容如下 ---")
        for segment in result['segments']:
            start = format_timestamp(segment['start'])
            end = format_timestamp(segment['end'])
            text = segment['text'].strip()
            
            # 过滤掉 ASR 偶尔产生的幻觉噪音（如重复的单字）
            if len(text) < 2:
                continue

            line = f"[{start} --> {end}] {text}"
            print(line)
            f.write(line + "\n")

    print(f"\n✅ 提取完成！模型：large-v3 | 结果保存至: {output_file}")

if __name__ == "__main__":
    video_name = "huibao.mp4" 
    extract_dialogue(video_name)