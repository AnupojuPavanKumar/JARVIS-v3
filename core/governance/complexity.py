# core/governance/complexity.py
"""
Complexity governance — P10.
Module count, dependency depth, event coupling, executor coupling,
service graph complexity, startup overhead. Complexity scoring,
architecture warnings, growth trend analysis, overengineering detection.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("ComplexityMonitor")


@dataclass
class ComplexityMetrics:
    timestamp: float
    module_count: int
    total_files: int
    dependency_depth: int
    event_types_count: int
    executor_count: int
    service_count: int
    complexity_score: float
    warnings: list[str]


class ComplexityMonitor:
    """
    Monitors architectural complexity metrics.
    Detects growth trends and overengineering.
    """

    def __init__(self, score_warning_threshold: float = 50.0, score_critical_threshold: float = 80.0):
        self._warning_threshold = score_warning_threshold
        self._critical_threshold = score_critical_threshold
        self._history: list[ComplexityMetrics] = []
        self._lock = threading.Lock()
        self._last_scan_time: float = 0.0
        self._module_cache: dict[str, list[str]] = {}

    def scan(self) -> ComplexityMetrics:
        """Scan the codebase and compute complexity metrics."""
        import glob
        t0 = time.time()
        module_count = 0
        total_files = 0
        executor_count = 0
        event_types = set()
        modules: dict[str, list[str]] = {}
        core_dir = "core"

        for pattern in [f"{core_dir}/**/*.py"]:
            for f in glob.glob(pattern, recursive=True):
                if "__pycache__" in f or "test_" in f or ".pyc" in f:
                    continue
                total_files += 1
                if os.path.isdir(f):
                    continue
                rel = os.path.relpath(f).replace("\\", "/")
                parts = rel.split("/")
                if len(parts) >= 2 and parts[0] == core_dir:
                    module = parts[1]
                    if module not in modules:
                        modules[module] = []
                    modules[module].append(rel)
                    if "executor" in module:
                        executor_count += 1

        module_count = len(modules)
        dep_depth = max(len(modules.get("router", [])), 2)
        try:
            from core.events.governance import get_event_governance
            gov = get_event_governance()
            event_types = sum(len(list(g)) for g in gov._domain_registry.values())
        except Exception:
            event_types = 10
        try:
            from core.services.container import service_container
            service_count = len(service_container.list_services())
        except Exception:
            service_count = 0

        score = self._compute_score(
            module_count, total_files, executor_count,
            event_types, service_count, dep_depth,
        )
        warnings = self._detect_warnings(
            module_count, executor_count, event_types, service_count, score,
        )
        metrics = ComplexityMetrics(
            timestamp=t0, module_count=module_count, total_files=total_files,
            dependency_depth=dep_depth, event_types_count=event_types,
            executor_count=executor_count, service_count=service_count,
            complexity_score=score, warnings=warnings,
        )
        with self._lock:
            self._history.append(metrics)
            self._last_scan_time = t0
            self._module_cache = modules
        return metrics

    def _compute_score(
        self, module_count: int, total_files: int,
        executor_count: int, event_types: int,
        service_count: int, dep_depth: int,
    ) -> float:
        score = 0.0
        score += min(module_count * 2, 30)
        score += min(executor_count * 5, 20)
        score += min(event_types * 0.5, 20)
        score += min(service_count * 3, 15)
        score += min(dep_depth * 2, 10)
        score += min(total_files * 0.5, 5)
        return round(score, 1)

    def _detect_warnings(
        self, module_count: int, executor_count: int,
        event_types: int, service_count: int, score: float,
    ) -> list[str]:
        warnings = []
        if score >= self._critical_threshold:
            warnings.append("CRITICAL: Architecture complexity exceeds safe threshold")
        elif score >= self._warning_threshold:
            warnings.append("WARNING: Architecture complexity is elevated")
        if executor_count > 10:
            warnings.append("WARNING: High executor count - consider consolidation")
        if module_count > 20:
            warnings.append("WARNING: Module count is growing - verify necessity")
        if service_count > 30:
            warnings.append("WARNING: Service count is high - check for over-abstraction")
        with self._lock:
            if len(self._history) >= 5:
                trend = [h.complexity_score for h in self._history[-5:]]
                if all(trend[i] <= trend[i + 1] for i in range(len(trend) - 1)):
                    warnings.append("WARNING: Complexity score has been increasing for 5+ consecutive scans")
        return warnings

    def get_trend(self) -> dict:
        with self._lock:
            history = list(self._history)
        if len(history) < 2:
            return {"trend": "insufficient_data", "score": 0, "delta": 0}
        oldest = history[0]
        newest = history[-1]
        delta = newest.complexity_score - oldest.complexity_score
        trend = "increasing" if delta > 5 else "decreasing" if delta < -5 else "stable"
        return {
            "trend": trend,
            "current_score": newest.complexity_score,
            "delta": round(delta, 1),
            "samples": len(history),
        }

    def stats(self) -> dict:
        metrics = self.scan()
        with self._lock:
            history = list(self._history)
        return {
            "current_score": metrics.complexity_score,
            "warnings": metrics.warnings,
            "metrics": {
                "modules": metrics.module_count,
                "files": metrics.total_files,
                "executors": metrics.executor_count,
                "event_types": metrics.event_types_count,
                "services": metrics.service_count,
            },
            "trend": self.get_trend(),
            "history_samples": len(history),
        }


_global_complexity: ComplexityMonitor | None = None
_cm_lock = threading.Lock()


def get_complexity_monitor() -> ComplexityMonitor:
    global _global_complexity
    with _cm_lock:
        if _global_complexity is None:
            _global_complexity = ComplexityMonitor()
        return _global_complexity
