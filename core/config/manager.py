# core/config/manager.py
"""
Hot reloadable configuration system — P13.
Live config reload without restart, validation, rollback on invalid configs.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("ConfigManager")


@dataclass
class ConfigSchema:
    """Schema for a configuration key."""
    name: str
    default: Any
    type: type
    min_value: Any = None
    max_value: Any = None
    options: list[Any] | None = None
    description: str = ""
    on_change: Callable[[Any, Any], None] | None = None


@dataclass
class ConfigSnapshot:
    key: str
    old_value: Any
    new_value: Any
    timestamp: float
    validated: bool
    rollback_from: Any | None = None


class ConfigManager:
    """
    Hot-reloadable configuration manager.
    Validates changes, supports rollback, notifies on-change callbacks.
    """

    def __init__(self):
        self._configs: dict[str, ConfigSchema] = {}
        self._values: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._history: deque[ConfigSnapshot] = deque(maxlen=200)
        self._observers: dict[str, list[Callable[[Any], None]]] = {}
        self._source_file: str | None = None

    def register_schema(self, schema: ConfigSchema):
        """Register a configuration schema with its default and constraints."""
        with self._lock:
            self._configs[schema.name] = schema
            if schema.name not in self._values:
                self._values[schema.name] = schema.default

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def set(self, key: str, value: Any, reason: str = "manual") -> tuple[bool, str]:
        """Set a config value with validation. Returns (success, message)."""
        with self._lock:
            if key not in self._configs:
                schema = ConfigSchema(name=key, default=value, type=type(value))
                self._configs[key] = schema
            schema = self._configs[key]
        valid, msg = self._validate(key, value, schema)
        if not valid:
            log.warning(f"[ConfigManager] Invalid value for '{key}': {msg}")
            return False, msg
        old_value = self.get(key)
        snapshot = ConfigSnapshot(key=key, old_value=old_value, new_value=value,
                                  timestamp=time.time(), validated=valid,
                                  rollback_from=old_value if valid else None)
        with self._lock:
            self._values[key] = value
            self._history.append(snapshot)
        if schema.on_change:
            try:
                schema.on_change(old_value, value)
            except Exception as e:
                log.warning(f"[ConfigManager] on_change error for '{key}': {e}")
        self._notify_observers(key, value)
        log.info(f"[ConfigManager] Config changed: {key} = {value} ({reason})")
        return True, "OK"

    def _validate(self, key: str, value: Any, schema: ConfigSchema) -> tuple[bool, str]:
        """Validate a value against its schema."""
        if not isinstance(value, schema.type) and schema.type not in (Any, type(None)):
            return False, f"Expected type {schema.type.__name__}, got {type(value).__name__}"
        if schema.min_value is not None and value < schema.min_value:
            return False, f"Value {value} below minimum {schema.min_value}"
        if schema.max_value is not None and value > schema.max_value:
            return False, f"Value {value} above maximum {schema.max_value}"
        if schema.options is not None and value not in schema.options:
            return False, f"Value {value} not in options: {schema.options}"
        return True, "OK"

    def rollback(self, key: str, steps: int = 1) -> tuple[bool, str]:
        """Rollback a config change to a previous value."""
        with self._lock:
            history = [h for h in self._history if h.key == key]
        if len(history) < steps:
            return False, f"Not enough history to rollback {steps} steps"
        target = history[-steps - 1] if steps < len(history) else history[0]
        return self.set(key, target.old_value, f"rollback to {target.old_value}")

    def observe(self, key: str, callback: Callable[[Any], None]):
        """Register an observer for a config key."""
        with self._lock:
            if key not in self._observers:
                self._observers[key] = []
            self._observers[key].append(callback)

    def _notify_observers(self, key: str, value: Any):
        with self._lock:
            cbs = list(self._observers.get(key, []))
        for cb in cbs:
            try:
                cb(value)
            except Exception as e:
                log.warning(f"[ConfigManager] observer error for '{key}': {e}")

    def load_from_file(self, path: str) -> tuple[int, int]:
        """Load config from JSON file. Returns (loaded, failed)."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            loaded, failed = 0, 0
            for key, value in data.items():
                ok, _ = self.set(key, value, f"file load from {path}")
                if ok:
                    loaded += 1
                else:
                    failed += 1
            with self._lock:
                self._source_file = path
            return loaded, failed
        except Exception as e:
            log.error(f"[ConfigManager] File load error: {e}")
            return 0, 0

    def save_to_file(self, path: str) -> bool:
        """Save current config to JSON file."""
        try:
            with self._lock:
                data = {k: self._values[k] for k in self._configs}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            log.error(f"[ConfigManager] File save error: {e}")
            return False

    def get_all(self) -> dict:
        with self._lock:
            return dict(self._values)

    def get_history(self, key: str | None = None, limit: int = 20) -> list[ConfigSnapshot]:
        with self._lock:
            history = list(self._history)
        if key:
            history = [h for h in history if h.key == key]
        return history[-limit:]

    def stats(self) -> dict:
        with self._lock:
            return {
                "registered_configs": len(self._configs),
                "current_values": len(self._values),
                "history_entries": len(self._history),
                "observers": sum(len(v) for v in self._observers.values()),
                "source_file": self._source_file,
            }


_global_config_manager: ConfigManager | None = None
_cm_lock = threading.Lock()


def get_config_manager() -> ConfigManager:
    global _global_config_manager
    with _cm_lock:
        if _global_config_manager is None:
            _global_config_manager = ConfigManager()
        return _global_config_manager
