import yaml
import os
from pathlib import Path


class Config:
    def __init__(self, config_path=None):
        # 1. åŽŸå§‹é…ç½®è·¯å¾„
        if config_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(current_dir, "settings.yaml")

        # base backend dir: .../services/backend
        # config_loader.py -> config -> CRAG -> llm -> services -> backend
        self._base_dir = Path(__file__).resolve().parents[4]

        # 2. åŠ è½½ YAML
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                self.cfg = yaml.safe_load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"é…ç½®æ–‡ä»¶æœªæ‰¾åˆ°ï¼Œè¯·æ£€æŸ¥è·¯å¾? {config_path}")

    # --- åŸºç¡€é…ç½®å?---
    @property
    def paths(self):
        return self.cfg.get("paths", {})

    @property
    def models(self):
        models = self.cfg.get("models", {}) or {}
        resolved = dict(models)
        for key in ("generator_path", "evaluator_path"):
            raw = models.get(key)
            if raw:
                resolved[key] = str(self._resolve_path(raw))
        return resolved

    @property
    def params(self):
        return self.cfg.get("parameters", {})

    # --- å¿«æ·å±žæ€?(Shortcuts) ---
    @property
    def task_name(self):
        """èŽ·å–å½“å‰ä»»åŠ¡å?(popqa/pubqa)"""
        return self.cfg.get("task", "popqa")

    @property
    def generator_type(self):
        """èŽ·å–ç”Ÿæˆå™¨ç±»åž?(llama/selfrag)"""
        return self.models.get("generator_type", "llama")

    def _resolve_path(self, raw: str):
        p = Path(raw)
        if p.is_absolute():
            return p
        return (self._base_dir / p).resolve()


# å•ä¾‹æ¨¡å¼
settings = Config()
