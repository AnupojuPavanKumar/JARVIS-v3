# core/context/attention.py — JARVIS ATTENTION MODEL
"""
Estimates user attention level from behavioral signals.
Used to adapt:
  - when JARVIS speaks (or stays silent)
  - how verbose the response is
  - how aggressive proactive suggestions are
  - notification timing

Signals used (all local, no surveillance):
  - WorkspaceObserver: active app, category, workflow
  - keyboard activity frequency
  - mouse movement patterns
  - time since last input
  - fullscreen state
  - meeting detection

Confidence thresholds prevent over-interruptions.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto

@dataclass
class AttentionState:
    level: str          # "focused" | "active" | "relaxed" | "idle" | "absent"
    confidence: float   # 0.0 – 1.0
    reasons: list[str]  # why this level was chosen
    timestamp: float

    def is_focused(self) -> bool:
        return self.level in ("focused", "absent")

    def should_interrupt(self) -> bool:
        """True if assistant should be able to interrupt user."""
        return self.level in ("active", "relaxed")

    def verbosity_modifier(self) -> float:
        """1.0 = full verbosity, 0.5 = terse, 0.0 = silent."""
        return {"focused": 0.3, "active": 1.0, "relaxed": 0.9, "idle": 0.5, "absent": 0.0}.get(self.level, 0.5)


class AttentionModel:
    """
    Computes attention state from workspace + activity signals.
    Thread-safe, reads from WorkspaceObserver.
    """

    # Thresholds
    _IDLE_THRESHOLD     = 120.0   # seconds before "idle"
    _ABSENT_THRESHOLD  = 600.0   # seconds before "absent"
    _FOCUSED_KEYWORDS  = ["coding", "game", "meeting", "office"]
    _RELAXED_KEYWORDS  = ["browser", "media", "social", "reading"]

    def __init__(self, workspace=None):
        self._ws = workspace
        self._state = AttentionState(
            level="active",
            confidence=0.5,
            reasons=["initial"],
            timestamp=time.time(),
        )
        self._lock = threading.RLock()

    def set_workspace(self, workspace):
        self._ws = workspace

    def evaluate(self) -> AttentionState:
        """Compute current attention state from all available signals."""
        with self._lock:
            reasons = []
            idle_sec = 0.0
            cat = "unknown"
            workflow = None
            is_fs = False
            typing = 0.0

            if self._ws:
                idle_sec = getattr(self._ws, "idle_seconds", 0.0) or 0.0
                cat = getattr(self._ws, "current_category", "unknown") or "unknown"
                workflow = getattr(self._ws, "workflow", None) or ""
                is_fs = False
                if hasattr(self._ws, "_current") and self._ws._current:
                    is_fs = getattr(self._ws._current, "is_fullscreen", False) or False
                typing = getattr(self._ws, "typing_speed", 0.0) or 0.0

            # ── Level determination ─────────────────────────────────────────────
            if idle_sec > self._ABSENT_THRESHOLD:
                level = "absent"
                reasons.append(f"away for {idle_sec/60:.0f}min")
                conf = 0.9
            elif idle_sec > self._IDLE_THRESHOLD:
                level = "idle"
                reasons.append(f"idle for {idle_sec:.0f}s")
                conf = 0.8
            elif is_fs:
                level = "focused"
                reasons.append("fullscreen")
                conf = 0.85
            elif cat in self._FOCUSED_KEYWORDS:
                level = "focused"
                reasons.append(f"focused app ({cat})")
                conf = 0.75
            elif workflow in ("coding_session", "coding_research"):
                level = "focused"
                reasons.append(f"workflow: {workflow}")
                conf = 0.7
            elif cat in self._RELAXED_KEYWORDS:
                level = "relaxed"
                reasons.append(f"relaxed app ({cat})")
                conf = 0.65
            elif typing > 5.0:
                level = "active"
                reasons.append(f"typing at {typing:.0f}c/s")
                conf = 0.6
            else:
                level = "active"
                reasons.append(f"general ({cat})")
                conf = 0.5

            self._state = AttentionState(
                level=level,
                confidence=conf,
                reasons=reasons,
                timestamp=time.time(),
            )
            return self._state

    @property
    def state(self) -> AttentionState:
        with self._lock:
            return self._state

    def should_suggest(self, urgency: str = "normal") -> bool:
        """
        Decide if a proactive suggestion should fire.
        urgency: "low" | "normal" | "high" | "critical"
        """
        state = self.evaluate()
        if state.level == "absent":
            return urgency == "critical"
        if state.level == "idle":
            return urgency in ("normal", "high", "critical")
        if state.level == "focused":
            return urgency in ("high", "critical")
        return True  # active or relaxed → always suggest

    def interruption_cost(self) -> float:
        """
        Returns 0.0–1.0: how costly is an interruption right now?
        0.0 = free to interrupt, 1.0 = never interrupt.
        """
        state = self._state
        base = {
            "absent":  1.0,
            "focused": 0.85,
            "idle":    0.3,
            "active":  0.1,
            "relaxed": 0.05,
        }.get(state.level, 0.5)
        # Confidence adjusts cost slightly
        adj = (1.0 - state.confidence) * 0.1
        return min(1.0, base + adj)


# Singleton
_instance: AttentionModel | None = None
_lock = threading.Lock()

def get_attention_model() -> AttentionModel:
    global _instance
    with _lock:
        if _instance is None:
            _instance = AttentionModel()
        return _instance