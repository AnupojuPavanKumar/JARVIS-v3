# core/companion/trust_model.py — JARVIS TRUST ADAPTATION MODEL
"""
Earns trust gradually instead of assuming it.

Tracks:
  - accepted suggestions
  - rejected automations
  - dismissed prompts
  - repeated workflows (user-initiated repetition = trust signal)
  - user overrides of assistant actions
  - repeated tool usage

Adapts:
  - automation confidence (don't auto-pilot if user always overrides)
  - proactive behavior (fewer suggestions if often dismissed)
  - restoration suggestions (offer if user accepts them)
  - verbosity level (trustworthy users get terser responses)

Wire into: SuggestionEngine, CalmEngine, jarvis_brain.
"""
from __future__ import annotations

import threading
import time
import os
import json
from collections import deque
from dataclasses import dataclass
from typing import Optional

_PATH = "memory/trust_model.json"
_MAX_EVENTS = 200


@dataclass
class TrustEvent:
    type: str
    value: float
    timestamp: float
    detail: str = ""

    def age(self) -> float:
        return time.time() - self.timestamp


class TrustModel:
    """
    Trust score 0.0–1.0. Starts neutral (0.5), evolves based on behavior patterns.
    Low trust → assistant is cautious and asks for confirmation.
    High trust → assistant acts more confidently and proactively.
    """

    _BASE = 0.5

    def __init__(self):
        self._lock = threading.RLock()
        self._events: deque[TrustEvent] = deque(maxlen=_MAX_EVENTS)
        self._trust = self._BASE
        self._suggestion_accept_count = 0
        self._suggestion_reject_count = 0
        self._automation_override_count = 0
        self._automation_accept_count = 0
        self._workflow_repeat_count = 0
        self._load()

    def _load(self):
        try:
            if os.path.exists(_PATH):
                with open(_PATH, "r") as f:
                    data = json.load(f)
                    self._suggestion_accept_count = data.get("accept_count", 0)
                    self._suggestion_reject_count = data.get("reject_count", 0)
                    self._automation_override_count = data.get("override_count", 0)
                    self._automation_accept_count = data.get("auto_accept_count", 0)
                    self._workflow_repeat_count = data.get("workflow_repeat", 0)
                    self._recompute_trust()
                    print(f"[Trust] Loaded — trust={self._trust:.2f}")
        except Exception as e:
            print(f"[Trust] Load error: {e}")

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(_PATH), exist_ok=True)
                with open(_PATH, "w") as f:
                    json.dump({
                        "accept_count": self._suggestion_accept_count,
                        "reject_count": self._suggestion_reject_count,
                        "override_count": self._automation_override_count,
                        "auto_accept_count": self._automation_accept_count,
                        "workflow_repeat": self._workflow_repeat_count,
                        "trust": self._trust,
                    }, f, indent=2)
            except Exception as e:
                print(f"[Trust] Save error: {e}")

    def _recompute_trust(self):
        total = self._suggestion_accept_count + self._suggestion_reject_count
        if total > 0:
            accept_rate = self._suggestion_accept_count / total
            self._trust = self._BASE + (accept_rate - 0.5) * 0.2

        if self._automation_accept_count > self._automation_override_count:
            self._trust = min(1.0, self._trust + 0.05)

        if self._workflow_repeat_count > 3:
            self._trust = min(1.0, self._trust + 0.05)

        self._trust = max(0.1, min(1.0, self._trust))

    def record_suggestion_accepted(self, suggestion: str = ""):
        with self._lock:
            self._suggestion_accept_count += 1
            self._events.append(TrustEvent(
                type="suggestion_accept", value=0.02,
                timestamp=time.time(), detail=suggestion[:50]
            ))
            self._recompute_trust()

    def record_suggestion_rejected(self, suggestion: str = ""):
        with self._lock:
            self._suggestion_reject_count += 1
            self._events.append(TrustEvent(
                type="suggestion_reject", value=-0.01,
                timestamp=time.time(), detail=suggestion[:50]
            ))
            self._recompute_trust()

    def record_automation_override(self, action: str = ""):
        with self._lock:
            self._automation_override_count += 1
            self._events.append(TrustEvent(
                type="override", value=-0.03,
                timestamp=time.time(), detail=action[:50]
            ))
            self._recompute_trust()

    def record_automation_accepted(self, action: str = ""):
        with self._lock:
            self._automation_accept_count += 1
            self._events.append(TrustEvent(
                type="auto_accept", value=0.03,
                timestamp=time.time(), detail=action[:50]
            ))
            self._recompute_trust()

    def record_workflow_repeated(self, workflow: str = ""):
        with self._lock:
            self._workflow_repeat_count += 1
            self._events.append(TrustEvent(
                type="workflow_repeat", value=0.01,
                timestamp=time.time(), detail=workflow[:50]
            ))
            self._recompute_trust()

    @property
    def trust(self) -> float:
        with self._lock:
            return self._trust

    @property
    def is_trusted(self) -> bool:
        return self.trust > 0.55

    @property
    def is_cautious(self) -> bool:
        return self.trust < 0.45

    def should_auto_act(self) -> bool:
        """High-trust → act without asking. Low-trust → confirm first."""
        with self._lock:
            return self._trust > 0.7

    def should_suggest_proactively(self) -> bool:
        """Don't suggest if user keeps rejecting."""
        with self._lock:
            if self._suggestion_reject_count > 10:
                rate = self._suggestion_reject_count / max(1,
                    self._suggestion_reject_count + self._suggestion_accept_count)
                if rate > 0.6:
                    return False
            return True

    def suggestion_confidence_threshold(self) -> float:
        """Suggest only if confidence exceeds this."""
        return max(0.7, 0.95 - self._trust * 0.3)

    def automation_delay_s(self) -> float:
        """Delay before auto-acting (higher trust = shorter delay)."""
        return max(0, 3.0 - self._trust * 2.5)

    def restoration_confidence(self) -> float:
        """How confident to offer session restoration."""
        return 0.6 + self._trust * 0.2

    def get_summary(self) -> dict:
        with self._lock:
            return {
                "trust": round(self._trust, 3),
                "suggestion_accept_rate": (
                    self._suggestion_accept_count / max(1,
                        self._suggestion_accept_count + self._suggestion_reject_count)
                ),
                "automation_override_rate": (
                    self._automation_override_count / max(1,
                        self._automation_override_count + self._automation_accept_count)
                ),
                "workflow_repeats": self._workflow_repeat_count,
                "is_trusted": self.is_trusted,
                "is_cautious": self.is_cautious,
            }


_instance: Optional[TrustModel] = None
_lock = threading.Lock()


def get_trust_model() -> TrustModel:
    global _instance
    with _lock:
        if _instance is None:
            _instance = TrustModel()
        return _instance