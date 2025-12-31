import io
import wave
import math
import struct

def synthesize_wav_stub(text: str, seconds: float = 1.0, sr: int = 16000) -> bytes:
    """
    生成一段 440Hz 的正弦波音频（嘟——声），用于测试音频传输
    """
    nframes = int(seconds * sr)
    buf = io.BytesIO()
    
    # --- 声音参数配置 ---
    frequency = 440.0       # 频率 440Hz (标准 A 音)
    volume = 0.3 * 32767    # 音量 (30% 的最大音量，防止太炸耳)，16-bit 最大是 32767
    
    # --- 生成波形数据 ---
    audio_data = bytearray()
    
    for i in range(nframes):
        # 核心数学公式：振幅 = 音量 * sin(2 * π * 频率 * 当前时间)
        # i / sr 就是当前的时间点(秒)
        sample_value = int(volume * math.sin(2 * math.pi * frequency * i / sr))
        
        # 将数值打包成 16-bit signed little-endian 格式 (Standard WAV format)
        # "<h" 的意思是：小端序 (Little-endian), short (2 bytes)
        audio_data.extend(struct.pack("<h", sample_value))

    # --- 写入 WAV 文件头 ---
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)      # 单声道
        wf.setsampwidth(2)      # 16-bit
        wf.setframerate(sr)     # 采样率
        wf.writeframes(audio_data)
        
    return buf.getvalue()