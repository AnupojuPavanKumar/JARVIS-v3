# core/system/meta_stability_guard.py — JARVIS META-STABILITY PROTECTION
"""
Detects and breaks recursive adaptive feedback loops between:
  Governor ↔ Confidence ↔ Recovery ↔ Watchdog ↔ Mitigation

Patterns monitored:
  1. Oscillation    — same system changes state > N times in window
  2. Feedback loop  — two systems correlate in opposing directions repeatedly
  3. Churn          — overall state-change rate exceeds safety threshold

Response:
  - Freeze mitigations for stabilization period
  - Reduce probe/recovery frequency
  - Emit diagnostic narratives
  - Notify registered callbacks
"""
from __future__ import annotations

import threading
import time
from collections import deque, defaultdict
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("MetaStabilityGuard")

_WINDOW_SEC           = 60.0
_OSCILLATION_THRESH   = 4
_CHURN_THRESH         = 12
_FEEDBACK_THRESH      = 3
_POLL_INTERVAL        = 15.0

# Graded dampening durations (seconds) — escalate with each trigger
_DAMPEN_DURATIONS = [30.0, 60.0, 120.0, 240.0]  # LIGHT, MODERATE, HEAVY, FROZEN


class DampeningLevel:
    NONE     = 0
    LIGHT    = 1
    MODERATE = 2
    HEAVY    = 3
    FROZEN   = 4

    # Rate multipliers applied to governor mitigation rate limit
    _MULTIPLIERS = {0: 1.0, 1: 1.5, 2: 2.5, 3: 4.0, 4: float('inf')}


class StabilityEvent(Enum):
    OSCILLATION   = auto()
    FEEDBACK_LOOP = auto()
    CHURN         = auto()
    STABILIZED    = auto()    # returned to calm after freeze


@dataclass
class ChangeEvent:
    timestamp: float
    source:    str
    event:     str
    direction: int   # +1 escalating, -1 de-escalating, 0 neutral


class MetaStabilityGuard:
    """
    Central observer for cross-system feedback loops.
    All adaptive subsystems should record_event() on state changes.
    """

    _instance: Optional[MetaStabilityGuard] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._events: deque[ChangeEvent] = deque(maxlen=500)
        self._stabilizing_until: float = 0.0
        self._dampening_level: int = DampeningLevel.NONE
        self._stability_events: list[tuple[float, StabilityEvent, str]] = []
        self._callbacks: list[Callable[[StabilityEvent, str], None]] = []
        self._running   = False
        self._stop_evt  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._freeze_count = 0
        self._last_trigger_at: float = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def record_event(self, source: str, event: str, direction: int = 0):
        """
        Record a state change from any adaptive subsystem.
        source:    e.g. "governor", "recovery", "confidence", "watchdog"
        event:     e.g. "ELEVATED", "QUARANTINED", "CAUTIOUS"
        direction: +1 = worsening/escalating, -1 = improving/recovering, 0 = neutral
        """
        with self._lock:
            self._events.append(ChangeEvent(
                timestamp=time.time(), source=source,
                event=event, direction=direction,
            ))

    def is_stabilizing(self) -> bool:
        return time.time() < self._stabilizing_until

    def stabilization_remaining_sec(self) -> float:
        return max(0.0, self._stabilizing_until - time.time())

    def get_dampening_level(self) -> int:
        """Current dampening level (0=NONE .. 4=FROZEN)."""
        if not self.is_stabilizing():
            return DampeningLevel.NONE
        return self._dampening_level

    def get_dampening_multiplier(self) -> float:
        """Rate limit multiplier for governor — higher = fewer mitigations allowed."""
        return DampeningLevel._MULTIPLIERS.get(self.get_dampening_level(), 1.0)

    def on_stability_event(self, cb: Callable[[StabilityEvent, str], None]):
        self._callbacks.append(cb)

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="MetaStabilityGuard"
        )
        self._thread.start()
        log.info("[MetaStability] Guard started.")

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    # ── Detection ─────────────────────────────────────────────────────────────

    def _loop(self):
        while self._running and not self._stop_evt.is_set():
            try:
                self._check_all()
            except Exception as e:
                log.debug(f"[MetaStability] Check error: {e}")
            self._stop_evt.wait(timeout=_POLL_INTERVAL)

    def _window_events(self) -> list[ChangeEvent]:
        cutoff = time.time() - _WINDOW_SEC
        with self._lock:
            return [e for e in self._events if e.timestamp >= cutoff]

    def _check_all(self):
        if self.is_stabilizing():
            return   # already frozen — don't re-trigger

        events = self._window_events()
        if not events:
            return

        reason = self._detect_oscillation(events)
        if not reason:
            reason = self._detect_feedback_loop(events)
        if not reason:
            reason = self._detect_churn(events)

        if reason:
            self._trigger_stabilization(reason)

    def _detect_oscillation(self, events: list[ChangeEvent]) -> Optional[str]:
        counts: dict[str, int] = defaultdict(int)
        for e in events:
            counts[e.source] += 1
        for source, count in counts.items():
            if count >= _OSCILLATION_THRESH:
                return (f"Oscillation in '{source}': "
                        f"{count} state changes in {_WINDOW_SEC:.0f}s")
        return None

    def _detect_feedback_loop(self, events: list[ChangeEvent]) -> Optional[str]:
        """
        Detect correlated opposing-direction pairs.
        e.g. governor escalates → recovery attempts → governor escalates again
        """
        # Build direction sequences per source
        by_source: dict[str, list[int]] = defaultdict(list)
        for e in events:
            if e.direction != 0:
                by_source[e.source].append(e.direction)

        # Look for alternating +1/-1 patterns (feedback ping-pong)
        for source, directions in by_source.items():
            if len(directions) < _FEEDBACK_THRESH * 2:
                continue
            alternations = sum(
                1 for i in range(1, len(directions))
                if directions[i] != directions[i - 1]
            )
            if alternations >= _FEEDBACK_THRESH * 2 - 1:
                return (f"Feedback loop in '{source}': "
                        f"{alternations} direction reversals")

        # Cross-system: governor escalating while recovery also escalating
        gov_up = sum(1 for e in events if e.source == "governor" and e.direction > 0)
        rec_up = sum(1 for e in events if e.source == "recovery" and e.direction > 0)
        if gov_up >= _FEEDBACK_THRESH and rec_up >= _FEEDBACK_THRESH:
            return (f"Cross-system feedback: governor escalated {gov_up}x "
                    f"while recovery also escalated {rec_up}x")
        return None

    def _detect_churn(self, events: list[ChangeEvent]) -> Optional[str]:
        if len(events) >= _CHURN_THRESH:
            rate = len(events) / (_WINDOW_SEC / 60)
            return f"Churn: {len(events)} state changes in {_WINDOW_SEC:.0f}s ({rate:.1f}/min)"
        return None

    def _trigger_stabilization(self, reason: str):
        """Graded dampening — level escalates with each trigger."""
        self._freeze_count += 1
        self._last_trigger_at = time.time()

        # Escalate dampening level up to FROZEN
        level = min(self._freeze_count, DampeningLevel.FROZEN)
        self._dampening_level = level

        # Duration scales with level
        idx      = min(level - 1, len(_DAMPEN_DURATIONS) - 1)
        duration = _DAMPEN_DURATIONS[idx]
        self._stabilizing_until = time.time() + duration

        level_name = ["NONE","LIGHT","MODERATE","HEAVY","FROZEN"][level]
        log.warning(f"[MetaStability] DAMPEN:{level_name} for {duration:.0f}s — {reason}")

        # Log explainability
        try:
            from core.system.runtime_explainability import get_runtime_explainability
            get_runtime_explainability().stabilization(level_name, reason, duration)
        except Exception:
            pass

        ev_type = StabilityEvent.OSCILLATION
        self._stability_events.append((time.time(), ev_type, reason))
        for cb in self._callbacks:
            try:
                cb(ev_type, reason)
            except Exception:
                pass

        # Clear events to prevent immediate re-trigger
        with self._lock:
            self._events.clear()

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict:
        events = self._window_events()
        by_source: dict[str, int] = defaultdict(int)
        for e in events:
            by_source[e.source] += 1
        level = self.get_dampening_level()
        level_name = ["NONE","LIGHT","MODERATE","HEAVY","FROZEN"][level]
        return {
            "is_stabilizing":          self.is_stabilizing(),
            "dampening_level":         level_name,
            "dampening_multiplier":    self.get_dampening_multiplier(),
            "stabilization_remaining": round(self.stabilization_remaining_sec(), 1),
            "freeze_count":            self._freeze_count,
            "events_in_window":        len(events),
            "events_by_source":        dict(by_source),
            "recent_stability_events": [
                {"ts": round(ts, 1), "type": ev.name, "reason": r}
                for ts, ev, r in self._stability_events[-5:]
            ],
        }


_instance: Optional[MetaStabilityGuard] = None
_guard_lock = threading.Lock()


def get_meta_stability_guard() -> MetaStabilityGuard:
    global _instance
    with _guard_lock:
        if _instance is None:
            _instance = MetaStabilityGuard()
        return _instance
