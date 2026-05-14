# core/companion/session_memory.py — JARVIS SESSION CONTINUITY
"""
Session memory: tracks the current session's context for continuity.
Complements WorkspaceMemory (long-term) with session-scoped context:
  - current task
  - last N commands in this session
  - recent errors/attempts
  - unfinished commands
  - session duration

Loaded on startup to detect: "continue" / "keep going" / "same as before"
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

_MAX_HISTORY = 20
_MAX_ERRORS  = 5


@dataclass
class SessionEntry:
    command: str
    result: str
    timestamp: float
    success: bool
    intent: str = ""


@dataclass
class SessionMemory:
    """
    Lightweight session-scoped context.
    Cleared on new session, survives JARVIS restarts via CheckpointManager.
    """
    session_id: str
    started_at: float = field(default_factory=time.time)
    last_command: str = ""
    last_result: str = ""
    last_intent: str = ""
    last_app: str = ""
    current_task: str = ""   # what user is currently working on
    history: deque = field(default_factory=lambda: deque(maxlen=_MAX_HISTORY))
    errors: deque = field(default_factory=lambda: deque(maxlen=_MAX_ERRORS))
    interrupted: bool = False

    def record(self, command: str, result: str, intent: str = "", success: bool = True):
        self.last_command = command
        self.last_result  = result
        self.last_intent  = intent
        self.history.append(SessionEntry(
            command=command, result=result,
            timestamp=time.time(), success=success, intent=intent,
        ))
        if not success:
            self.errors.append(command)

    def set_task(self, task: str):
        self.current_task = task

    def mark_interrupted(self):
        self.interrupted = True

    def is_resumable(self) -> bool:
        return bool(self.current_task and self.last_command)

    def get_summary(self) -> dict:
        """One-line session summary for context restoration."""
        duration = time.time() - self.started_at
        return {
            "session_id":    self.session_id,
            "duration_min": duration / 60,
            "commands":     len(self.history),
            "last_command": self.last_command,
            "current_task": self.current_task,
            "last_intent": self.last_intent,
            "errors":       len(self.errors),
            "is_resumable": self.is_resumable(),
        }

    def can_continue(self, command: str) -> bool:
        """Does 'command' look like a continuation of an unfinished session?"""
        low = command.lower().strip()
        continue_signals = ["continue", "keep going", "same", "again",
                            "still", "not done", "incomplete", "leftover",
                            "carry on", "go on"]
        return any(s in low for s in continue_signals)

    def format_continuation(self) -> str:
        """Return a natural continuation prompt for the user."""
        if not self.is_resumable():
            return ""
        ctx = self.get_summary()
        if ctx["errors"] > 0:
            return f"Continuing from: {self.last_command} (with {ctx['errors']} errors)"
        return f"Continuing from: {self.last_command}"


class SessionContinuity:
    """
    Manages session memory across JARVIS restarts.
    Loads previous session from checkpoint, evaluates resumability,
    and provides continuation context.
    """

    def __init__(self, checkpoint=None):
        self._checkpoint  = checkpoint
        self._session    = None
        self._lock       = threading.Lock()

    def start_session(self, session_id: str):
        with self._lock:
            self._session = SessionMemory(session_id=session_id)

    def get_session(self) -> SessionMemory | None:
        return self._session

    def record_command(self, command: str, result: str, intent: str = "", success: bool = True):
        if self._session:
            self._session.record(command, result, intent, success)

    def get_previous_context(self) -> dict:
        """Load last session's summary from checkpoint."""
        if self._checkpoint is None:
            return {}
        return self._checkpoint.get_recovery_context()

    def should_offer_continuation(self) -> bool:
        """Should we suggest resuming the previous session?"""
        prev = self.get_previous_context()
        if not prev:
            return False
        return (
            prev.get("is_recent", False) and
            prev.get("commands", 0) > 3 and
            prev.get("workflow") is not None
        )

    def get_continuation_text(self) -> str:
        """Natural text for suggesting session continuation."""
        prev = self.get_previous_context()
        if not prev:
            return ""

        parts = []
        if prev.get("commands", 0) > 0:
            parts.append(f"{prev.get('commands')} commands last session")

        workflow = prev.get("workflow", "")
        if workflow:
            parts.append(f"workflow: {workflow.replace('_', ' ')}")

        # Ask cognitive compressor for compressed narrative
        try:
            from core.companion.cognitive_compression import get_cognitive_compressor
            cc = get_cognitive_compressor()
            narrative = cc.get_continuation_prompt()
            if narrative:
                return narrative
        except Exception:
            pass

        base = ". ".join(parts) + "." if parts else ""
        if base:
            return base + " Continue where you left off?"
        return "Continue where you left off?"


_instance: Optional[SessionContinuity] = None
_lock = threading.Lock()

def get_session_continuity() -> SessionContinuity:
    global _instance
    with _lock:
        if _instance is None:
            from core.companion.checkpoint import get_checkpoint
            _instance = SessionContinuity(checkpoint=get_checkpoint())
        return _instance