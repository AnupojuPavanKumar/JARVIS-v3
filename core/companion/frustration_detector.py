# core/companion/frustration_detector.py — JARVIS FRUSTRATION DETECTION
"""
Detects frustration patterns — repeated failures, rapid retries, error loops.
When frustrated, JARVIS should become quieter, more reliable, and less chatty.

Detects:
  - repeated failed commands
  - rapid retries (same command within 10s)
  - error loops (same error 3+ times)
  - tense interaction patterns (short, clipped commands)
  - sustained failure sequences

Wire into: CalmEngine level boost, FatigueModel, SuggestionEngine suppression.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

_MAX_HISTORY = 50


@dataclass
class InteractionSnapshot:
    command: str
    result: str
    success: bool
    timestamp: float
    latency_s: float
    category: str = ""


class FrustrationDetector:
    """
    Detects frustration and adapts JARVIS behavior accordingly.
    When the user is frustrated, JARVIS becomes calm, minimal, and reliable.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._history: deque[InteractionSnapshot] = deque(maxlen=_MAX_HISTORY)
        self._error_patterns: dict[str, int] = {}
        self._retry_patterns: dict[str, float] = {}
        self._frustration_level = 0.0
        self._last_frustration_check = time.time()

    def record(self, command: str, result: str, success: bool,
               latency_s: float = 0.0, category: str = ""):
        """Record an interaction for frustration pattern analysis."""
        with self._lock:
            snap = InteractionSnapshot(
                command=command.lower().strip(),
                result=result,
                success=success,
                timestamp=time.time(),
                latency_s=latency_s,
                category=category,
            )
            self._history.append(snap)
            self._update_frustration(snap)

    def _update_frustration(self, snap: InteractionSnapshot):
        now = time.time()

        if not snap.success:
            err_key = snap.result[:60] if snap.result else snap.command[:40]
            self._error_patterns[err_key] = self._error_patterns.get(err_key, 0) + 1

        cmd_key = snap.command[:50]
        if cmd_key in self._retry_patterns:
            gap = now - self._retry_patterns[cmd_key]
            if gap < 10:
                self._frustration_level = min(1.0, self._frustration_level + 0.15)
        self._retry_patterns[cmd_key] = now

        if not snap.success:
            self._frustration_level = min(1.0, self._frustration_level + 0.1)
        else:
            self._frustration_level = max(0.0, self._frustration_level - 0.05)

        self._frustration_level = max(0.0, min(1.0, self._frustration_level))

    @property
    def level(self) -> float:
        with self._lock:
            return self._frustration_level

    @property
    def is_frustrated(self) -> bool:
        return self.level > 0.5

    @property
    def is_very_frustrated(self) -> bool:
        return self.level > 0.7

    def should_be_minimal(self) -> bool:
        return self.is_frustrated

    def should_suppress_suggestions(self) -> bool:
        return self.is_frustrated

    def should_simplify(self) -> bool:
        return self.is_very_frustrated

    def get_adaptive_verbosity(self, base_verbosity: str) -> str:
        if self.is_very_frustrated:
            return "ultra_terse"
        elif self.is_frustrated:
            return "terse"
        return base_verbosity

    def get_response_style(self) -> str:
        if self.is_very_frustrated:
            return "minimal_direct"
        elif self.is_frustrated:
            return "brief_calm"
        return "normal"

    def recent_failures(self, window_s: float = 60) -> list[InteractionSnapshot]:
        cutoff = time.time() - window_s
        with self._lock:
            return [s for s in self._history if not s.success and s.timestamp > cutoff]

    def failure_count(self, window_s: float = 120) -> int:
        return len(self.recent_failures(window_s))

    def last_error(self) -> Optional[str]:
        with self._lock:
            for s in reversed(self._history):
                if not s.success:
                    return s.result[:80] if s.result else s.command[:60]
        return None

    def get_state(self) -> dict:
        with self._lock:
            return {
                "frustration": round(self._frustration_level, 3),
                "is_frustrated": self.is_frustrated,
                "recent_failures_60s": self.failure_count(60),
                "recent_failures_120s": self.failure_count(120),
                "last_error": self.last_error(),
                "style": self.get_response_style(),
            }


_instance: Optional[FrustrationDetector] = None
_lock = threading.Lock()


def get_frustration_detector() -> FrustrationDetector:
    global _instance
    with _lock:
        if _instance is None:
            _instance = FrustrationDetector()
        return _instance