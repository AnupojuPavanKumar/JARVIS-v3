# core/performance/__init__.py
"""
Performance governors — latency enforcement, watchdog timers,
execution benchmarking, slow-path detection, profiling instrumentation.
"""
from core.performance.governors import PerformanceGovernor, LatencyBudget, get_governor

__all__ = ["PerformanceGovernor", "LatencyBudget", "get_governor"]
