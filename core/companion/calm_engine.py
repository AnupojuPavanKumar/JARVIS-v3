# core/companion/calm_engine.py — JARVIS CALMNESS ENGINE
"""
Controls JARVIS's behavioral energy — how often it speaks, how it paces
responses, and when it stays silent.

The goal: JARVIS should feel calm, composed, and low-stress.
Not: overeager, overhelpful, over-chatty.

Calmness levers:
  - suggestion suppression: skip suggestions in certain states
  - verbosity ceiling: never exceed current mode's verbosity even if model returns more
  - acknowledgment reduction: sometimes just do, don't say
  - pacing delay: subtle delay before responses (50-200ms) to feel deliberate
  - tone override: never use excited/panicked language
  - silence preference: when in doubt, stay quiet
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto


class CalmLevel(Enum):
    FULL     = auto()   # all systems, full energy, normal speed
    NORMAL   = auto()   # balanced
    QUIET    = auto()   # minimal speech, skip confirmations
    SILENT   = auto()   # TTS off except critical alerts
    EMERGENCY = auto()  # critical alerts only


@dataclass
class CalmConfig:
    level: CalmLevel
    suppress_suggestions: bool
    max_sentences: int        # cap response length
    pacing_delay_ms: int       # artificial delay before speaking (0-200ms)
    ack_threshold: float      # confidence below which we skip TTS
    skip_completions: bool    # don't say "done" after actions
    interrupt_cost_mult: float  # multiply interruption cost


_CALM_CONFIGS: dict[CalmLevel, CalmConfig] = {
    CalmLevel.FULL:       CalmConfig(
        level=CalmLevel.FULL, suppress_suggestions=False,
        max_sentences=10, pacing_delay_ms=0, ack_threshold=0.3,
        skip_completions=False, interrupt_cost_mult=1.0,
    ),
    CalmLevel.NORMAL:    CalmConfig(
        level=CalmLevel.NORMAL, suppress_suggestions=False,
        max_sentences=4, pacing_delay_ms=50, ack_threshold=0.4,
        skip_completions=False, interrupt_cost_mult=1.0,
    ),
    CalmLevel.QUIET:    CalmConfig(
        level=CalmLevel.QUIET, suppress_suggestions=True,
        max_sentences=2, pacing_delay_ms=100, ack_threshold=0.5,
        skip_completions=True, interrupt_cost_mult=1.5,
    ),
    CalmLevel.SILENT:    CalmConfig(
        level=CalmLevel.SILENT, suppress_suggestions=True,
        max_sentences=0, pacing_delay_ms=200, ack_threshold=0.8,
        skip_completions=True, interrupt_cost_mult=2.0,
    ),
    CalmLevel.EMERGENCY: CalmConfig(
        level=CalmLevel.EMERGENCY, suppress_suggestions=False,
        max_sentences=3, pacing_delay_ms=0, ack_threshold=0.0,
        skip_completions=False, interrupt_cost_mult=0.0,
    ),
}


class CalmEngine:
    """
    Manages JARVIS's behavioral energy level.
    Adapts to context: when user is focused → quiet; when idle → normal.
    """

    def __init__(self):
        self._lock       = threading.RLock()
        self._level      = CalmLevel.NORMAL
        self._override   : CalmLevel | None = None  # manual override
        self._auto_mode  = True
        self._override_until: float = 0.0

    def set_level(self, level: CalmLevel):
        """Manually override calmness level."""
        with self._lock:
            self._override = level
            self._auto_mode = False

    def auto_level(self):
        """Return to context-driven calmness."""
        with self._lock:
            self._override = None
            self._auto_mode = True

    def set_temporary(self, level: CalmLevel, duration_s: float):
        """Temporarily boost calmness for N seconds (e.g., focus session)."""
        with self._lock:
            self._override = level
            self._override_until = time.time() + duration_s

    @property
    def level(self) -> CalmLevel:
        with self._lock:
            if self._override is not None:
                # Check if temporary override expired
                if self._override_until > 0 and time.time() > self._override_until:
                    self._override = None
                    self._auto_mode = True
                elif self._override is not None:
                    return self._override
            return self._level

    @property
    def config(self) -> CalmConfig:
        return _CALM_CONFIGS[self.level]

    def adapt_to_context(self, attention_level: str, workflow: str | None):
        """Automatically set calmness based on workspace context."""
        if not self._auto_mode:
            return

        with self._lock:
            if attention_level in ("focused", "absent"):
                self._level = CalmLevel.QUIET
            elif attention_level == "idle":
                self._level = CalmLevel.NORMAL
            elif attention_level in ("active", "relaxed"):
                self._level = CalmLevel.FULL
            elif workflow == "gaming":
                self._level = CalmLevel.SILENT
            else:
                self._level = CalmLevel.NORMAL

    def should_suppress_suggestion(self) -> bool:
        return self.config.suppress_suggestions

    def should_skip_tts(self, confidence: float) -> bool:
        """Skip TTS if confidence below threshold."""
        return confidence < self.config.ack_threshold

    def should_skip_completion(self) -> bool:
        return self.config.skip_completions

    def max_sentences(self, text: str) -> str:
        """Cap response at configured sentence count."""
        sentences = text.split(". ")
        capped = ". ".join(sentences[:self.config.max_sentences])
        if capped and not capped.endswith("."):
            capped += "."
        return capped

    def pacing_delay(self) -> float:
        """Return pacing delay in seconds."""
        return self.config.pacing_delay_ms / 1000.0

    def interruption_cost(self, base: float) -> float:
        """Return adjusted interruption cost."""
        return base * self.config.interrupt_cost_mult

    def get_state(self) -> dict:
        with self._lock:
            return {
                "level":         self.level.name,
                "auto":          self._auto_mode,
                "overridden":     self._override is not None,
                "config": {
                    "suppress_suggestions": self.config.suppress_suggestions,
                    "max_sentences":        self.config.max_sentences,
                    "pacing_delay_ms":      self.config.pacing_delay_ms,
                    "ack_threshold":       self.config.ack_threshold,
                    "skip_completions":     self.config.skip_completions,
                }
            }


_instance: CalmEngine | None = None
_lock = threading.Lock()

def get_calm_engine() -> CalmEngine:
    global _instance
    with _lock:
        if _instance is None:
            _instance = CalmEngine()
        return _instance