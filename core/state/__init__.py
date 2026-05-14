# core/state/__init__.py
"""
Finite State Machines — explicit state management for all major subsystems.
Strict transition validation, invalid transition blocking, state transition tracing.
"""
from core.state.fsm import (
    FiniteStateMachine, TransitionError, StateMachineError,
    AssistantState, AudioState, ExecutionState, ModelState,
    WakeWordState, ConversationState, get_state_machine,
)
from core.state.registry import StateRegistry, get_state_registry

__all__ = [
    "FiniteStateMachine", "TransitionError", "StateMachineError",
    "AssistantState", "AudioState", "ExecutionState", "ModelState",
    "WakeWordState", "ConversationState",
    "get_state_machine", "StateRegistry", "get_state_registry",
]
