# core/system/readiness_state.py — JARVIS SUBSYSTEM READINESS TRACKING
"""
Tracks readiness state for every JARVIS subsystem.

States: UNINITIALIZED → INITIALIZING → READY → DEGRADED → FAILED

Subsystems report their state. UI queries capability readiness
before presenting interactive features.

Capability model (what the user can DO):
  FAST_COMMAND — deterministic routing works (sub-50ms commands)
  VOICE       — voice input + output works end-to-end
  AI          — LLM inference available
  OCR         — screen capture + OCR available
  CONTEXT     — proactive suggestions + workspace awareness
  AUTOMATION  — checkpoint/session recovery available
"""
from __future__ import annotations

import threading
import time
from collections import deque
from enum import Enum, auto
from typing import Callable, Optional

ReadinessCallback = Callable[[str, str], None]


class ReadinessState(Enum):
    UNINITIALIZED = auto()
    INITIALIZING  = auto()
    READY         = auto()
    DEGRADED      = auto()
    FAILED        = auto()


_SUBSYSTEMS = [
    # Phase 2 — Core runtime
    "event_bus",
    "execution_queue",
    "fast_router",
    "deterministic_executor",
    "command_orchestrator",
    # Phase 3 — Background services
    "checkpoint_manager",
    "session_continuity",
    "phrase_rotation",
    "cognitive_continuity",
    "cognitive_compression",
    "fatigue_model",
    "graceful_degradation",
    "trust_model",
    "domain_trust",
    "frustration_detector",
    "behavior_drift",
    "layered_memory",
    "interaction_closure",
    "confidence_rhythm",
    "calm_engine",
    "recovery_engine",
    "workspace_observer",
    "suggestion_engine",
    "hardware_sentinel",
    "watchdog",
    "capability_validator",
    "pressure_governor",
    "recovery_orchestrator",
    "runtime_confidence",
    "meta_stability_guard",
    "domain_confidence",
    "equilibrium_monitor",
    "degradation_persona",
    "runtime_explainability",
    # Phase 4 — Heavy systems
    "ollama_manager",
    "model_prewarmer",
    "voice_stt",
    "voice_tts",
    "voice_worker",
    "wake_word",
    "voice_interrupt",
    "telemetry",
    "memory_service",
]

_CAPABILITY_MAP = {
    "FAST_COMMAND": {
        "fast_router", "deterministic_executor", "execution_queue", "event_bus",
    },
    "VOICE": {
        "voice_stt", "voice_tts", "wake_word", "voice_worker",
    },
    "AI": {
        "ollama_manager", "model_prewarmer", "memory_service",
    },
    "OCR": {
        "vision_engine",
    },
    "CONTEXT": {
        "suggestion_engine", "workspace_observer", "cognitive_continuity",
    },
    "AUTOMATION": {
        "checkpoint_manager", "session_continuity", "recovery_engine",
        "graceful_degradation",
    },
}


class ReadinessTracker:
    """
    Centralized subsystem readiness tracking.
    All subsystems register via mark_initializing() → mark_ready().
    """

    def __init__(self):
        self._lock: threading.RLock = threading.RLock()
        self._states: dict[str, ReadinessState] = {
            s: ReadinessState.UNINITIALIZED for s in _SUBSYSTEMS
        }
        self._init_started: dict[str, float] = {}
        self._init_complete: dict[str, float] = {}
        self._failures: dict[str, str] = {}
        self._listeners: list[ReadinessCallback] = []
        self._phase = 0
        self._audit: deque[dict] = deque(maxlen=200)

    def set_phase(self, phase: int):
        with self._lock:
            self._phase = phase

    def mark_initializing(self, subsystem: str):
        with self._lock:
            current = self._states.get(subsystem)
            if current in (ReadinessState.READY, ReadinessState.DEGRADED):
                return
            self._states[subsystem] = ReadinessState.INITIALIZING
            self._init_started[subsystem] = time.time()
            self._audit.append({
                "ts": time.time(),
                "subsystem": subsystem,
                "event": "INITIALIZING",
                "phase": self._phase,
            })
        self._notify(subsystem, ReadinessState.INITIALIZING)

    def mark_ready(self, subsystem: str):
        with self._lock:
            self._states[subsystem] = ReadinessState.READY
            self._init_complete[subsystem] = time.time()
            self._audit.append({
                "ts": time.time(),
                "subsystem": subsystem,
                "event": "READY",
                "duration_ms": (self._init_complete[subsystem] - self._init_started.get(subsystem, self._init_complete[subsystem])) * 1000,
            })
        self._notify(subsystem, ReadinessState.READY)

    def mark_degraded(self, subsystem: str, reason: str = ""):
        with self._lock:
            self._states[subsystem] = ReadinessState.DEGRADED
            self._failures[subsystem] = reason
            self._audit.append({
                "ts": time.time(),
                "subsystem": subsystem,
                "event": "DEGRADED",
                "reason": reason,
            })
        self._notify(subsystem, ReadinessState.DEGRADED)

    def mark_failed(self, subsystem: str, reason: str = ""):
        with self._lock:
            self._states[subsystem] = ReadinessState.FAILED
            self._failures[subsystem] = reason
            self._audit.append({
                "ts": time.time(),
                "subsystem": subsystem,
                "event": "FAILED",
                "reason": reason,
            })
        self._notify(subsystem, ReadinessState.FAILED)

    def get_state(self, subsystem: str) -> ReadinessState:
        with self._lock:
            return self._states.get(subsystem, ReadinessState.UNINITIALIZED)

    def get_all(self) -> dict[str, ReadinessState]:
        with self._lock:
            return dict(self._states)

    def is_ready(self, subsystem: str) -> bool:
        return self.get_state(subsystem) in (ReadinessState.READY, ReadinessState.DEGRADED)

    def is_all_ready(self, subsystems: list[str]) -> bool:
        return all(self.is_ready(s) for s in subsystems)

    def ready_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._states.values()
                        if s in (ReadinessState.READY, ReadinessState.DEGRADED))

    def total_count(self) -> int:
        return len(_SUBSYSTEMS)

    def readiness_pct(self) -> float:
        return self.ready_count() / max(1, self.total_count())

    def init_duration_ms(self, subsystem: str) -> float | None:
        with self._lock:
            started = self._init_started.get(subsystem)
            complete = self._init_complete.get(subsystem)
        if started and complete:
            return (complete - started) * 1000
        return None

    def get_degraded(self) -> list[str]:
        with self._lock:
            return [s for s, st in self._states.items()
                    if st == ReadinessState.DEGRADED]

    def get_failed(self) -> list[str]:
        with self._lock:
            return [s for s, st in self._states.items()
                    if st == ReadinessState.FAILED]

    def subscribe(self, callback: ReadinessCallback):
        self._listeners.append(callback)

    def _notify(self, subsystem: str, state: ReadinessState):
        for cb in self._listeners:
            try:
                cb(subsystem, state.name)
            except Exception:
                pass

    def get_summary(self) -> dict:
        with self._lock:
            total = len(self._states)
            ready = sum(1 for s in self._states.values() if s == ReadinessState.READY)
            degraded = sum(1 for s in self._states.values() if s == ReadinessState.DEGRADED)
            failed = sum(1 for s in self._states.values() if s == ReadinessState.FAILED)
            initializing = sum(1 for s in self._states.values() if s == ReadinessState.INITIALIZING)
            return {
                "phase": self._phase,
                "total": total,
                "ready": ready,
                "degraded": degraded,
                "failed": failed,
                "initializing": initializing,
                "pct": round(ready / max(1, total) * 100, 1),
            }

    # ── Capability readiness ─────────────────────────────────────────────────

    def get_capability(self, name: str) -> bool:
        """
        Returns True if ALL required subsystems for the named capability are ready.

        Capability names: FAST_COMMAND, VOICE, AI, OCR, CONTEXT, AUTOMATION
        """
        required = _CAPABILITY_MAP.get(name, set())
        if not required:
            return False
        return all(self.is_ready(s) for s in required if s in self._states)

    def get_capabilities(self) -> dict[str, bool]:
        """All capability readiness states."""
        return {cap: self.get_capability(cap) for cap in _CAPABILITY_MAP}

    def get_user_status(self) -> str:
        """
        Human-readable status of what the user can actually do.
        Used by UI to present meaningful readiness.
        """
        caps = self.get_capabilities()
        ready = [k for k, v in caps.items() if v]
        with self._lock:
            degraded = [s for s, st in self._states.items() if st == ReadinessState.DEGRADED]
            failed = [s for s, st in self._states.items() if st == ReadinessState.FAILED]

        parts = []
        if caps.get("FAST_COMMAND"):
            parts.append("commands")
        if caps.get("VOICE"):
            parts.append("voice")
        if caps.get("AI"):
            parts.append("AI")
        if caps.get("CONTEXT"):
            parts.append("context")

        if not parts:
            return "INITIALIZING"
        status = " / ".join(parts)
        if degraded:
            status += f" ({len(degraded)} degraded)"
        if failed:
            status += f" ({len(failed)} unavailable)"
        return status

    # ── Audit ────────────────────────────────────────────────────────────────

    def get_audit(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._audit)[-limit:]

    def audit_summary(self) -> dict:
        with self._lock:
            events_by_subsystem: dict[str, int] = {}
            for ev in self._audit:
                s = ev["subsystem"]
                events_by_subsystem[s] = events_by_subsystem.get(s, 0) + 1
            return {
                "total_events": len(self._audit),
                "events_by_subsystem": events_by_subsystem,
                "init_order": [
                    e["subsystem"] for e in self._audit
                    if e["event"] == "READY"
                ],
            }


_instance: Optional[ReadinessTracker] = None
_lock = threading.Lock()


def get_readiness_tracker() -> ReadinessTracker:
    global _instance
    with _lock:
        if _instance is None:
            _instance = ReadinessTracker()
        return _instance
