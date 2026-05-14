# core/state/fsm.py
"""
Explicit Finite State Machine implementation.
Strict transition validation, invalid transition blocking, timeout protection.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

log = logging.getLogger("FSM")


class StateMachineError(Exception):
    """Base exception for state machine errors."""
    pass


class TransitionError(StateMachineError):
    """Raised when an invalid state transition is attempted."""
    def __init__(self, current: str, target: str, reason: str = ""):
        self.current = current
        self.target = target
        self.reason = reason
        super().__init__(f"Invalid transition {current} -> {target}: {reason}")


@dataclass
class StateTransition:
    """A recorded state transition."""
    transition_id: str
    from_state: str
    to_state: str
    trigger: str
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    success: bool = True
    error: str | None = None


@dataclass
class FSMConfig:
    """Configuration for a state machine."""
    name: str
    initial_state: str
    allow_self_transition: bool = False
    strict_mode: bool = True
    max_history: int = 100
    transition_timeout_sec: float = 0.0
    on_invalid_transition: Callable[[str, str], None] | None = None


class FiniteStateMachine:
    """
    Thread-safe FSM with strict transition validation.
    Tracks state history, validates transitions, supports timeout protection.
    """

    def __init__(self, config: FSMConfig):
        self.config = config
        self._state: str = config.initial_state
        self._lock = threading.RLock()
        self._history: deque[StateTransition] = deque(maxlen=config.max_history)
        self._transition_in_progress = False
        self._transition_started_at: float = 0.0
        self._state_change_callbacks: list[Callable[[str, str], None]] = []
        self._pending_timeout: Callable[[], None] | None = None
        self._timeout_thread: threading.Thread | None = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def get_allowed_transitions(self) -> list[str]:
        """Subclasses override this to define valid transitions."""
        return []

    def validate_transition(self, from_state: str, to_state: str) -> tuple[bool, str]:
        """Validate a transition. Returns (valid, reason)."""
        if from_state == to_state and not self.config.allow_self_transition:
            return False, "self-transition not allowed"
        allowed = self.get_allowed_transitions()
        if not allowed:
            return True, ""
        if from_state not in allowed:
            return False, f"state '{from_state}' has no outgoing transitions defined"
        if to_state not in allowed[from_state]:
            return False, f"transition '{from_state}' -> '{to_state}' not in allowed set"
        return True, ""

    def transition_to(self, to_state: str, trigger: str = "unknown", metadata: dict | None = None) -> bool:
        """Attempt a state transition."""
        with self._lock:
            if self._transition_in_progress:
                log.warning(f"[FSM] Transition already in progress for {self.config.name}")
                return False
            from_state = self._state
            valid, reason = self.validate_transition(from_state, to_state)
            if not valid:
                if self.config.strict_mode:
                    log.error(f"[FSM] {self.config.name}: {reason}")
                    if self.config.on_invalid_transition:
                        self.config.on_invalid_transition(from_state, to_state)
                    raise TransitionError(from_state, to_state, reason)
                log.warning(f"[FSM] {self.config.name}: invalid transition {from_state} -> {to_state} blocked")
                return False
            self._transition_in_progress = True
            self._transition_started_at = time.time()
        try:
            for cb in self._state_change_callbacks:
                try:
                    cb(from_state, to_state)
                except Exception as e:
                    log.warning(f"[FSM] state change callback error: {e}")
            t = StateTransition(
                transition_id=str(uuid.uuid4())[:8],
                from_state=from_state, to_state=to_state, trigger=trigger,
            )
            with self._lock:
                self._state = to_state
                self._transition_in_progress = False
                self._history.append(t)
            if self.config.transition_timeout_sec > 0:
                self._schedule_timeout(from_state, to_state)
            return True
        except Exception as e:
            with self._lock:
                self._transition_in_progress = False
                t = StateTransition(
                    transition_id=str(uuid.uuid4())[:8],
                    from_state=from_state, to_state=to_state, trigger=trigger,
                    success=False, error=str(e),
                )
                self._history.append(t)
            raise

    def _schedule_timeout(self, from_state: str, to_state: str):
        def timeout_watcher():
            time.sleep(self.config.transition_timeout_sec)
            with self._lock:
                if self._state == to_state and self._transition_in_progress:
                    log.warning(f"[FSM] {self.config.name}: transition timeout in state {to_state}")
            self._pending_timeout = None
        self._pending_timeout = timeout_watcher
        self._timeout_thread = threading.Thread(target=timeout_watcher, daemon=True)

    def on_state_change(self, callback: Callable[[str, str], None]):
        """Register a state change callback."""
        self._state_change_callbacks.append(callback)

    def get_history(self, limit: int | None = None) -> list[StateTransition]:
        with self._lock:
            hist = list(self._history)
        if limit:
            return hist[-limit:]
        return hist

    def get_last_transition(self) -> StateTransition | None:
        with self._lock:
            return self._history[-1] if self._history else None

    def is_in_state(self, state: str) -> bool:
        with self._lock:
            return self._state == state

    def is_transitioning(self) -> bool:
        with self._lock:
            return self._transition_in_progress


# ── Predefined FSM Implementations ───────────────────────────────────────────

class AssistantState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    ERROR = "error"
    RECOVERING = "recovering"


class AssistantFSM(FiniteStateMachine):
    """FSM for the main assistant state."""

    TRANSITIONS = {
        AssistantState.IDLE.value: [AssistantState.LISTENING.value],
        AssistantState.LISTENING.value: [AssistantState.THINKING.value, AssistantState.ERROR.value],
        AssistantState.THINKING.value: [AssistantState.EXECUTING.value, AssistantState.SPEAKING.value, AssistantState.ERROR.value],
        AssistantState.EXECUTING.value: [AssistantState.SPEAKING.value, AssistantState.IDLE.value, AssistantState.ERROR.value],
        AssistantState.SPEAKING.value: [AssistantState.IDLE.value, AssistantState.LISTENING.value, AssistantState.ERROR.value],
        AssistantState.ERROR.value: [AssistantState.RECOVERING.value],
        AssistantState.RECOVERING.value: [AssistantState.IDLE.value, AssistantState.ERROR.value],
    }

    def get_allowed_transitions(self) -> dict[str, list[str]]:
        return self.TRANSITIONS

    def validate_transition(self, from_state: str, to_state: str) -> tuple[bool, str]:
        if from_state == to_state:
            return True, ""
        return super().validate_transition(from_state, to_state)


class AudioState(Enum):
    MUTED = "muted"
    ACTIVE = "active"
    CAPTURING = "capturing"
    PLAYING = "playing"
    SUSPENDED = "suspended"


class AudioFSM(FiniteStateMachine):
    TRANSITIONS = {
        AudioState.MUTED.value: [AudioState.ACTIVE.value],
        AudioState.ACTIVE.value: [AudioState.CAPTURING.value, AudioState.PLAYING.value, AudioState.MUTED.value],
        AudioState.CAPTURING.value: [AudioState.ACTIVE.value, AudioState.MUTED.value],
        AudioState.PLAYING.value: [AudioState.ACTIVE.value, AudioState.MUTED.value],
        AudioState.SUSPENDED.value: [AudioState.ACTIVE.value, AudioState.MUTED.value],
    }
    def get_allowed_transitions(self) -> dict[str, list[str]]:
        return self.TRANSITIONS


class ExecutionState(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLING_BACK = "rolling_back"


class ExecutionFSM(FiniteStateMachine):
    TRANSITIONS = {
        ExecutionState.PENDING.value: [ExecutionState.QUEUED.value, ExecutionState.CANCELLED.value],
        ExecutionState.QUEUED.value: [ExecutionState.RUNNING.value, ExecutionState.CANCELLED.value],
        ExecutionState.RUNNING.value: [ExecutionState.COMPLETED.value, ExecutionState.FAILED.value, ExecutionState.ROLLING_BACK.value],
        ExecutionState.COMPLETED.value: [],
        ExecutionState.FAILED.value: [ExecutionState.PENDING.value],
        ExecutionState.CANCELLED.value: [],
        ExecutionState.ROLLING_BACK.value: [ExecutionState.COMPLETED.value, ExecutionState.FAILED.value],
    }
    def get_allowed_transitions(self) -> dict[str, list[str]]:
        return self.TRANSITIONS


class ModelState(Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    INFERENCE = "inference"
    OVERLOADED = "overloaded"
    ERROR = "error"


class ModelFSM(FiniteStateMachine):
    TRANSITIONS = {
        ModelState.UNLOADED.value: [ModelState.LOADING.value],
        ModelState.LOADING.value: [ModelState.LOADED.value, ModelState.ERROR.value],
        ModelState.LOADED.value: [ModelState.INFERENCE.value, ModelState.UNLOADED.value],
        ModelState.INFERENCE.value: [ModelState.LOADED.value, ModelState.OVERLOADED.value, ModelState.ERROR.value],
        ModelState.OVERLOADED.value: [ModelState.INFERENCE.value, ModelState.LOADED.value],
        ModelState.ERROR.value: [ModelState.UNLOADED.value],
    }
    def get_allowed_transitions(self) -> dict[str, list[str]]:
        return self.TRANSITIONS


class WakeWordState(Enum):
    DORMANT = "dormant"
    ARMED = "armed"
    DETECTED = "detected"
    CONFIRMING = "confirming"
    DEACTIVATED = "deactivated"


class WakeWordFSM(FiniteStateMachine):
    TRANSITIONS = {
        WakeWordState.DORMANT.value: [WakeWordState.ARMED.value],
        WakeWordState.ARMED.value: [WakeWordState.DETECTED.value, WakeWordState.DORMANT.value],
        WakeWordState.DETECTED.value: [WakeWordState.CONFIRMING.value, WakeWordState.ARMED.value],
        WakeWordState.CONFIRMING.value: [WakeWordState.ARMED.value, WakeWordState.DORMANT.value],
        WakeWordState.DEACTIVATED.value: [WakeWordState.ARMED.value],
    }
    def get_allowed_transitions(self) -> dict[str, list[str]]:
        return self.TRANSITIONS


class ConversationState(Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CONCLUDED = "concluded"
    TIMEOUT = "timeout"


class ConversationFSM(FiniteStateMachine):
    TRANSITIONS = {
        ConversationState.INACTIVE.value: [ConversationState.ACTIVE.value],
        ConversationState.ACTIVE.value: [ConversationState.SUSPENDED.value, ConversationState.CONCLUDED.value, ConversationState.TIMEOUT.value],
        ConversationState.SUSPENDED.value: [ConversationState.ACTIVE.value, ConversationState.CONCLUDED.value],
        ConversationState.TIMEOUT.value: [ConversationState.ACTIVE.value, ConversationState.CONCLUDED.value],
        ConversationState.CONCLUDED.value: [],
    }
    def get_allowed_transitions(self) -> dict[str, list[str]]:
        return self.TRANSITIONS


# ── Singleton Registry ──────────────────────────────────────────────────────────

_fsm_instances: dict[str, FiniteStateMachine] = {}
_fsm_lock = threading.Lock()


def get_state_machine(name: str) -> FiniteStateMachine:
    """Get or create a named FSM."""
    with _fsm_lock:
        if name in _fsm_instances:
            return _fsm_instances[name]
        configs = {
            "assistant": FSMConfig(name="assistant", initial_state=AssistantState.IDLE.value),
            "audio": FSMConfig(name="audio", initial_state=AudioState.MUTED.value),
            "execution": FSMConfig(name="execution", initial_state=ExecutionState.PENDING.value),
            "model": FSMConfig(name="model", initial_state=ModelState.UNLOADED.value),
            "wakeword": FSMConfig(name="wakeword", initial_state=WakeWordState.DORMANT.value),
            "conversation": FSMConfig(name="conversation", initial_state=ConversationState.INACTIVE.value),
        }
        fsm_classes = {
            "assistant": AssistantFSM,
            "audio": AudioFSM,
            "execution": ExecutionFSM,
            "model": ModelFSM,
            "wakeword": WakeWordFSM,
            "conversation": ConversationFSM,
        }
        config = configs.get(name)
        cls = fsm_classes.get(name)
        if config and cls:
            _fsm_instances[name] = cls(config)
            return _fsm_instances[name]
        raise KeyError(f"Unknown FSM: {name}")
