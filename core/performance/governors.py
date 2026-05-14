# core/performance/governors.py
"""
Performance governors — latency enforcement, watchdog timers,
execution benchmarking, slow-path detection, profiling instrumentation.
Enforces: routing <50ms, queue insertion <5ms, hot execution <200ms, app launch <300ms.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

log = logging.getLogger("PerformanceGovernor")


class LatencyBudget(Enum):
    ROUTING_MS = 50
    QUEUE_INSERT_MS = 5
    HOT_EXECUTION_MS = 200
    APP_LAUNCH_MS = 300
    EXECUTION_TIMEOUT_MS = 8000
    DECOMPOSITION_MS = 100
    TRIGGER_SCORING_MS = 20
    CACHE_LOOKUP_MS = 5
    DECISION_MS = 50


@dataclass
class BenchmarkResult:
    """Result of a performance benchmark."""
    operation: str
    latency_ms: float
    budget_ms: float
    passed: bool
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


@dataclass
class SlowPathAlert:
    """Alert for a slow execution path."""
    operation: str
    latency_ms: float
    budget_ms: float
    overshoot_percent: float
    timestamp: float = field(default_factory=time.time)
    count: int = 1


class PerformanceGovernor:
    """
    Performance enforcement layer.
    Watchdog timers, latency budgets, benchmarking, slow-path detection.
    Tracks performance across all pipeline operations.
    """

    def __init__(self):
        self._benchmarks: deque[BenchmarkResult] = deque(maxlen=500)
        self._alerts: deque[SlowPathAlert] = deque(maxlen=100)
        self._lock = threading.RLock()
        self._operation_timers: dict[str, float] = {}
        self._slow_counts: dict[str, int] = {}

    def start_operation(self, operation: str):
        """Mark the start of an operation for timing."""
        with self._lock:
            self._operation_timers[operation] = time.perf_counter()

    def end_operation(self, operation: str) -> float:
        """Mark the end of an operation and return latency in ms."""
        with self._lock:
            start = self._operation_timers.pop(operation, None)
        if start is None:
            return 0.0
        latency_ms = (time.perf_counter() - start) * 1000
        return latency_ms

    def benchmark(
        self, operation: str, budget: LatencyBudget, metadata: dict | None = None
    ) -> Callable:
        """Decorator for benchmarking an operation against a budget."""
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            def wrapper(*args, **kwargs) -> Any:
                t0 = time.perf_counter()
                result = func(*args, **kwargs)
                latency_ms = (time.perf_counter() - t0) * 1000
                passed = latency_ms < budget.value
                bench = BenchmarkResult(
                    operation=operation, latency_ms=latency_ms,
                    budget_ms=float(budget.value), passed=passed, metadata=metadata or {},
                )
                with self._lock:
                    self._benchmarks.append(bench)
                if not passed:
                    self._record_slow_path(operation, latency_ms, budget.value)
                return result
            return wrapper
        return decorator

    def check_latency(self, operation: str, latency_ms: float, budget: LatencyBudget) -> bool:
        """Check a measured latency against a budget."""
        passed = latency_ms < budget.value
        bench = BenchmarkResult(
            operation=operation, latency_ms=latency_ms,
            budget_ms=float(budget.value), passed=passed,
        )
        with self._lock:
            self._benchmarks.append(bench)
        if not passed:
            self._record_slow_path(operation, latency_ms, budget.value)
        return passed

    def _record_slow_path(self, operation: str, latency_ms: float, budget_ms: float):
        overshoot = ((latency_ms - budget_ms) / budget_ms) * 100
        with self._lock:
            self._slow_counts[operation] = self._slow_counts.get(operation, 0) + 1
            count = self._slow_counts[operation]
        alert = SlowPathAlert(
            operation=operation, latency_ms=latency_ms, budget_ms=budget_ms, overshoot_percent=round(overshoot, 1), count=count
        )
        with self._lock:
            self._alerts.append(alert)
        log.warning(f"[PerfGovernor] SLOW PATH: {operation} took {latency_ms:.1f}ms (budget: {budget_ms:.1f}ms, +{overshoot:.0f}%)")

    def get_violations(self, limit: int = 20) -> list[SlowPathAlert]:
        with self._lock:
            return list(self._alerts)[-limit:]

    def get_benchmarks(self, operation: str | None = None, limit: int = 100) -> list[BenchmarkResult]:
        with self._lock:
            benchmarks = list(self._benchmarks)
        if operation:
            benchmarks = [b for b in benchmarks if b.operation == operation]
        return benchmarks[-limit:]

    def stats(self) -> dict:
        with self._lock:
            benchmarks = list(self._benchmarks)
            alerts = list(self._alerts)
        if not benchmarks:
            return {"benchmarks": 0, "violations": 0, "avg_latency_ms": 0}
        total = len(benchmarks)
        passed = sum(1 for b in benchmarks if b.passed)
        avg_latency = sum(b.latency_ms for b in benchmarks) / total
        by_op = {}
        for b in benchmarks:
            key = b.operation
            if key not in by_op:
                by_op[key] = {"count": 0, "passed": 0, "avg_ms": 0}
            by_op[key]["count"] += 1
            if b.passed:
                by_op[key]["passed"] += 1
            by_op[key]["avg_ms"] = round(by_op[key]["avg_ms"] * (by_op[key]["count"] - 1) + b.latency_ms / by_op[key]["count"], 2)
        return {
            "total_benchmarks": total,
            "pass_rate": round(passed / total, 3) if total > 0 else 0,
            "violations": len(alerts),
            "avg_latency_ms": round(avg_latency, 2),
            "by_operation": by_op,
            "slow_counts": dict(self._slow_counts),
        }


_global_governor: PerformanceGovernor | None = None
_gov_lock = threading.Lock()


def get_governor() -> PerformanceGovernor:
    global _global_governor
    with _gov_lock:
        if _global_governor is None:
            _global_governor = PerformanceGovernor()
        return _global_governor
