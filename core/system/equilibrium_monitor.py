# core/system/equilibrium_monitor.py — JARVIS PREDICTIVE EQUILIBRIUM MONITOR
"""
Detects trajectories toward instability BEFORE oscillation occurs.

Tracks:
  - Mitigation churn rate (changes/min)
  - Recovery frequency acceleration
  - Confidence collapse gradient
  - Pressure slope

Emits warnings on deteriorating trajectory and triggers preemptive dampening.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("EquilibriumMonitor")

_POLL_SEC    = 20.0
_WINDOW_SEC  = 120.0   # 2-minute trend window
_SLOPE_WARN  = 0.15    # confidence drop per minute → warn
_SLOPE_CRIT  = 0.30    # confidence drop per minute → critical
_CHURN_WARN  = 4       # mitigation changes per minute → warn
_RECOV_ACCEL = 3       # recovery requests per 2-min window → acceleration warning


class Trajectory(Enum):
    IMPROVING     = auto()
    STABLE        = auto()
    DETERIORATING = auto()
    CRITICAL      = auto()


@dataclass
class EquilibriumSnapshot:
    timestamp:         float
    trajectory:        Trajectory
    confidence_slope:  float    # per minute, negative = dropping
    pressure_slope:    float    # per check, positive = rising
    churn_rate:        float    # mitigation changes/min
    recovery_rate:     float    # recovery requests/min
    warnings:          list[str]


class EquilibriumMonitor:

    _instance: Optional[EquilibriumMonitor] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._confidence_history: deque[tuple[float, float]] = deque(maxlen=60)  # (ts, score)
        self._pressure_history:   deque[tuple[float, int]]   = deque(maxlen=60)  # (ts, level_int)
        self._mitigation_times:   deque[float]               = deque(maxlen=100)
        self._recovery_times:     deque[float]               = deque(maxlen=100)
        self._snapshots:          deque[EquilibriumSnapshot]  = deque(maxlen=60)
        self._callbacks: list[Callable[[Trajectory, EquilibriumSnapshot], None]] = []
        self._running   = False
        self._stop_evt  = threading.Event()
        self._thread:   Optional[threading.Thread] = None
        self._last_trajectory = Trajectory.STABLE

    # ── Public API ────────────────────────────────────────────────────────────

    def record_mitigation(self):
        self._mitigation_times.append(time.time())

    def record_recovery_request(self):
        self._recovery_times.append(time.time())

    def record_confidence(self, score: float):
        self._confidence_history.append((time.time(), score))

    def record_pressure(self, level_int: int):
        self._pressure_history.append((time.time(), level_int))

    def on_trajectory_change(self, cb: Callable[[Trajectory, EquilibriumSnapshot], None]):
        self._callbacks.append(cb)

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="EquilibriumMonitor"
        )
        self._thread.start()
        log.info("[EquilibriumMonitor] Started.")

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    # ── Computation ──────────────────────────────────────────────────────────

    def _loop(self):
        while self._running and not self._stop_evt.is_set():
            try:
                snap = self._compute()
                with self._lock:
                    self._snapshots.append(snap)
                if snap.trajectory != self._last_trajectory:
                    log.info(f"[Equilibrium] Trajectory: {self._last_trajectory.name} "
                             f"→ {snap.trajectory.name}")
                    for cb in self._callbacks:
                        try:
                            cb(snap.trajectory, snap)
                        except Exception:
                            pass
                    self._last_trajectory = snap.trajectory
                if snap.warnings:
                    for w in snap.warnings:
                        log.warning(f"[Equilibrium] {w}")
            except Exception as e:
                log.debug(f"[EquilibriumMonitor] Error: {e}")
            self._stop_evt.wait(timeout=_POLL_SEC)

    def _window(self, buf: deque) -> list:
        cutoff = time.time() - _WINDOW_SEC
        return [(ts, v) for ts, v in buf if ts >= cutoff]

    def _compute(self) -> EquilibriumSnapshot:
        warnings = []
        now = time.time()

        # Confidence slope (change per minute)
        conf_window = self._window(self._confidence_history)
        conf_slope  = self._linear_slope(conf_window)  # negative = dropping

        # Pressure slope
        press_window = self._window(self._pressure_history)
        press_slope  = self._linear_slope(press_window)

        # Churn rate (mitigations per minute)
        mit_window   = [t for t in self._mitigation_times if t >= now - _WINDOW_SEC]
        churn_rate   = len(mit_window) / (_WINDOW_SEC / 60.0)

        # Recovery acceleration
        rec_window   = [t for t in self._recovery_times if t >= now - _WINDOW_SEC]
        recovery_rate= len(rec_window) / (_WINDOW_SEC / 60.0)

        # Assess warnings
        if conf_slope < -_SLOPE_CRIT:
            warnings.append(f"Confidence collapsing at {conf_slope:.2f}/min — preemptive action needed")
        elif conf_slope < -_SLOPE_WARN:
            warnings.append(f"Confidence declining at {conf_slope:.2f}/min")

        if churn_rate >= _CHURN_WARN:
            warnings.append(f"Mitigation churn at {churn_rate:.1f}/min — oscillation risk")

        if len(rec_window) >= _RECOV_ACCEL:
            warnings.append(f"Recovery acceleration: {len(rec_window)} requests in {_WINDOW_SEC:.0f}s")

        # Determine trajectory
        if conf_slope < -_SLOPE_CRIT or (churn_rate >= _CHURN_WARN and press_slope > 0.5):
            trajectory = Trajectory.CRITICAL
        elif conf_slope < -_SLOPE_WARN or churn_rate >= _CHURN_WARN * 0.6:
            trajectory = Trajectory.DETERIORATING
        elif conf_slope > _SLOPE_WARN * 0.5 and press_slope < 0:
            trajectory = Trajectory.IMPROVING
        else:
            trajectory = Trajectory.STABLE

        # If trajectory is critical → trigger preemptive dampening
        if trajectory == Trajectory.CRITICAL:
            try:
                from core.system.meta_stability_guard import get_meta_stability_guard, StabilityEvent
                guard = get_meta_stability_guard()
                guard.record_event("equilibrium_monitor", "PREEMPTIVE_DAMPEN", direction=+1)
            except Exception:
                pass

        return EquilibriumSnapshot(
            timestamp=now,
            trajectory=trajectory,
            confidence_slope=round(conf_slope, 3),
            pressure_slope=round(press_slope, 3),
            churn_rate=round(churn_rate, 2),
            recovery_rate=round(recovery_rate, 2),
            warnings=warnings,
        )

    @staticmethod
    def _linear_slope(points: list[tuple[float, float]]) -> float:
        """Simple linear regression slope over (timestamp, value) pairs."""
        if len(points) < 2:
            return 0.0
        n   = len(points)
        t0  = points[0][0]
        xs  = [(p[0] - t0) / 60.0 for p in points]  # minutes
        ys  = [p[1] for p in points]
        mx  = sum(xs) / n
        my  = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = sum((x - mx) ** 2 for x in xs)
        return num / den if den else 0.0

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def get_latest(self) -> Optional[EquilibriumSnapshot]:
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def get_diagnostics(self) -> dict:
        snap = self.get_latest()
        return {
            "trajectory":       snap.trajectory.name     if snap else "UNKNOWN",
            "confidence_slope": snap.confidence_slope     if snap else 0,
            "pressure_slope":   snap.pressure_slope       if snap else 0,
            "churn_rate":       snap.churn_rate           if snap else 0,
            "recovery_rate":    snap.recovery_rate        if snap else 0,
            "warnings":         snap.warnings             if snap else [],
        }


_instance: Optional[EquilibriumMonitor] = None
_em_lock = threading.Lock()


def get_equilibrium_monitor() -> EquilibriumMonitor:
    global _instance
    with _em_lock:
        if _instance is None:
            _instance = EquilibriumMonitor()
        return _instance
