# core/governance/__init__.py
"""
Complexity governance & DI governance & memory domains & predictive scheduling.
P10: Complexity scoring, architecture warnings. P4: DI governance.
P6: Structured memory domains. P5: Predictive resource scheduling.
"""
from core.governance.complexity import ComplexityMonitor, get_complexity_monitor
from core.governance.di_governance import DIGoverner, get_di_governor
from core.governance.memory_domains import MemoryDomains, MemoryDomain, get_memory_domains
from core.governance.predictive_scheduler import PredictiveScheduler, get_predictive_scheduler

__all__ = [
    "ComplexityMonitor", "get_complexity_monitor",
    "DIGoverner", "get_di_governor",
    "MemoryDomains", "MemoryDomain", "get_memory_domains",
    "PredictiveScheduler", "get_predictive_scheduler",
]
