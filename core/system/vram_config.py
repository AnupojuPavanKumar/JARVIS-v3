# core/system/vram_config.py — Parses agent.yaml vram_strategy into runtime config
"""
Loads the vram_strategy section from agent.yaml and makes it available
to VRAMOrchestrator and other components that need hardware budget info.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

_default_config = {
    "budget_gb": 8.0,
    "eviction_threshold_pct": 75.0,
    "prefetch_priority": [
        {"intent": "WEB_RESEARCH",  "model": "qwen2.5-coder:7b"},
        {"intent": "AGENT_TASK",    "model": "deepseek-r1:7b"},
        {"intent": "SECURITY_AUDIT","model": "gemma2:2b"},
    ],
    "eviction_strategy": "lru",
}


class VRAMConfig:
    """
    Singleton that reads vram_strategy from agent.yaml.
    Falls back to defaults if YAML is unavailable or parse fails.
    """
    _instance: Optional["VRAMConfig"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._config = cls._instance._load()
        return cls._instance

    def _load(self) -> dict:
        """Load vram_strategy from agent.yaml, falling back to defaults."""
        if not YAML_AVAILABLE:
            return _default_config.copy()

        path = os.path.join(os.path.dirname(__file__), "..", "..", "agent.yaml")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            vs = data.get("vram_strategy", {}) if data else {}
            if vs:
                return vs
        except Exception:
            pass
        return _default_config.copy()

    def get(self, key: str, default=None):
        return self._config.get(key, default)

    @property
    def budget_gb(self) -> float:
        return float(self._config.get("budget_gb", 8.0))

    @property
    def eviction_threshold_pct(self) -> float:
        return float(self._config.get("eviction_threshold_pct", 75.0))

    @property
    def prefetch_priority(self) -> list[dict]:
        return self._config.get("prefetch_priority", _default_config["prefetch_priority"])

    def model_for_intent(self, intent: str) -> Optional[str]:
        for entry in self.prefetch_priority:
            if entry.get("intent") == intent:
                return entry.get("model")
        return None

    def refresh(self):
        """Re-read the YAML file (call after agent.yaml is edited)."""
        self._config = self._load()


def get_vram_config() -> VRAMConfig:
    return VRAMConfig()