# core/simulation/__init__.py
"""
Simulation & chaos testing framework — P9.
Event storms, VRAM exhaustion, microphone failure, dead subprocesses,
queue overload, model crashes, slow inference, event propagation loops.
Deterministic replay, stress-test harness, orchestration fuzz testing.
"""
from core.simulation.framework import ChaosEngine, SimulationScenario, get_chaos_engine

__all__ = ["ChaosEngine", "SimulationScenario", "get_chaos_engine"]
