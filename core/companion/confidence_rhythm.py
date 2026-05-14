# core/companion/confidence_rhythm.py — JARVIS CONFIDENCE RHYTHM
"""
Confidence-aware interaction pacing.

LOW CONFIDENCE:
  - softer phrasing ("This looks like...", "I believe...")
  - slower pacing (longer delay)
  - more contextual wording
  - less assertive

HIGH CONFIDENCE:
  - concise direct execution
  - minimal chatter
  - stronger operational flow
  - brief acknowledgments

Wire into: _mid_post_speak, _adapt_verbosity, phrase rotation.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Literal

Confidence = Literal["low", "medium", "high", "very_high"]


_SOFT_PHRASES = [
    "This looks like the right approach.",
    "I believe this is what you needed.",
    "This seems relevant based on context.",
    "Based on recent work, this should help.",
    "I think this is the one you meant.",
]

_DIRECT_PHRASES = [
    "Done.",
    "Handled.",
    "Complete.",
    "Done, sir.",
    "Proceeding.",
]


class ConfidenceRhythm:
    """
    Manages response confidence — how assertive or tentative JARVIS sounds.
    Derived from: command type, previous success rate, context clarity.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._current: Confidence = "medium"
        self._session_success_rate = 1.0
        self._recent_commands = 0
        self._recent_successes = 0
        self._last_confidence_change = time.time()

    def update_success(self, success: bool):
        """Update running success rate for confidence calculation."""
        with self._lock:
            self._recent_commands += 1
            if success:
                self._recent_successes += 1
            self._session_success_rate = (
                self._recent_successes / self._recent_commands
                if self._recent_commands > 0 else 1.0
            )
            self._recompute_confidence()

    def _recompute_confidence(self):
        rate = self._session_success_rate
        if rate >= 0.9 and self._recent_commands >= 3:
            new = "very_high"
        elif rate >= 0.75 and self._recent_commands >= 3:
            new = "high"
        elif rate < 0.5:
            new = "low"
        elif rate < 0.7:
            new = "medium"
        else:
            new = self._current

        if new != self._current:
            self._current = new
            self._last_confidence_change = time.time()

    @property
    def level(self) -> Confidence:
        with self._lock:
            return self._current

    @property
    def mult(self) -> float:
        """Confidence multiplier for sentence count, delay, etc."""
        mapping = {"low": 0.6, "medium": 0.8, "high": 1.0, "very_high": 1.0}
        with self._lock:
            return mapping.get(self._current, 0.8)

    def should_soften_phrase(self) -> bool:
        """Should we use softer uncertainty phrasing?"""
        with self._lock:
            return self._current in ("low", "medium")

    def get_pacing_delay(self) -> float:
        """Extra delay in seconds based on confidence. Lower confidence = slower."""
        with self._lock:
            if self._current == "very_high":
                return 0.0
            elif self._current == "high":
                return 0.02
            elif self._current == "medium":
                return 0.08
            else:
                return 0.15

    def get_max_sentences(self, base: int = 3) -> int:
        """Max sentences based on confidence."""
        with self._lock:
            if self._current in ("low", "medium"):
                return 2
            return base

    def adapt_acknowledgment(self, base_ack: str) -> str:
        """Adapt acknowledgment based on confidence level."""
        with self._lock:
            if self._current == "very_high" or self._current == "high":
                return base_ack
            if self._current == "low":
                if not any(p in base_ack.lower() for p in ["i think", "this looks", "perhaps"]):
                    return random.choice(_SOFT_PHRASES)
            if self._current == "medium":
                if random.random() < 0.3:
                    prefix = "I believe "
                    if not base_ack.lower().startswith("i "):
                        return prefix + base_ack[0].lower() + base_ack[1:]
            return base_ack

    def get_uncertainty_insert(self) -> str:
        """Insert a soft uncertainty signal where natural."""
        with self._lock:
            if self._current == "low":
                return random.choice(_SOFT_PHRASES)
            return ""

    def get_state(self) -> dict:
        with self._lock:
            return {
                "confidence": self._current,
                "mult": self.mult,
                "session_success_rate": round(self._session_success_rate, 3),
                "recent_commands": self._recent_commands,
                "should_soften": self.should_soften_phrase(),
            }


_instance: ConfidenceRhythm | None = None
_lock = threading.Lock()


def get_confidence_rhythm() -> ConfidenceRhythm:
    global _instance
    with _lock:
        if _instance is None:
            _instance = ConfidenceRhythm()
        return _instance