# core/companion/fatigue_model.py — JARVIS INTERACTION FATIGUE MODEL
"""
Tracks interaction fatigue — when the user is tired of JARVIS's chatter,
repeated suggestions, or sustained interaction.

Detects:
  - repetitive acknowledgments
  - suggestion saturation
  - prolonged session fatigue
  - acknowledgment density

Adapts:
  - suppresses suggestions proactively
  - reduces speech density
  - drops conversational warmth
  - increases quiet mode tendency

Wire into: SuggestionEngine, CalmEngine, jarvis_brain post-processing.
"""
from __future__ import annotations

import threading
import time
import os
import json
from collections import deque
from dataclasses import dataclass
from typing import Optional

_PATH = "memory/fatigue_model.json"
_WINDOW_S = 600


@dataclass
class InteractionEvent:
    type: str  # "ack", "suggestion", "command", "speech", "dismiss"
    timestamp: float
    fatigue_delta: float


class FatigueModel:
    """
    Tracks interaction fatigue level (0.0 = fresh, 1.0 = saturated).
    Fatigue rises from repeated interactions, falls during quiet periods.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._events: deque[InteractionEvent] = deque(maxlen=500)
        self._fatigue = 0.0
        self._last_interaction = time.time()
        self._session_start = time.time()
        self._dismiss_count = 0
        self._suggestion_count = 0
        self._accepted_suggestions = 0
        self._speech_count = 0
        self._last_decay = time.time()
        self._load()

    def _load(self):
        try:
            if os.path.exists(_PATH):
                with open(_PATH, "r") as f:
                    data = json.load(f)
                    self._dismiss_count = data.get("dismiss_count", 0)
                    self._suggestion_count = data.get("suggestion_count", 0)
                    self._accepted_suggestions = data.get("accepted", 0)
                    print(f"[Fatigue] Loaded dismiss={self._dismiss_count}, "
                          f"suggestions={self._suggestion_count}")
        except Exception as e:
            print(f"[Fatigue] Load error: {e}")

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(_PATH), exist_ok=True)
                with open(_PATH, "w") as f:
                    json.dump({
                        "dismiss_count": self._dismiss_count,
                        "suggestion_count": self._suggestion_count,
                        "accepted": self._accepted_suggestions,
                    }, f, indent=2)
            except Exception as e:
                print(f"[Fatigue] Save error: {e}")

    def _decay(self):
        """Slowly reduce fatigue during quiet periods."""
        now = time.time()
        if now - self._last_decay > 30:
            delta = min(0.05, (now - self._last_decay) / 3600)
            self._fatigue = max(0.0, self._fatigue - delta)
            self._last_decay = now

    def record(self, event_type: str):
        """Record an interaction event and update fatigue."""
        self._decay()
        with self._lock:
            event = InteractionEvent(type=event_type, timestamp=time.time(), fatigue_delta=0.0)

            if event_type == "speech":
                self._speech_count += 1
                self._fatigue = min(1.0, self._fatigue + 0.01)
                event.fatigue_delta = 0.01
            elif event_type == "suggestion":
                self._suggestion_count += 1
                self._fatigue = min(1.0, self._fatigue + 0.02)
                event.fatigue_delta = 0.02
            elif event_type == "dismiss":
                self._dismiss_count += 1
                self._fatigue = min(1.0, self._fatigue + 0.03)
                event.fatigue_delta = 0.03
            elif event_type == "command":
                self._last_interaction = time.time()
                self._fatigue = min(1.0, self._fatigue + 0.005)
                event.fatigue_delta = 0.005
            elif event_type == "accept":
                self._accepted_suggestions += 1
                self._fatigue = max(0.0, self._fatigue - 0.02)

            self._events.append(event)

    @property
    def level(self) -> float:
        """Current fatigue level 0.0–1.0."""
        self._decay()
        with self._lock:
            return min(1.0, self._fatigue)

    @property
    def is_fatigued(self) -> bool:
        return self.level > 0.6

    @property
    def is_very_fatigued(self) -> bool:
        return self.level > 0.8

    def suggestion_suppression_odds(self) -> float:
        """Return 0.0–1.0 likelihood of suppressing a suggestion."""
        if self.level < 0.3:
            return 0.0
        return (self.level - 0.3) * 0.85

    def speech_density_mult(self) -> float:
        """Multiplier for speech rate (1.0 = normal, 0.5 = quiet)."""
        return max(0.3, 1.0 - self.level * 0.7)

    def should_skip_suggestions(self) -> bool:
        return self.level > 0.75

    def should_skip_completion(self) -> bool:
        return self.level > 0.5

    def should_be_quiet(self) -> bool:
        return self.level > 0.7

    def session_duration_min(self) -> float:
        return (time.time() - self._session_start) / 60

    def get_metrics(self) -> dict:
        with self._lock:
            return {
                "fatigue":       round(self._fatigue, 3),
                "dismiss_count": self._dismiss_count,
                "suggestion_count": self._suggestion_count,
                "accepted_suggestions": self._accepted_suggestions,
                "speech_count":  self._speech_count,
                "session_min":  self.session_duration_min(),
                "is_fatigued":  self.is_fatigued,
                "suppression_odds": round(self.suggestion_suppression_odds(), 3),
            }

    def recent_events(self, event_type: str, window_s: float = 300) -> list[InteractionEvent]:
        with self._lock:
            cutoff = time.time() - window_s
            return [e for e in self._events if e.type == event_type and e.timestamp > cutoff]

    def suggestion_rejection_rate(self) -> float:
        total = self._accepted_suggestions + self._dismiss_count
        if total == 0:
            return 0.0
        return self._dismiss_count / total


_instance: Optional[FatigueModel] = None
_lock = threading.Lock()


def get_fatigue_model() -> FatigueModel:
    global _instance
    with _lock:
        if _instance is None:
            _instance = FatigueModel()
        return _instance