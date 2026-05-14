# core/intents/shortcuts.py
"""
Smart execution shortcuts — hot-path optimizations.
Command precompilation, hot command acceleration, execution prediction,
adaptive caching for frequently used commands.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("Shortcuts")


@dataclass
class Shortcut:
    """A precompiled execution shortcut."""
    command: str
    command_normalized: str
    intent_name: str
    resolved_target: str | None
    precompiled_payload: Any | None = None
    hit_count: int = 0
    last_hit: float = field(default_factory=time.time)
    avg_latency_ms: float = 0.0
    total_hits: int = 0
    is_hot: bool = False
    hot_threshold: int = 3

    def mark_hit(self, latency_ms: float):
        self.hit_count += 1
        self.total_hits += 1
        self.last_hit = time.time()
        self.avg_latency_ms = (
            (self.avg_latency_ms * (self.hit_count - 1) + latency_ms) / self.hit_count
        )
        if self.hit_count >= self.hot_threshold and self.avg_latency_ms < 200:
            self.is_hot = True


class ShortcutRegistry:
    """
    Hot-path execution shortcuts with adaptive caching.
    Frequently used commands bypass most routing overhead.
    """

    def __init__(self, max_shortcuts: int = 100, hot_threshold: int = 3, hot_latency_ms: float = 200.0):
        self._max_shortcuts = max_shortcuts
        self._hot_threshold = hot_threshold
        self._hot_latency_ms = hot_latency_ms
        self._shortcuts: dict[str, Shortcut] = {}
        self._hot_shortcuts: dict[str, Shortcut] = {}
        self._lock = threading.RLock()
        self._recent_hits: deque[str] = deque(maxlen=50)

    def register(self, command: str, intent_name: str, resolved_target: str | None = None):
        """Register a command shortcut."""
        normalized = command.lower().strip()
        with self._lock:
            if normalized in self._shortcuts:
                return
            shortcut = Shortcut(
                command=command,
                command_normalized=normalized,
                intent_name=intent_name,
                resolved_target=resolved_target,
            )
            self._shortcuts[normalized] = shortcut
            if len(self._shortcuts) > self._max_shortcuts:
                self._evict_cold()

    def get(self, command: str) -> Shortcut | None:
        """Get a shortcut for a command."""
        normalized = command.lower().strip()
        with self._lock:
            return self._shortcuts.get(normalized)

    def mark_execution(self, command: str, latency_ms: float):
        """Record a command execution for hot-path promotion."""
        normalized = command.lower().strip()
        with self._lock:
            shortcut = self._shortcuts.get(normalized)
            if shortcut:
                shortcut.mark_hit(latency_ms)
                self._recent_hits.append(normalized)
                if shortcut.is_hot and normalized not in self._hot_shortcuts:
                    self._hot_shortcuts[normalized] = shortcut
            else:
                self._shortcuts[normalized] = Shortcut(
                    command=command,
                    command_normalized=normalized,
                    intent_name="UNKNOWN",
                    resolved_target=None,
                    hit_count=1,
                    total_hits=1,
                )

    def is_hot(self, command: str) -> bool:
        normalized = command.lower().strip()
        with self._lock:
            shortcut = self._shortcuts.get(normalized)
            return shortcut.is_hot if shortcut else False

    def get_hot_commands(self) -> list[Shortcut]:
        with self._lock:
            return sorted(self._hot_shortcuts.values(), key=lambda s: s.hit_count, reverse=True)

    def predict_next(self, context: str) -> list[Shortcut]:
        """Predict likely next commands based on context pattern."""
        with self._lock:
            recent = list(self._recent_hits)
        if not recent:
            return []
        predictions = []
        with self._lock:
            for cmd in recent[-5:]:
                if cmd in self._shortcuts:
                    predictions.append(self._shortcuts[cmd])
        return sorted(predictions, key=lambda s: s.last_hit, reverse=True)[:5]

    def _evict_cold(self):
        """Evict cold shortcuts to make room."""
        cold = sorted(
            [s for s in self._shortcuts.values() if not s.is_hot],
            key=lambda s: (s.last_hit, s.hit_count)
        )
        if cold:
            removed = cold[:3]
            for s in removed:
                self._shortcuts.pop(s.command_normalized, None)
                self._hot_shortcuts.pop(s.command_normalized, None)

    def stats(self) -> dict:
        with self._lock:
            hot = [s for s in self._shortcuts.values() if s.is_hot]
            return {
                "total_shortcuts": len(self._shortcuts),
                "hot_shortcuts": len(hot),
                "total_executions": sum(s.total_hits for s in self._shortcuts.values()),
                "avg_hot_latency_ms": round(sum(s.avg_latency_ms for s in hot) / len(hot), 1) if hot else 0,
                "top_hot": [{"command": s.command, "hits": s.total_hits, "latency_ms": round(s.avg_latency_ms, 1)}
                            for s in sorted(hot, key=lambda x: x.total_hits, reverse=True)[:10]],
            }


_global_shortcuts: ShortcutRegistry | None = None
_shortcuts_lock = threading.Lock()


def get_shortcut_registry() -> ShortcutRegistry:
    global _global_shortcuts
    with _shortcuts_lock:
        if _global_shortcuts is None:
            _global_shortcuts = ShortcutRegistry()
        return _global_shortcuts
