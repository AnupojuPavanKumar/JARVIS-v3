# core/state/registry.py
"""
State registry — central tracking of all FSM instances.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FSMHealthInfo:
    name: str
    state: str
    transitioning: bool
    last_transition: str | None
    transitions_count: int
    errors_count: int


class StateRegistry:
    """Central registry of all FSM instances."""

    def __init__(self):
        self._fsm_states: dict[str, FSMHealthInfo] = {}
        self._lock = threading.RLock()

    def register(self, name: str, fsm):
        with self._lock:
            self._fsm_states[name] = FSMHealthInfo(
                name=name, state=fsm.state,
                transitioning=fsm.is_transitioning(),
                last_transition=None, transitions_count=0, errors_count=0,
            )

    def refresh(self):
        with self._lock:
            for name in list(self._fsm_states.keys()):
                from core.state.fsm import _fsm_instances
                if name in _fsm_instances:
                    fsm = _fsm_instances[name]
                    h = self._fsm_states[name]
                    history = fsm.get_history(10)
                    errors = sum(1 for t in history if not t.success)
                    last = history[-1] if history else None
                    self._fsm_states[name] = FSMHealthInfo(
                        name=name, state=fsm.state,
                        transitioning=fsm.is_transitioning(),
                        last_transition=f"{last.from_state} -> {last.to_state}" if last else None,
                        transitions_count=len(history),
                        errors_count=errors,
                    )

    def get_health(self, name: str) -> FSMHealthInfo | None:
        with self._lock:
            return self._fsm_states.get(name)

    def all_health(self) -> dict[str, FSMHealthInfo]:
        with self._lock:
            return dict(self._fsm_states)


_global_registry: StateRegistry | None = None
_reg_lock = threading.Lock()


def get_state_registry() -> StateRegistry:
    global _global_registry
    with _reg_lock:
        if _global_registry is None:
            _global_registry = StateRegistry()
        return _global_registry
