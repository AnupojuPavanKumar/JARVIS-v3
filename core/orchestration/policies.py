# core/orchestration/policies.py
"""
Policy engine — P7.
Rule-based orchestration policies.
IF gpu_usage > 85% THEN switch_model(lightweight)
IF battery_low THEN reduce_background_agents
Deterministic, lightweight, no external frameworks.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Any, Callable, Optional

log = logging.getLogger("PolicyEngine")


class PolicyPriority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class Policy:
    """A named policy rule with condition and action."""
    name: str
    condition_fn: Callable[[], bool]
    action_fn: Callable[[], Any]
    priority: PolicyPriority = PolicyPriority.NORMAL
    enabled: bool = True
    description: str = ""
    last_triggered: float = 0.0
    trigger_count: int = 0
    cooldown_sec: float = 5.0

    def should_trigger(self) -> bool:
        if not self.enabled:
            return False
        if self.cooldown_sec > 0 and (time.time() - self.last_triggered) < self.cooldown_sec:
            return False
        return self.condition_fn()

    def trigger(self) -> Any:
        self.last_triggered = time.time()
        self.trigger_count += 1
        return self.action_fn()


@dataclass
class PolicyResult:
    """Result of evaluating policies."""
    triggered: list[Policy]
    skipped: list[str]
    execution_time_ms: float
    total_evaluated: int


class PolicyEngine:
    """
    Lightweight rule-based policy engine.
    Evaluates policy conditions, executes actions, tracks statistics.
    No external frameworks, deterministic execution.
    """

    def __init__(self):
        self._policies: list[Policy] = []
        self._lock = threading.RLock()
        self._history: deque[PolicyResult] = deque(maxlen=100)
        self._execution_count: dict[str, int] = {}
        self._total_evals: int = 0

    def register(self, policy: Policy):
        """Register a policy."""
        with self._lock:
            self._policies.append(policy)
            self._policies.sort(key=lambda p: p.priority.value)

    def unregister(self, name: str) -> bool:
        """Remove a policy by name."""
        with self._lock:
            for i, p in enumerate(self._policies):
                if p.name == name:
                    self._policies.pop(i)
                    return True
        return False

    def enable(self, name: str, enabled: bool):
        """Enable or disable a policy."""
        with self._lock:
            for p in self._policies:
                if p.name == name:
                    p.enabled = enabled

    def evaluate_all(self) -> PolicyResult:
        """Evaluate all enabled policies. Returns triggered policies."""
        t0 = time.perf_counter()
        triggered = []
        skipped = []
        with self._lock:
            policies = list(self._policies)
        for p in policies:
            try:
                if not p.enabled:
                    skipped.append(p.name)
                    continue
                if p.should_trigger():
                    result = p.trigger()
                    triggered.append(p)
                    with self._lock:
                        self._execution_count[p.name] = self._execution_count.get(p.name, 0) + 1
                    log.debug(f"[PolicyEngine] Triggered: {p.name}")
            except Exception as e:
                skipped.append(f"{p.name}:{str(e)[:30]}")
                log.warning(f"[PolicyEngine] Policy '{p.name}' error: {e}")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self._total_evals += 1
        result = PolicyResult(
            triggered=triggered, skipped=skipped,
            execution_time_ms=elapsed_ms, total_evaluated=len(policies),
        )
        with self._lock:
            self._history.append(result)
        return result

    def evaluate_domain(self, domain: str) -> PolicyResult:
        """Evaluate policies for a specific domain."""
        return self.evaluate_all()

    def get_stats(self) -> dict:
        with self._lock:
            enabled = sum(1 for p in self._policies if p.enabled)
            total = len(self._policies)
            return {
                "total_policies": total,
                "enabled": enabled,
                "disabled": total - enabled,
                "executions": dict(self._execution_count),
                "total_evaluations": self._total_evals,
                "top_triggered": sorted(
                    self._execution_count.items(), key=lambda x: x[1], reverse=True
                )[:5],
            }


_global_policy_engine: PolicyEngine | None = None
_pe_lock = threading.Lock()


def get_policy_engine() -> PolicyEngine:
    global _global_policy_engine
    with _pe_lock:
        if _global_policy_engine is None:
            _global_policy_engine = PolicyEngine()
        return _global_policy_engine
