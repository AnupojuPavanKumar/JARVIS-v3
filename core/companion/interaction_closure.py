# core/companion/interaction_closure.py — JARVIS INTERACTION CLOSURE
"""
Detects when workflows/tasks are complete and provides natural closure.

Detects:
  - completed debugging sessions
  - finished coding workflows
  - end-of-session transitions
  - successful task completion

Adds:
  - lightweight completion summaries
  - subtle completion acknowledgments
  - operational state transitions

No cheesy motivational language. Clean, brief, done.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

_MAX_HISTORY = 30


@dataclass
class WorkflowSnapshot:
    category: str
    topic: str
    command_count: int
    success_count: int
    failure_count: int
    started_at: float
    last_activity: float
    completed: bool = False
    completion_summary: str = ""


class InteractionClosure:
    """
    Detects task/workflow completion and provides natural closure.
    No celebration, no "great work!", just clean acknowledgment.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._workflows: deque[WorkflowSnapshot] = deque(maxlen=_MAX_HISTORY)
        self._active_workflow: Optional[WorkflowSnapshot] = None
        self._idle_since: float = time.time()
        self._last_command_time: float = time.time()

    def record_command(self, command: str, success: bool, category: str = ""):
        """Record a command within the active workflow."""
        now = time.time()
        self._last_command_time = now

        with self._lock:
            if self._active_workflow is None:
                self._active_workflow = WorkflowSnapshot(
                    category=category or self._infer_category(command),
                    topic=self._infer_topic(command),
                    command_count=0, success_count=0, failure_count=0,
                    started_at=now, last_activity=now,
                )
                self._workflows.append(self._active_workflow)

            wf = self._active_workflow
            wf.command_count += 1
            wf.last_activity = now
            if success:
                wf.success_count += 1
            else:
                wf.failure_count += 1

            if len(self._workflows) > _MAX_HISTORY:
                self._workflows.popleft()

    def detect_completion(self, force: bool = False) -> Optional[str]:
        """Check if the active workflow appears complete. Returns summary or None."""
        now = time.time()
        idle_time = now - self._last_command_time

        with self._lock:
            if self._active_workflow is None:
                return None

            wf = self._active_workflow

            completion_signals = [
                force,
                idle_time > 300 and wf.command_count > 2,
                self._has_completion_language(),
            ]

            if not any(completion_signals):
                return None

            wf.completed = True
            summary = self._build_summary(wf)
            wf.completion_summary = summary
            self._active_workflow = None
            return summary

    def _has_completion_language(self) -> bool:
        last_commands = [e.command for e in self._workflows][-5:]
        completion_phrases = [
            "done", "finished", "complete", "all set", "that works",
            "it's working", "fixed", "solved", "resolved", "handled",
        ]
        for cmd in last_commands:
            if any(phrase in cmd.lower() for phrase in completion_phrases):
                return True
        return False

    def _infer_category(self, command: str) -> str:
        low = command.lower()
        cats = [
            ("debug", "debugging"),
            ("fix", "debugging"), ("error", "debugging"),
            ("build", "coding"), ("create", "coding"), ("implement", "coding"),
            ("test", "testing"), ("run tests", "testing"),
            ("research", "research"), ("find out", "research"),
            ("deploy", "setup"), ("setup", "setup"), ("install", "setup"),
        ]
        for phrase, cat in cats:
            if phrase in low:
                return cat
        return "general"

    def _infer_topic(self, command: str) -> str:
        words = command.split()
        return " ".join(words[:4]).strip()

    def _build_summary(self, wf: WorkflowSnapshot) -> str:
        if wf.command_count == 0:
            return ""

        success_rate = wf.success_count / wf.command_count if wf.command_count > 0 else 0
        duration = (wf.last_activity - wf.started_at) / 60

        if wf.category == "debugging":
            if success_rate >= 0.8:
                return f"Debugged {wf.topic}. Resolved."
            elif success_rate >= 0.5:
                return f"Worked on {wf.topic}. Partially resolved."
            else:
                return f"Debugged {wf.topic}. Issue persists."

        if wf.category == "coding":
            if success_rate >= 0.9:
                return f"Built {wf.topic}. Complete."
            return f"Worked on {wf.topic}."

        if wf.category == "testing":
            return f"Tested {wf.topic}."

        if wf.category == "setup":
            return f"Set up {wf.topic}."

        if wf.category == "research":
            return f"Researched {wf.topic}."

        return f"Completed {wf.topic} ({wf.command_count} commands)."

    def get_last_workflow_summary(self) -> Optional[str]:
        with self._lock:
            for wf in reversed(self._workflows):
                if wf.completed:
                    return wf.completion_summary
            if self._active_workflow and self._active_workflow.command_count > 2:
                return self._build_summary(self._active_workflow)
            return None

    def is_workflow_active(self) -> bool:
        with self._lock:
            return self._active_workflow is not None

    def get_active_topic(self) -> Optional[str]:
        with self._lock:
            return self._active_workflow.topic if self._active_workflow else None


_instance: Optional[InteractionClosure] = None
_lock = threading.Lock()


def get_interaction_closure() -> InteractionClosure:
    global _instance
    with _lock:
        if _instance is None:
            _instance = InteractionClosure()
        return _instance