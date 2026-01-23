# services/backend/config/config.py
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv

# 当前文件: .../services/backend/config/config.py
_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parent.parent  # .../services/backend
_ENV_PATH = _BACKEND_DIR / ".env"

# 只在这里加载一次 env，ws.py 不要再 load_dotenv
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

def _bool_env(key: str, default: str = "0") -> bool:
    v = (os.getenv(key, default) or default).strip().lower()
    return v in ("1", "true", "yes", "y", "on")

def _int_env(key: str, default: int | None = None) -> int | None:
    raw = (os.getenv(key, "") or "").strip()
    if raw.isdigit():
        return int(raw)
    return default

def _resolve_path(raw: str | None, base: Path) -> Path | None:
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_absolute() else (base / raw)

class Settings:
    def __init__(self):
        self.BASE_DIR = _BACKEND_DIR

        # 建议默认放 backend/logs（和你 ws.py 的 metrics_* 一致）
        raw_log_dir = os.getenv("LOG_DIR")
        self.LOG_DIR = Path(raw_log_dir) if raw_log_dir else (_BACKEND_DIR / "logs")
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)

        # 每次进程启动唯一；如你希望固定，可在 .env 里写死 SERVER_INSTANCE_ID
        self.SERVER_INSTANCE_ID = os.getenv("SERVER_INSTANCE_ID") or uuid.uuid4().hex

        # ---- LLM ----
        self.LLM_MODEL_DIR = os.getenv("LLM_MODEL_DIR", "models/selfrag_llama2_7b")

        # ---- TTS backend ----
        self.TTS_BACKEND = (os.getenv("TTS_BACKEND", "edge") or "edge").strip().lower()

        # ---- Piper common ----
        self.PIPER_USE_CUDA = _bool_env("PIPER_USE_CUDA", "0")
        self.PIPER_TARGET_SAMPLE_RATE = _int_env("PIPER_TARGET_SAMPLE_RATE", None)  # e.g. 16000

        # ---- Piper ZH ----
        # 兼容老变量：如果没写 *_ZH，就回落到 PIPER_MODEL_PATH / PIPER_CONFIG_PATH
        mp_zh = os.getenv("PIPER_MODEL_PATH_ZH") or os.getenv("PIPER_MODEL_PATH") or "models/voices/zh_CN-huayan-x_low.onnx"
        cp_zh = os.getenv("PIPER_CONFIG_PATH_ZH") or os.getenv("PIPER_CONFIG_PATH")  # 允许为空
        self.PIPER_MODEL_PATH_ZH = _resolve_path(mp_zh, _BACKEND_DIR)
        self.PIPER_CONFIG_PATH_ZH = _resolve_path(cp_zh, _BACKEND_DIR) if cp_zh else None

        # ---- Piper EN ----
        # 如果你没填 *_EN，就默认复用中文（保证不炸）
        mp_en = os.getenv("PIPER_MODEL_PATH_EN") or mp_zh
        cp_en = os.getenv("PIPER_CONFIG_PATH_EN") or cp_zh
        self.PIPER_MODEL_PATH_EN = _resolve_path(mp_en, _BACKEND_DIR)
        self.PIPER_CONFIG_PATH_EN = _resolve_path(cp_en, _BACKEND_DIR) if cp_en else None

        # ---- Auto language selection ----
        self.TTS_AUTO_LANG = _bool_env("TTS_AUTO_LANG", "1")
        self.TTS_LANG_DECIDE_CHARS = _int_env("TTS_LANG_DECIDE_CHARS", 120) or 120

settings = Settings()
