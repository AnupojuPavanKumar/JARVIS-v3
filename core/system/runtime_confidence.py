# core/system/runtime_confidence.py — JARVIS RUNTIME CONFIDENCE MODEL
"""
Scores overall runtime health from multiple signals.

Factors (weighted):
  - Subsystem stability    (30%) — failed/degraded ratio
  - Pressure level         (25%) — from HealthPressureGovernor
  - Watchdog incidents     (20%) — hung task frequency
  - Recovery success rate  (15%) — from RecoveryOrchestrator
  - Session uptime         (10%) — long sessions = more confident

Levels:
  CONFIDENT  >= 80  — full capability, all proactive features active
  CAUTIOUS   >= 60  — reduce proactive, prefer deterministic paths
  UNCERTAIN  >= 40  — suppress suggestions, light automation only
  LOW        <  40  — deterministic only, no risky automation
"""
from __future__ import annotations

import threading
import time
from enum import IntEnum, auto
from collections import deque
from typing import Callable, Optional
from dataclasses import dataclass

import logging

log = logging.getLogger("RuntimeConfidence")


class ConfidenceLevel(IntEnum):
    LOW        = 0
    UNCERTAIN  = 1
    CAUTIOUS   = 2
    CONFIDENT  = 3


@dataclass
class ConfidenceSnapshot:
    timestamp:          float
    score:              float        # 0-100
    level:              ConfidenceLevel
    stability_score:    float
    pressure_score:     float
    watchdog_score:     float
    recovery_score:     float
    uptime_score:       float


class RuntimeConfidence:
    """
    Background confidence monitor.
    Poll every 30s. Emit callbacks on level change.
    """

    _instance: Optional[RuntimeConfidence] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._level    = ConfidenceLevel.CONFIDENT
        self._score    = 100.0
        self._history: deque[ConfidenceSnapshot] = deque(maxlen=120)
        self._callbacks: list[Callable[[ConfidenceLevel, float], None]] = []
        self._running  = False
        self._stop_evt = threading.Event()
        self._thread:  Optional[threading.Thread] = None
        self._started_at = time.time()
        self._interval = 30.0

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="RuntimeConfidence"
        )
        self._thread.start()
        log.info("[Confidence] Monitor started.")

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def on_change(self, cb: Callable[[ConfidenceLevel, float], None]):
        """Called when confidence level changes."""
        self._callbacks.append(cb)

    # ── Scoring ──────────────────────────────────────────────────────────────

    def _loop(self):
        while self._running and not self._stop_evt.is_set():
            try:
                snap = self._compute()
                with self._lock:
                    prev = self._level
                    self._score = snap.score
                    self._level = snap.level
                    self._history.append(snap)
                if snap.level != prev:
                    log.info(f"[Confidence] {prev.name} → {snap.level.name} (score={snap.score:.1f})")
                    for cb in self._callbacks:
                        try:
                            cb(snap.level, snap.score)
                        except Exception:
                            pass
            except Exception as e:
                log.debug(f"[Confidence] Compute error: {e}")
            self._stop_evt.wait(timeout=self._interval)

    def _compute(self) -> ConfidenceSnapshot:
        stability  = self._score_stability()
        pressure   = self._score_pressure()
        watchdog   = self._score_watchdog()
        recovery   = self._score_recovery()
        uptime     = self._score_uptime()

        score = (
            stability * 0.30 +
            pressure  * 0.25 +
            watchdog  * 0.20 +
            recovery  * 0.15 +
            uptime    * 0.10
        )

        if score >= 80:  level = ConfidenceLevel.CONFIDENT
        elif score >= 60: level = ConfidenceLevel.CAUTIOUS
        elif score >= 40: level = ConfidenceLevel.UNCERTAIN
        else:             level = ConfidenceLevel.LOW

        return ConfidenceSnapshot(
            timestamp=time.time(), score=round(score, 1), level=level,
            stability_score=stability, pressure_score=pressure,
            watchdog_score=watchdog, recovery_score=recovery, uptime_score=uptime,
        )

    def _score_stability(self) -> float:
        """100 = all ready, 0 = all failed."""
        try:
            from core.system.readiness_state import get_readiness_tracker
            rt = get_readiness_tracker()
            summary = rt.get_summary()
            total = max(1, summary["total"])
            failed   = summary["failed"]
            degraded = summary["degraded"]
            # Failed costs more than degraded
            penalty = (failed * 3 + degraded * 1) / total * 100
            return max(0.0, 100.0 - penalty)
        except Exception:
            return 50.0

    def _score_pressure(self) -> float:
        """100 = NOMINAL, 0 = EMERGENCY."""
        try:
            from core.system.health_pressure_governor import get_health_pressure_governor, PressureLevel
            level = get_health_pressure_governor().level
            return {
                PressureLevel.NOMINAL:   100.0,
                PressureLevel.ELEVATED:   80.0,
                PressureLevel.HIGH:       55.0,
                PressureLevel.CRITICAL:   25.0,
                PressureLevel.EMERGENCY:   0.0,
            }.get(level, 50.0)
        except Exception:
            return 50.0

    def _score_watchdog(self) -> float:
        """100 = no incidents, drops per hung event."""
        try:
            from core.system.subsystem_watchdog import get_watchdog
            wd = get_watchdog()
            total_hung = sum(wd._hung_count.values())
            return max(0.0, 100.0 - total_hung * 15)
        except Exception:
            return 75.0

    def _score_recovery(self) -> float:
        """100 = no failures, drops per quarantined/suspended subsystem."""
        try:
            from core.system.recovery_orchestrator import get_recovery_orchestrator
            ro = get_recovery_orchestrator()
            quarantined = len(ro.get_quarantined())
            suspended   = len(ro.get_suspended())
            penalty = quarantined * 20 + suspended * 35
            return max(0.0, 100.0 - penalty)
        except Exception:
            return 75.0

    def _score_uptime(self) -> float:
        """Increases with session age, saturates at 60min."""
        uptime_min = (time.time() - self._started_at) / 60.0
        return min(100.0, uptime_min / 60.0 * 100.0)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def level(self) -> ConfidenceLevel:
        with self._lock:
            return self._level

    @property
    def score(self) -> float:
        with self._lock:
            return self._score

    def is_confident(self) -> bool:
        return self.level == ConfidenceLevel.CONFIDENT

    def should_suppress_proactive(self) -> bool:
        return self.level <= ConfidenceLevel.CAUTIOUS

    def should_suppress_automation(self) -> bool:
        return self.level <= ConfidenceLevel.UNCERTAIN

    def prefer_deterministic(self) -> bool:
        return self.level <= ConfidenceLevel.UNCERTAIN

    def is_low_confidence(self) -> bool:
        return self.level == ConfidenceLevel.LOW

    def get_latest(self) -> Optional[ConfidenceSnapshot]:
        with self._lock:
            return self._history[-1] if self._history else None

    def get_diagnostics(self) -> dict:
        snap = self.get_latest()
        return {
            "level":       self._level.name,
            "score":       self._score,
            "uptime_min":  round((time.time() - self._started_at) / 60, 1),
            "suppress_proactive":    self.should_suppress_proactive(),
            "suppress_automation":   self.should_suppress_automation(),
            "prefer_deterministic":  self.prefer_deterministic(),
            "breakdown": {
                "stability":  snap.stability_score  if snap else None,
                "pressure":   snap.pressure_score   if snap else None,
                "watchdog":   snap.watchdog_score   if snap else None,
                "recovery":   snap.recovery_score   if snap else None,
                "uptime":     snap.uptime_score      if snap else None,
            } if snap else {},
        }


_instance: Optional[RuntimeConfidence] = None
_rc_lock = threading.Lock()


def get_runtime_confidence() -> RuntimeConfidence:
    global _instance
    with _rc_lock:
        if _instance is None:
            _instance = RuntimeConfidence()
        return _instance
