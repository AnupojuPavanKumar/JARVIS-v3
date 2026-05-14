# core/context/bus.py — JARVIS CONTEXT BUS
"""
Lightweight event bus exclusively for contextual intelligence events.
Decoupled from the main EventBus to keep contextual concerns separate from
system events (speech, commands, telemetry).

Context events are fire-and-forget: subscribers receive data, no return value.
All context events are local-only, never stored, no persistence.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

log = logging.getLogger("ContextBus")

class ContextLevel(Enum):
    """How intrusive/interruptive this context event is."""
    SILENT   = auto()  # passive observation, never interrupt
    LOW      = auto()  # small nudge, quiet
    MEDIUM   = auto()  # suggestion territory
    HIGH     = auto()  # active interruption warranted


@dataclass
class ContextEvent:
    """Base context event with level, source, and data."""
    level: ContextLevel = ContextLevel.LOW
    source: str = "context"
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: __import__("time").time())


# All context event types as constants (for type-safe subscribe/publish)
EVENT_WORKFLOW_CHANGED  = "workflow_changed"
EVENT_WINDOW_CHANGED    = "window_changed"
EVENT_USER_IDLE         = "user_idle"
EVENT_USER_ACTIVE       = "user_active"
EVENT_FOCUS_LOST        = "focus_lost"
EVENT_FOCUS_GAINED     = "focus_gained"
EVENT_MEETING_STARTED   = "meeting_started"
EVENT_MEETING_ENDED     = "meeting_ended"
EVENT_GAME_STARTED      = "game_started"
EVENT_GAME_ENDED        = "game_ended"
EVENT_CODING_SESSION    = "coding_session"
EVENT_IDLE_LONG         = "idle_long"
EVENT_SUGGESTION_READY  = "suggestion_ready"
EVENT_CONTEXT_CAPTURED  = "context_captured"
EVENT_PRIVACY_CHANGED   = "privacy_changed"
EVENT_WORKFLOW_SUGGEST  = "workflow_suggest"

_ALL_EVENTS = {
    EVENT_WORKFLOW_CHANGED, EVENT_WINDOW_CHANGED, EVENT_USER_IDLE,
    EVENT_USER_ACTIVE, EVENT_FOCUS_LOST, EVENT_FOCUS_GAINED,
    EVENT_MEETING_STARTED, EVENT_MEETING_ENDED, EVENT_GAME_STARTED,
    EVENT_GAME_ENDED, EVENT_CODING_SESSION, EVENT_IDLE_LONG,
    EVENT_SUGGESTION_READY, EVENT_CONTEXT_CAPTURED, EVENT_PRIVACY_CHANGED,
    EVENT_WORKFLOW_SUGGEST,
}


class ContextBus:
    """
    Thread-safe pub/sub for contextual intelligence.
    Priority subscribers receive events first; low-level events can be
    throttled by the bus if user is in focus mode.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._subscribers: dict[str, list[tuple[int, Callable]]] = {}
                cls._instance._privacy_paused: set[str] = set()
                cls._instance._last_event: dict[str, float] = {}
            return cls._instance

    def subscribe(self, event: str, callback: Callable, priority: int = 0):
        """Register callback for event. Lower priority = called first."""
        if event not in _ALL_EVENTS:
            log.warning(f"[ContextBus] Unknown event type: {event}")
            return
        with self._lock:
            if event not in self._subscribers:
                self._subscribers[event] = []
            entry = (priority, callback)
            if entry not in self._subscribers[event]:
                self._subscribers[event].append(entry)
                self._subscribers[event].sort(key=lambda x: x[0])

    def unsubscribe(self, event: str, callback: Callable):
        with self._lock:
            if event in self._subscribers:
                self._subscribers[event] = [(p, cb) for p, cb in self._subscribers[event] if cb != callback]

    def publish(self, event: str, data: dict = None, level: ContextLevel = ContextLevel.LOW):
        """Fire event to all subscribers. SILENT events always publish; others respect privacy."""
        if event in self._privacy_paused and level != ContextLevel.SILENT:
            return
        # Rate limit: minimum 5s between same events (except SILENT)
        if level != ContextLevel.SILENT:
            now = __import__("time").time()
            last = self._last_event.get(event, 0)
            if now - last < 5.0:
                return
            self._last_event[event] = now

        subscribers = []
        with self._lock:
            subscribers = list(self._subscribers.get(event, []))

        for _, cb in subscribers:
            try:
                cb(ContextEvent(level=level, source="context", data=data or {}))
            except Exception as e:
                log.debug(f"[ContextBus] {event} callback error: {e}")

    def pause_event(self, event: str):
        """Temporarily pause an event type (e.g. user enabled privacy mode)."""
        with self._lock:
            self._privacy_paused.add(event)

    def resume_event(self, event: str):
        with self._lock:
            self._privacy_paused.discard(event)

    def pause_all(self):
        with self._lock:
            self._privacy_paused.update(_ALL_EVENTS)

    def resume_all(self):
        with self._lock:
            self._privacy_paused.clear()

    @property
    def paused_events(self) -> set[str]:
        with self._lock:
            return set(self._privacy_paused)


def get_context_bus() -> ContextBus:
    return ContextBus()