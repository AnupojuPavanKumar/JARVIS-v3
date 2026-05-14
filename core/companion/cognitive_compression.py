# core/companion/cognitive_compression.py — JARVIS COGNITIVE COMPRESSION
"""
Compresses cognitive continuity events into narrative summaries.
Prevents memory noise accumulation by summarizing related events into
single coherent statements.

Instead of:
  "Opened VSCode" → "edited login.py" → "debugged Flask" → "searched StackOverflow"

Store:
  "Working on Flask authentication/session persistence debugging"

Wire into: CognitiveContinuity.save() + scheduled compression runs.
"""
from __future__ import annotations

import threading
import time
import json
import os
from collections import deque, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

_PATH = "memory/cognitive_narratives.json"
_MAX_SUMMARIES = 30


@dataclass
class NarrativeSummary:
    id: str
    narrative: str
    category: str
    topic: str
    first_seen: float
    last_seen: float
    event_count: int
    resolved: bool
    confidence: float
    detail_keys: list[str] = field(default_factory=list)

    def age(self) -> float:
        return time.time() - self.last_seen

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RawEvent:
    category: str
    topic: str
    detail: str
    timestamp: float
    context_keys: list[str] = field(default_factory=list)


_CATEGORY_LABELS = {
    "debugging": "debugging",
    "coding": "coding",
    "research": "researching",
    "testing": "testing",
    "setup": "setting up",
    "review": "reviewing",
    "unknown": "working on",
}


class CognitiveCompressor:
    """
    Compresses cognitive events into narrative summaries.
    Prevents the cognitive continuity from becoming event spam.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._narratives: list[NarrativeSummary] = []
        self._pending_events: deque[RawEvent] = deque(maxlen=50)
        self._last_compress = time.time()
        self._load()

    def _load(self):
        try:
            if os.path.exists(_PATH):
                with open(_PATH, "r") as f:
                    data = json.load(f)
                    self._narratives = [NarrativeSummary(**n) for n in data.get("narratives", [])]
                    print(f"[Compress] Loaded {len(self._narratives)} narrative summaries.")
        except Exception as e:
            print(f"[Compress] Load error: {e}")

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(_PATH), exist_ok=True)
                with open(_PATH, "w") as f:
                    json.dump({
                        "narratives": [n.to_dict() for n in self._narratives],
                    }, f, indent=2)
            except Exception as e:
                print(f"[Compress] Save error: {e}")

    def add_event(self, category: str, topic: str, detail: str = "",
                  context_keys: list[str] | None = None):
        """Add a raw cognitive event to be compressed later."""
        with self._lock:
            self._pending_events.append(RawEvent(
                category=category,
                topic=topic,
                detail=detail,
                timestamp=time.time(),
                context_keys=context_keys or [],
            ))
        if time.time() - self._last_compress > 120:
            self.compress()

    def compress(self):
        """Compress pending events into narrative summaries."""
        with self._lock:
            if not self._pending_events:
                return

            events = list(self._pending_events)
            self._pending_events.clear()
            self._last_compress = time.time()

            by_topic: dict[str, list[RawEvent]] = defaultdict(list)
            for e in events:
                key = self._normalize_topic(e.topic)
                if key:
                    by_topic[key].append(e)
                else:
                    by_topic[e.category].append(e)

            for topic_key, evts in by_topic.items():
                if not evts:
                    continue

                primary = evts[0]
                category = primary.category
                topic = self._coalesce_topic([e.topic for e in evts])
                label = _CATEGORY_LABELS.get(category, "working on")
                detail_keys = list({k for e in evts for k in e.context_keys if k})[:8]

                narrative = self._build_narrative(label, topic, evts, detail_keys)
                self._upsert_summary(narrative, category, topic, evts, detail_keys)

    def _normalize_topic(self, topic: str) -> str:
        if not topic:
            return ""
        topic = topic.lower().strip()
        return " ".join(topic.split()[:4])

    def _coalesce_topic(self, topics: list[str]) -> str:
        topics = [t.strip() for t in topics if t.strip()]
        if not topics:
            return ""
        if len(topics) == 1:
            return topics[0]
        first = topics[0].lower()
        for t in topics[1:]:
            if first in t.lower() or t.lower() in first:
                return max(topics, key=len)
        return topics[0]

    def _build_narrative(self, label: str, topic: str, events: list[RawEvent],
                        detail_keys: list[str]) -> str:
        count = len(events)
        detail_str = ""
        if detail_keys:
            files = [k for k in detail_keys if any(k.endswith(ext) for ext in
                        [".py", ".js", ".ts", ".json", ".md", ".txt"])]
            if files:
                detail_str = f" ({', '.join(files[:3])})"

        if count == 1:
            return f"{label.capitalize()} {topic}{detail_str}."
        elif count <= 3:
            return f"{label.capitalize()} {topic}{detail_str}."
        elif count <= 8:
            return f"{label.capitalize()} {topic} ({count} interactions){detail_str}."
        else:
            return f"Deep session: {label} {topic}{detail_str}."

    def _upsert_summary(self, narrative: str, category: str, topic: str,
                        events: list[RawEvent], detail_keys: list[str]):
        now = time.time()
        topic_norm = self._normalize_topic(topic)

        for existing in self._narratives:
            if self._normalize_topic(existing.topic) == topic_norm and existing.category == category:
                existing.narrative = narrative
                existing.last_seen = now
                existing.event_count += len(events)
                existing.detail_keys = list(set(existing.detail_keys + detail_keys))[:8]
                existing.resolved = False
                return

        summary = NarrativeSummary(
            id=f"{category}_{int(now)}",
            narrative=narrative,
            category=category,
            topic=topic,
            first_seen=now,
            last_seen=now,
            event_count=len(events),
            resolved=False,
            confidence=min(0.95, 0.5 + len(events) * 0.05),
            detail_keys=detail_keys,
        )
        self._narratives.append(summary)
        if len(self._narratives) > _MAX_SUMMARIES:
            self._narratives.sort(key=lambda n: n.last_seen)
            self._narratives = self._narratives[-_MAX_SUMMARIES:]

    def resolve_topic(self, topic: str, category: str = ""):
        with self._lock:
            topic_norm = self._normalize_topic(topic)
            for n in self._narratives:
                if self._normalize_topic(n.topic) == topic_norm:
                    if not category or n.category == category:
                        n.resolved = True

    def get_active_narratives(self, max_age_hours: float = 24) -> list[NarrativeSummary]:
        cutoff = time.time() - max_age_hours * 3600
        with self._lock:
            return [n for n in self._narratives
                    if not n.resolved and n.last_seen > cutoff]

    def get_last_narrative(self) -> Optional[NarrativeSummary]:
        with self._lock:
            active = self.get_active_narratives()
            return active[-1] if active else None

    def get_continuation_prompt(self) -> str:
        """Natural human-readable continuation from compressed narratives."""
        last = self.get_last_narrative()
        if last:
            return f"{last.narrative}"
        return ""

    def get_narrative_for_category(self, category: str) -> Optional[NarrativeSummary]:
        active = self.get_active_narratives()
        for n in reversed(active):
            if n.category == category:
                return n
        return None

    def prune_old(self, max_age_hours: float = 168):
        cutoff = time.time() - max_age_hours * 3600
        with self._lock:
            self._narratives = [n for n in self._narratives
                               if n.last_seen > cutoff or n.event_count > 10]


_instance: Optional[CognitiveCompressor] = None
_lock = threading.Lock()


def get_cognitive_compressor() -> CognitiveCompressor:
    global _instance
    with _lock:
        if _instance is None:
            _instance = CognitiveCompressor()
        return _instance