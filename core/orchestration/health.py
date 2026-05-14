# core/orchestration/health.py
"""
Health monitoring system — P15.
Overall health score, subsystem health scores, degradation warnings,
predictive instability alerts. Tracks queue health, event bus health,
executor failures, latency drift, resource pressure, rollback frequency.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

log = logging.getLogger("HealthMonitor")


class HealthLevel(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    CRITICAL = auto()
    UNKNOWN = auto()


@dataclass
class SubsystemHealth:
    """Health status for a single subsystem."""
    name: str
    level: HealthLevel
    score: float
    message: str
    last_check: float
    metrics: dict = field(default_factory=dict)


@dataclass
class SystemHealthReport:
    """Full system health report."""
    timestamp: float
    overall_score: float
    overall_level: HealthLevel
    subsystems: dict[str, SubsystemHealth]
    active_alerts: list[str]
    degradation_warnings: list[str]


class HealthMonitor:
    """
    Operational health monitoring.
    Aggregates subsystem health, computes overall score,
    generates alerts and degradation warnings.
    """

    def __init__(self):
        self._subsystems: dict[str, SubsystemHealth] = {}
        self._lock = threading.RLock()
        self._history: deque[SystemHealthReport] = deque(maxlen=200)
        self._alerts: deque[str] = deque(maxlen=50)
        self._health_thresholds = {
            HealthLevel.HEALTHY: 0.8,
            HealthLevel.DEGRADED: 0.5,
            HealthLevel.CRITICAL: 0.2,
        }
        self._subsystem_weights: dict[str, float] = {
            "queue": 0.15, "event_bus": 0.10, "executor": 0.20,
            "resource": 0.15, "memory": 0.10, "provider": 0.15,
            "fsm": 0.05, "safety": 0.10,
        }

    def update_subsystem(self, name: str, level: HealthLevel, score: float, message: str, metrics: dict | None = None):
        """Update health status for a subsystem."""
        with self._lock:
            self._subsystems[name] = SubsystemHealth(
                name=name, level=level, score=score,
                message=message, last_check=time.time(),
                metrics=metrics or {},
            )
        if level in (HealthLevel.DEGRADED, HealthLevel.CRITICAL):
            with self._lock:
                self._alerts.append(f"[{level.name}] {name}: {message}")

    def compute_subsystem_health(self, name: str) -> SubsystemHealth | None:
        """Compute or refresh health for a subsystem based on real metrics."""
        with self._lock:
            sub = self._subsystems.get(name)
        if not sub:
            return None
        score = sub.score
        level = self._score_to_level(score)
        with self._lock:
            self._subsystems[name] = SubsystemHealth(
                name=name, level=level, score=score,
                message=sub.message, last_check=time.time(),
                metrics=sub.metrics,
            )
        return self._subsystems[name]

    def _score_to_level(self, score: float) -> HealthLevel:
        if score >= self._health_thresholds[HealthLevel.HEALTHY]:
            return HealthLevel.HEALTHY
        elif score >= self._health_thresholds[HealthLevel.DEGRADED]:
            return HealthLevel.DEGRADED
        elif score >= self._health_thresholds[HealthLevel.CRITICAL]:
            return HealthLevel.CRITICAL
        return HealthLevel.UNKNOWN

    def compute_overall_score(self) -> tuple[float, HealthLevel]:
        """Compute weighted overall health score."""
        with self._lock:
            subsystems = dict(self._subsystems)
        if not subsystems:
            return 0.0, HealthLevel.UNKNOWN
        total_weight = 0.0
        weighted_score = 0.0
        for name, weight in self._subsystem_weights.items():
            sub = subsystems.get(name)
            if sub:
                weighted_score += sub.score * weight
                total_weight += weight
        if total_weight == 0:
            return 0.0, HealthLevel.UNKNOWN
        normalized = weighted_score / sum(self._subsystem_weights.values())
        return round(normalized, 3), self._score_to_level(normalized)

    def refresh_all(self):
        """Refresh health for all known subsystems."""
        from core.executor.execution_queue import get_execution_queue
        from core.events.bus import get_event_bus
        from core.resource.monitor import get_resource_monitor
        from core.executor.rollback import get_transaction_executor
        from core.state.fsm import get_state_machine

        try:
            q = get_execution_queue()
            qs = q.stats
            total = qs.get("total", 1)
            failed_ratio = qs.get("total", 0) > 0 and (qs.get("total", 0) - qs.get("success_rate", 1) * total) / total
            q_score = max(0, min(1, qs.get("success_rate", 1.0) - failed_ratio * 0.3))
            q_level = self._score_to_level(q_score)
            self.update_subsystem("queue", q_level, q_score,
                f"depth={qs.get('queue_depth', 0)}, active={qs.get('active_count', 0)}, violations={qs.get('fairness_violations', 0)}",
                qs)
        except Exception as e:
            log.debug(f"Queue health check failed: {e}")

        try:
            bus = get_event_bus()
            bs = bus.stats()
            subscriber_ratio = min(bs.get("subscribers", 1), 100) / 100
            queue_ratio = min(bs.get("queue_depth", 0), 100) / 100
            bus_score = max(0, min(1, subscriber_ratio * 0.5 + (1 - queue_ratio) * 0.5))
            bus_level = self._score_to_level(bus_score)
            self.update_subsystem("event_bus", bus_level, bus_score,
                f"subs={bs.get('subscribers', 0)}, queue={bs.get('queue_depth', 0)}, running={bs.get('running', False)}", bs)
        except Exception as e:
            log.debug(f"Event bus health check failed: {e}")

        try:
            mon = get_resource_monitor()
            snap = mon.current_snapshot()
            if snap:
                import core.resource.monitor as rm
                profile = snap.profile if snap else rm.ResourceProfile.IDLE
                if profile == rm.ResourceProfile.CRITICAL:
                    res_score = 0.1
                elif profile == rm.ResourceProfile.HEAVY:
                    res_score = 0.3
                elif profile == rm.ResourceProfile.MODERATE:
                    res_score = 0.6
                elif profile == rm.ResourceProfile.LIGHT:
                    res_score = 0.8
                else:
                    res_score = 0.95
                res_level = self._score_to_level(res_score)
                self.update_subsystem("resource", res_level, res_score,
                    f"profile={profile.name}, vram_free={snap.vram_free_mb:.0f}MB", snap.__dict__)
        except Exception as e:
            log.debug(f"Resource health check failed: {e}")

        try:
            tx = get_transaction_executor()
            ts = tx.stats()
            total = ts.get("total", 1)
            rb_rate = ts.get("rolled_back", 0) / total if total > 0 else 0
            tx_score = max(0, min(1, 1.0 - rb_rate * 2))
            tx_level = self._score_to_level(tx_score)
            self.update_subsystem("executor", tx_level, tx_score,
                f"total={ts.get('total', 0)}, completed={ts.get('completed', 0)}, rolled_back={ts.get('rolled_back', 0)}", ts)
        except Exception as e:
            log.debug(f"Executor health check failed: {e}")

        try:
            from core.executor.execution_safety import get_safety_validator
            safety = get_safety_validator()
            audit = safety.get_audit_log(20)
            blocked_count = sum(1 for e in audit if e.get("result") == "blocked")
            audit_score = max(0, min(1, 1.0 - blocked_count * 0.05))
            saf_level = self._score_to_level(audit_score)
            self.update_subsystem("safety", saf_level, audit_score,
                f"audit_entries={len(audit)}, blocked={blocked_count}", {"audit_size": len(audit)})
        except Exception as e:
            log.debug(f"Safety health check failed: {e}")

    def generate_report(self) -> SystemHealthReport:
        """Generate a full system health report."""
        self.refresh_all()
        overall_score, overall_level = self.compute_overall_score()
        with self._lock:
            subsystems = dict(self._subsystems)
            alerts = list(self._alerts)
        warnings = [
            f"{name}: {sub.message}"
            for name, sub in subsystems.items()
            if sub.level in (HealthLevel.DEGRADED, HealthLevel.CRITICAL)
        ]
        report = SystemHealthReport(
            timestamp=time.time(),
            overall_score=overall_score,
            overall_level=overall_level,
            subsystems=subsystems,
            active_alerts=list(alerts[-10:]),
            degradation_warnings=warnings,
        )
        with self._lock:
            self._history.append(report)
        return report

    def predict_instability(self) -> list[str]:
        """Predict potential instability based on trends."""
        predictions = []
        with self._lock:
            recent = list(self._history)[-10:]
        if len(recent) < 3:
            return predictions
        scores = [r.overall_score for r in recent]
        if len(scores) >= 3 and scores[-1] < scores[-2] < scores[-3]:
            predictions.append("Sustained health score decline detected")
        with self._lock:
            q_health = self._subsystems.get("queue")
        if q_health and q_health.metrics.get("queue_depth", 0) > 80:
            predictions.append("Queue depth approaching limit")
        with self._lock:
            res_health = self._subsystems.get("resource")
        if res_health and res_health.metrics.get("profile") == "HEAVY":
            predictions.append("Resource profile at HEAVY level")
        return predictions

    def get_report(self) -> SystemHealthReport:
        with self._lock:
            if self._history:
                return self._history[-1]
        return self.generate_report()


_global_health_monitor: HealthMonitor | None = None
_hm_lock = threading.Lock()


def get_health_monitor() -> HealthMonitor:
    global _global_health_monitor
    with _hm_lock:
        if _global_health_monitor is None:
            _global_health_monitor = HealthMonitor()
        return _global_health_monitor
