# core/events/__init__.py
"""
Event bus architecture — pub/sub pattern for decoupled orchestration.
Preserves existing threading model, no massive rewrites.
"""
from core.events.bus import EventBus, Event, EventPriority, get_event_bus
from typing import Protocol, runtime_checkable

__all__ = ["EventBus", "Event", "EventPriority", "get_event_bus", "EventSubscriber"]
