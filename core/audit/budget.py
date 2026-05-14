# core/audit/budget.py
"""
Complexity budget system — P13.
Hard limits: max module count, max orchestration depth, max service dependencies,
max event fanout, max startup time, max background threads.
Generates budget violations. New complexity must justify itself.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger("ComplexityBudget")


@dataclass
class BudgetLimit:
    name: str
    hard_limit: float
    soft_limit: float = 0.0
    current: float = 0.0
    unit: str = ""
    description: str = ""


@dataclass
class BudgetViolation:
    limit_name: str
    current: float
    limit: float
    severity: str
    timestamp: float
    suggestion: str


class ComplexityBudget:
    """
    Hard complexity limits that must be respected.
    Prevents unbounded architectural growth.
    """

    def __init__(self):
        self._limits: Dict[str, BudgetLimit] = {
            "max_module_count": BudgetLimit(
                name="max_module_count", hard_limit=50, current=0,
                unit="modules", description="Maximum number of core submodules",
            ),
            "max_orchestration_depth": BudgetLimit(
                name="max_orchestration_depth", hard_limit=20, current=0,
                unit="steps", description="Maximum depth of any orchestration chain",
            ),
            "max_service_dependencies": BudgetLimit(
                name="max_service_dependencies", hard_limit=5, current=0,
                unit="deps", description="Maximum direct dependencies per service",
            ),
            "max_event_fanout": BudgetLimit(
                name="max_event_fanout", hard_limit=20, current=0,
                unit="subscribers", description="Maximum subscribers per event type",
            ),
            "max_startup_time_ms": BudgetLimit(
                name="max_startup_time_ms", hard_limit=2000.0, current=0,
                unit="ms", description="Maximum startup time",
            ),
            "max_background_threads": BudgetLimit(
                name="max_background_threads", hard_limit=15, current=0,
                unit="threads", description="Maximum background daemon threads",
            ),
            "max_executor_count": BudgetLimit(
                name="max_executor_count", hard_limit=15, current=0,
                unit="executors", description="Maximum number of executor modules",
            ),
            "max_fsm_count": BudgetLimit(
                name="max_fsm_count", hard_limit=10, current=0,
                unit="FSMs", description="Maximum number of FSM instances",
            ),
            "max_policy_count": BudgetLimit(
                name="max_policy_count", hard_limit=50, current=0,
                unit="policies", description="Maximum registered policies",
            ),
            "max_memory_domain_size": BudgetLimit(
                name="max_memory_domain_size", hard_limit=10000, current=0,
                unit="entries", description="Maximum entries per memory domain",
            ),
        }
        self._violations: List[BudgetViolation] = []
        self._lock = threading.Lock()
        self._last_audit_time: float = 0.0

    def update(self, name: str, current: float):
        """Update a budget limit's current value."""
        with self._lock:
            if name in self._limits:
                self._limits[name].current = current
                if current > self._limits[name].hard_limit:
                    self._record_violation(name, current, self._limits[name].hard_limit)

    def _record_violation(self, name: str, current: float, limit: float):
        severity = "CRITICAL" if current > limit * 1.5 else "WARNING"
        suggestion = self._get_suggestion(name, current, limit)
        violation = BudgetViolation(
            limit_name=name, current=current, limit=limit,
            severity=severity, timestamp=time.time(), suggestion=suggestion,
        )
        self._violations.append(violation)
        log.warning(f"[ComplexityBudget] VIOLATION [{severity}]: {name} = {current} (limit: {limit})")

    def _get_suggestion(self, name: str, current: float, limit: float) -> str:
        suggestions = {
            "max_module_count": "Consider merging overlapping modules before adding new ones",
            "max_orchestration_depth": "Reduce nested callbacks or split the orchestration chain",
            "max_service_dependencies": "Use facade services or lazy composition to reduce direct deps",
            "max_event_fanout": "Consider event aggregation or hierarchical event structure",
            "max_startup_time_ms": "Lazy-load non-critical subsystems; defer background scans",
            "max_background_threads": "Merge polling loops or use shared timer threads",
            "max_executor_count": "Consolidate similar executors before adding new ones",
            "max_fsm_count": "Consider merging overlapping FSMs into shared base",
            "max_policy_count": "Prune inactive policies before adding new ones",
            "max_memory_domain_size": "Reduce TTL or increase eviction aggressiveness",
        }
        return suggestions.get(name, "Justify this new complexity before proceeding")

    def audit_all(self) -> Dict[str, dict]:
        """Run a full budget audit and return results."""
        now = time.time()
        if now - self._last_audit_time < 5.0:
            return {}
        self._last_audit_time = now
        results = {}
        with self._lock:
            for name, limit in self._limits.items():
                current = self._measure_current(name)
                limit.current = current
                status = "OK"
                if current > limit.hard_limit * 1.5:
                    status = "CRITICAL"
                elif current > limit.hard_limit:
                    status = "WARNING"
                elif current > limit.hard_limit * 0.8:
                    status = "CAUTION"
                results[name] = {
                    "current": round(current, 1),
                    "hard_limit": limit.hard_limit,
                    "utilization": round(current / max(limit.hard_limit, 1) * 100, 1),
                    "status": status,
                }
        return results

    def _measure_current(self, name: str) -> float:
        if name == "max_module_count":
            import glob
            modules = [d for d in glob.glob("core/*") if os.path.isdir(d) and not d.startswith("core\\__pycache__")]
            return float(len(modules))
        if name == "max_background_threads":
            import threading
            return float(sum(1 for t in threading.enumerate() if t.daemon and t.is_alive()))
        if name == "max_executor_count":
            import glob
            return float(len(glob.glob("core/executor/*.py")) - 1)
        if name == "max_service_dependencies":
            from core.services.container import service_container
            services = service_container.list_services()
            if not services:
                return 0.0
            from core.governance.di_governance import get_di_governor
            di = get_di_governor()
            max_depth = 0
            for s in services:
                ok, depth = di.check_dependency_depth(service_container, s)
                max_depth = max(max_depth, depth)
            return float(max_depth)
        if name == "max_fsm_count":
            from core.state.fsm import _fsm_instances
            return float(len(_fsm_instances))
        if name == "max_policy_count":
            from core.orchestration.policies import get_policy_engine
            return float(get_policy_engine().get_stats()["total_policies"])
        return 0.0

    def get_active_violations(self) -> List[BudgetViolation]:
        with self._lock:
            return [v for v in self._violations if time.time() - v.timestamp < 60]

    def get_budget_summary(self) -> dict:
        audit = self.audit_all()
        return {
            "limits": {name: {"current": r["current"], "hard_limit": r["hard_limit"],
                             "utilization": r["utilization"], "status": r["status"]}
                       for name, r in audit.items()},
            "active_violations": len(self.get_active_violations()),
            "total_violations": len(self._violations),
        }


_global_budget: ComplexityBudget | None = None
_bgt_lock = threading.Lock()


def get_budget() -> ComplexityBudget:
    global _global_budget
    with _bgt_lock:
        if _global_budget is None:
            _global_budget = ComplexityBudget()
        return _global_budget
