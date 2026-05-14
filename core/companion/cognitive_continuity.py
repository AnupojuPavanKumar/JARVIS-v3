# core/companion/cognitive_continuity.py — JARVIS COGNITIVE CONTINUITY
"""
Tracks WHAT the user was mentally doing — not just operational state.

Remembers:
  - active debugging topics (with error context)
  - recent coding goals (with file/function context)
  - interrupted workflows (with state context)
  - active research topics
  - unresolved problems
  - recent assistant actions (what JARVIS did for the user)

This is mental context, not just technical state. It answers:
  "You were debugging Flask session persistence."
  "We were setting up the authentication flow."
  "You were researching Ollama model deployment."

vs:
  "coding session restored."

Wire into: jarvis_brain post-processing + checkpoint save/load.
"""
from __future__ import annotations

import threading
import time
import json
import os
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional

_PATH = "memory/cognitive_context.json"
_MAX_ITEMS = 20
_MAX_ACTIONS = 30


@dataclass
class CognitiveItem:
    category: str
    topic: str
    detail: str
    timestamp: float
    confidence: float
    resolved: bool = False
    source_command: str = ""
    context_keys: list[str] = field(default_factory=list)

    def age(self) -> float:
        return time.time() - self.timestamp

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AssistantAction:
    action: str
    target: str
    timestamp: float
    command: str
    success: bool = True
    impact: str = ""
    detail: str = ""

    def age(self) -> float:
        return time.time() - self.timestamp

    def to_dict(self) -> dict:
        return asdict(self)


class CognitiveContinuity:
    """
    Tracks the user's mental state — what they're working on, thinking about,
    trying to solve. Complements operational checkpointing with cognitive context.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._items: deque[CognitiveItem] = deque(maxlen=_MAX_ITEMS)
        self._actions: deque[AssistantAction] = deque(maxlen=_MAX_ACTIONS)
        self._unresolved_topics: list[str] = []
        self._dirty = False
        self._load()

    def _load(self):
        try:
            if os.path.exists(_PATH):
                with open(_PATH, "r") as f:
                    data = json.load(f)
                    for item_data in data.get("items", []):
                        self._items.append(CognitiveItem(**item_data))
                    for act_data in data.get("actions", []):
                        self._actions.append(AssistantAction(**act_data))
                    self._unresolved_topics = data.get("unresolved", [])
                    print(f"[Cognitive] Loaded {len(self._items)} cognitive items, "
                          f"{len(self._actions)} actions.")
        except Exception as e:
            print(f"[Cognitive] Load error: {e}")

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(_PATH), exist_ok=True)
                data = {
                    "items": [i.to_dict() for i in self._items],
                    "actions": [a.to_dict() for a in self._actions],
                    "unresolved": self._unresolved_topics,
                }
                with open(_PATH, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"[Cognitive] Save error: {e}")

    def track_command(self, command: str, intent: str = ""):
        """Examine a command and update cognitive context accordingly."""
        low = command.lower()

        topics = self._detect_topics(low, command)
        for topic in topics:
            self._add_item(topic)

        if intent:
            self._detect_workflow_change(intent, command)

    def _detect_topics(self, low: str, original: str) -> list[CognitiveItem]:
        """Infer cognitive context from command phrasing."""
        items = []

        if any(k in low for k in ["debug", "fix", "error", "exception", "traceback", "crash", "bug"]):
            items.append(CognitiveItem(
                category="debugging",
                topic=self._extract_topic(low, ["debug", "fix", "error", "crash"]),
                detail=self._extract_detail(original),
                timestamp=time.time(),
                confidence=0.8,
                source_command=original,
                context_keys=self._extract_context_keys(low),
            ))

        if any(k in low for k in ["implement", "build", "create", "make", "add", "develop"]):
            if any(k in low for k in ["function", "class", "module", "api", "endpoint", "route", "auth", "login", "authenticate"]):
                items.append(CognitiveItem(
                    category="coding",
                    topic=self._extract_topic(low, ["implement", "build", "create", "add"]),
                    detail=self._extract_detail(original),
                    timestamp=time.time(),
                    confidence=0.75,
                    source_command=original,
                    context_keys=self._extract_context_keys(low),
                ))

        if any(k in low for k in ["research", "find out", "look up", "understand", "how does", "what is", "explain"]):
            items.append(CognitiveItem(
                category="research",
                topic=self._extract_topic(low, ["research", "find out", "look up", "understand"]),
                detail=self._extract_detail(original),
                timestamp=time.time(),
                confidence=0.7,
                source_command=original,
            ))

        if any(k in low for k in ["test", "run tests", "pytest", "unit test"]):
            items.append(CognitiveItem(
                category="testing",
                topic=self._extract_topic(low, ["test"]),
                detail=self._extract_detail(original),
                timestamp=time.time(),
                confidence=0.8,
                source_command=original,
            ))

        if any(k in low for k in ["deploy", "setup", "configure", "install", "set up"]):
            items.append(CognitiveItem(
                category="setup",
                topic=self._extract_topic(low, ["deploy", "setup", "configure", "install"]),
                detail=self._extract_detail(original),
                timestamp=time.time(),
                confidence=0.8,
                source_command=original,
            ))

        if any(k in low for k in ["review", "check", "analyse", "analyze"]):
            if any(k in low for k in ["code", "file", "script", "performance"]):
                items.append(CognitiveItem(
                    category="review",
                    topic=self._extract_topic(low, ["review", "check", "analyze"]),
                    detail=self._extract_detail(original),
                    timestamp=time.time(),
                    confidence=0.7,
                    source_command=original,
                ))

        return items

    def _extract_topic(self, low: str, keywords: list[str]) -> str:
        for kw in keywords:
            if kw in low:
                idx = low.index(kw)
                rest = low[idx + len(kw):].strip().strip(".,!?")
                if rest:
                    words = rest.split()
                    return " ".join(words[:6]).strip("'\"").strip()
        return low[:40].strip()

    def _extract_detail(self, original: str) -> str:
        if ":" in original:
            return original[original.index(":"):].strip()[:100]
        return original[:80].strip()

    def _extract_context_keys(self, low: str) -> list[str]:
        keys = []
        for token in low.split():
            if any(ext in token for ext in [".py", ".json", ".js", ".ts", ".md", ".txt"]):
                keys.append(token.strip(".,!?"))
            elif "/" in token or "\\" in token:
                keys.append(token)
        return keys[:5]

    def _detect_workflow_change(self, intent: str, command: str):
        pass

    def _add_item(self, item: CognitiveItem):
        with self._lock:
            is_dup = any(
                i.topic == item.topic and i.category == item.category
                and i.age() < 300
                for i in self._items
            )
            if not is_dup:
                self._items.append(item)
                if not item.resolved:
                    self._unresolved_topics.append(f"{item.category}:{item.topic}")
                self._dirty = True

    def track_action(self, action: str, target: str, command: str,
                     success: bool = True, detail: str = "", impact: str = ""):
        """Record what JARVIS did for the user."""
        act = AssistantAction(
            action=action, target=target, timestamp=time.time(),
            command=command, success=success, detail=detail, impact=impact,
        )
        with self._lock:
            self._actions.append(act)
            self._dirty = True

    def resolve_topic(self, topic: str, category: str = ""):
        """Mark a cognitive topic as resolved."""
        with self._lock:
            for item in self._items:
                if item.topic == topic and (not category or item.category == category):
                    item.resolved = True
                    self._dirty = True
            self._unresolved_topics = [
                t for t in self._unresolved_topics
                if not t.startswith(f"{category}:{topic}")
            ]

    def get_unresolved(self) -> list[CognitiveItem]:
        with self._lock:
            return [i for i in self._items if not i.resolved and i.age() < 7200]

    def get_last_topic(self) -> Optional[CognitiveItem]:
        with self._lock:
            unresolved = [i for i in self._items if not i.resolved]
            return unresolved[-1] if unresolved else None

    def get_last_action(self) -> Optional[AssistantAction]:
        with self._lock:
            return self._actions[-1] if self._actions else None

    def get_recent_actions(self, limit: int = 5) -> list[AssistantAction]:
        with self._lock:
            return list(self._actions)[-limit:]

    def get_continuation_prompt(self) -> str:
        """Generate a natural human-readable continuation prompt."""
        last = self.get_last_topic()
        actions = self.get_recent_actions(3)

        if last and last.category == "debugging":
            detail = f" debugging {last.topic}" if last.topic else ""
            return f"You were{detail} before shutdown."
        elif last and last.category == "coding":
            detail = f" implementing {last.topic}" if last.topic else ""
            return f"You were{detail}."
        elif last and last.category == "research":
            detail = f" researching {last.topic}" if last.topic else ""
            return f"You were{detail}."
        elif last and last.category == "setup":
            detail = f" setting up {last.topic}" if last.topic else ""
            return f"You were{detail}."
        elif last:
            return f"You were working on: {last.topic}."

        if actions:
            last_act = actions[-1]
            if last_act.impact:
                return f"Last, I {last_act.action}ed {last_act.target} ({last_act.impact})."
            return f"Last, I {last_act.action}ed {last_act.target}."

        return ""

    def get_narrative_summary(self) -> str:
        """One-paragraph narrative of what was happening."""
        unresolved = self.get_unresolved()
        actions = self.get_recent_actions(5)

        if not unresolved and not actions:
            return "No active work tracked."

        parts = []
        if unresolved:
            by_cat: dict[str, list] = {}
            for item in unresolved:
                by_cat.setdefault(item.category, []).append(item.topic)
            for cat, topics in by_cat.items():
                parts.append(f"Working on: {', '.join(topics[:3])}")

        if actions:
            act_parts = []
            for a in actions[-3:]:
                if a.action == "open":
                    act_parts.append(f"opened {a.target}")
                elif a.action == "search":
                    act_parts.append(f"searched for {a.target}")
                elif a.action == "build":
                    act_parts.append(f"built {a.target}")
                elif a.action == "fix":
                    act_parts.append(f"fixed {a.target}")
                elif a.action == "analyze":
                    act_parts.append(f"analyzed {a.target}")
                else:
                    act_parts.append(f"{a.action}ed {a.target}")
            if act_parts:
                parts.append("Recent: " + ", ".join(act_parts))

        return ". ".join(parts) + "."

    def what_were_we_doing(self) -> str:
        """Answer the user's 'what were we doing' question."""
        summary = self.get_narrative_summary()
        last = self.get_last_topic()

        if last:
            detail = f" ({last.detail[:60]})" if len(last.detail) > 10 else ""
            return f"We were {last.category}ing {last.topic}{detail}"
        elif summary != "No active work tracked.":
            return summary
        return "We haven't been working on anything specific that I can recall."


_instance: Optional[CognitiveContinuity] = None
_lock = threading.Lock()


def get_cognitive_continuity() -> CognitiveContinuity:
    global _instance
    with _lock:
        if _instance is None:
            _instance = CognitiveContinuity()
        return _instance