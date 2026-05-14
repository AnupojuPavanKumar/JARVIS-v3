# core/intents/context_resolver.py
"""
Conversational context resolution layer.
Lightweight memory for recent entities, active windows, last-action references,
and pronoun resolution. Deterministic first, AI fallback only when ambiguous.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

log = logging.getLogger("ContextResolver")


class EntityType(Enum):
    APP = auto()
    WINDOW = auto()
    MEDIA = auto()
    FILE = auto()
    COMMAND = auto()
    NONE = auto()


@dataclass
class Entity:
    """A recent entity (app, window, media, etc.)."""
    type: EntityType
    name: str
    identifier: str
    resolved_path: str | None = None
    last_referenced: float = field(default_factory=time.time)
    reference_count: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class ActionReference:
    """A reference to a recently executed action."""
    action_id: str
    action_type: str
    target: str
    result: str = ""
    timestamp: float = field(default_factory=time.time)
    undone: bool = False


class ContextResolver:
    """
    Lightweight conversational context memory.
    Tracks recent entities and resolves pronouns/references deterministically.
    """

    def __init__(self, max_entities: int = 20, max_actions: int = 20):
        self._entities: deque[Entity] = deque(maxlen=max_entities)
        self._actions: deque[ActionReference] = deque(maxlen=max_actions)
        self._focused_window: str | None = None
        self._last_command: str = ""
        self._lock = threading.RLock()

    def record_entity(self, entity: Entity):
        """Record a detected entity."""
        with self._lock:
            for existing in self._entities:
                if existing.identifier == entity.identifier:
                    existing.last_referenced = time.time()
                    existing.reference_count += 1
                    return
            self._entities.append(entity)

    def record_action(self, action: ActionReference):
        """Record an executed action."""
        with self._lock:
            self._actions.append(action)

    def set_focused_window(self, window_title: str):
        """Track the currently focused window."""
        with self._lock:
            self._focused_window = window_title

    def set_last_command(self, command: str):
        """Store the last command for context."""
        with self._lock:
            self._last_command = command

    def resolve_pronoun(self, text: str) -> tuple[Optional[str], Optional[EntityType]]:
        """Resolve pronouns ('it', 'that', 'them') to known entities. Returns (resolved, type)."""
        text_lower = text.lower().strip()
        with self._lock:
            entities = list(self._entities)
        if not entities:
            return None, None
        if text_lower in ("it", "this", "the one"):
            most_recent = max(entities, key=lambda e: e.last_referenced)
            return most_recent.identifier, most_recent.type
        if text_lower in ("that", "the one", "there"):
            for e in reversed(entities):
                if e.reference_count > 0 or e.type == EntityType.WINDOW:
                    return e.identifier, e.type
            return None, None
        if text_lower in ("them", "those", "all of them"):
            return None, None
        if text_lower in ("the app", "the application"):
            for e in entities:
                if e.type == EntityType.APP:
                    return e.identifier, e.type
            return None, None
        if text_lower in ("the music", "the song"):
            for e in entities:
                if e.type == EntityType.MEDIA:
                    return e.identifier, e.type
            return None, None
        return None, None

    def resolve_reference(self, text: str) -> tuple[Optional[str], Optional[EntityType]]:
        """Resolve contextual references (open it again, close that, resume the music)."""
        text_lower = text.lower().strip()
        keywords_again = ["again", "reopen", "restart", "open again", "launch again"]
        keywords_close = ["close that", "close it", "close this", "shut it"]
        keywords_resume = ["resume", "continue", "play again", "resume the"]
        with self._lock:
            if any(k in text_lower for k in keywords_again):
                for e in reversed(self._entities):
                    if e.type == EntityType.APP:
                        return e.identifier, e.type
            if any(k in text_lower for k in keywords_close):
                if self._focused_window:
                    return self._focused_window, EntityType.WINDOW
                for e in reversed(self._entities):
                    if e.type == EntityType.WINDOW:
                        return e.identifier, e.type
            if any(k in text_lower for k in keywords_resume):
                for e in reversed(self._entities):
                    if e.type == EntityType.MEDIA:
                        return e.identifier, e.type
            pronoun, ptype = self.resolve_pronoun(text)
            if pronoun:
                return pronoun, ptype
        return None, None

    def resolve_switch_back(self) -> Optional[str]:
        """Resolve 'switch back' to the previously focused app."""
        with self._lock:
            for e in self._entities:
                if e.type == EntityType.APP and e.reference_count > 0:
                    return e.identifier
        return None

    def get_recent_apps(self, limit: int = 5) -> list[Entity]:
        with self._lock:
            return [e for e in self._entities if e.type == EntityType.APP][:limit]

    def get_recent_actions(self, limit: int = 5) -> list[ActionReference]:
        with self._lock:
            return list(self._actions)[-limit:]

    def get_focused_window(self) -> Optional[str]:
        with self._lock:
            return self._focused_window

    def stats(self) -> dict:
        with self._lock:
            return {
                "entity_count": len(self._entities),
                "action_count": len(self._actions),
                "focused_window": self._focused_window,
                "last_command": self._last_command[-50:],
                "recent_apps": [e.name for e in self._entities if e.type == EntityType.APP][:5],
            }


_global_resolver: ContextResolver | None = None
_resolver_lock = threading.Lock()


def get_context_resolver() -> ContextResolver:
    global _global_resolver
    with _resolver_lock:
        if _global_resolver is None:
            _global_resolver = ContextResolver()
        return _global_resolver
