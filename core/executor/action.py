# core/executor/action.py — JARVIS Structured Action Objects
"""
Structured Action schema with lifecycle states, validation, and serialization.
Used by DeterministicExecutor and all sub-executors.
"""
from __future__ import annotations

import time
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable, Any

log = logging.getLogger("Action")


class ActionState(Enum):
    PENDING = auto()
    VALIDATED = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class ActionType(Enum):
    OPEN_APP = auto()
    CLOSE_APP = auto()
    VOLUME_CONTROL = auto()
    MEDIA_CONTROL = auto()
    SYSTEM_CONTROL = auto()
    WINDOW_CONTROL = auto()
    WEB_SEARCH = auto()
    FILE_OPEN = auto()
    COMPOSITE = auto()   # multi-step action
    AI_FALLBACK = auto()  # defer to LLM


@dataclass
class Action:
    """
    Structured execution unit with full lifecycle support.
    Replaces raw execute_fast() calls.
    """
    action_type: ActionType
    target: str
    raw_command: str
    confidence: float = 0.0
    source: str = "fast_router"  # which component created this action
    priority: int = 5              # 1 (highest) to 10 (lowest)

    # Identity
    action_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)

    # Lifecycle
    state: ActionState = ActionState.PENDING

    # Execution tracking
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: Optional[float] = None

    # Error handling
    error: Optional[str] = None
    error_detail: Optional[str] = None

    # Result
    result_message: Optional[str] = None
    success: bool = False

    # Children (for composite actions)
    children: list[Action] = field(default_factory=list)

    # Metadata
    params: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    # ── State transitions ─────────────────────────────────────────────────────

    def validate(self) -> bool:
        try:
            self._pre_validate()
            self.state = ActionState.VALIDATED
            return True
        except Exception as e:
            self._fail(str(e), str(e))
            return False

    def start(self):
        self.state = ActionState.RUNNING
        self.started_at = time.time()

    def complete(self, message: str = ""):
        self.state = ActionState.COMPLETED
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.started_at) * 1000 if self.started_at else 0
        self.success = True
        self.result_message = message
        log.info(
            f"[Action] {self.action_type.name} completed in {self.duration_ms:.1f}ms: {message}"
        )

    def _fail(self, error: str, detail: str = ""):
        self.state = ActionState.FAILED
        self.completed_at = time.time()
        self.duration_ms = (self.completed_at - self.started_at) * 1000 if self.started_at else 0
        self.error = error
        self.error_detail = detail
        self.success = False
        log.error(f"[Action] {self.action_type.name} FAILED: {error} ({detail})")

    def cancel(self):
        if self.state in (ActionState.PENDING, ActionState.VALIDATED):
            self.state = ActionState.CANCELLED
            self.completed_at = time.time()
            log.warning(f"[Action] {self.action_type.name} cancelled")

    # ── Validation ────────────────────────────────────────────────────────────

    def _pre_validate(self):
        if not self.target and self.action_type not in (
            ActionType.MEDIA_CONTROL, ActionType.VOLUME_CONTROL,
        ):
            raise ValueError(f"Action {self.action_id} has no target")
        if self.confidence < 0:
            raise ValueError(f"Action {self.action_id} has invalid confidence")
        if self.priority < 1 or self.priority > 10:
            raise ValueError(f"Action {self.action_id} priority out of range")

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.name,
            "target": self.target,
            "raw_command": self.raw_command,
            "confidence": self.confidence,
            "source": self.source,
            "priority": self.priority,
            "state": self.state.name,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "result_message": self.result_message,
            "timestamp": self.timestamp,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Action:
        action = cls(
            action_type=ActionType[data.get("action_type", "OPEN_APP")],
            target=data.get("target", ""),
            raw_command=data.get("raw_command", ""),
            confidence=data.get("confidence", 0.0),
            source=data.get("source", "deserialized"),
            priority=data.get("priority", 5),
        )
        action.action_id = data.get("action_id", action.action_id)
        action.timestamp = data.get("timestamp", action.timestamp)
        return action

    # ── Composite actions ─────────────────────────────────────────────────────

    def add_child(self, child: Action):
        child.priority = max(1, self.priority + 1)
        self.children.append(child)

    def is_composite(self) -> bool:
        return len(self.children) > 0

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        return f"{self.action_type.name}({self.target or 'default'})"

    def __repr__(self) -> str:
        return f"Action({self.action_type.name}, target={self.target!r}, state={self.state.name}, id={self.action_id[:8]})"