# core/companion/layered_memory.py — JARVIS LAYERED COGNITIVE MEMORY
"""
Multi-resolution memory: keeps memory lightweight WITHOUT losing recoverability.

Layers:
  L1 — Narrative summary: human-readable one-liner (compressed, persistent)
  L2 — Operational summary: what workflows were active, key decisions made
  L3 — Recoverable detail: file names, function names, error messages
  L4 — Raw event history: full command/result pairs (short retention, pruned)

Each layer has its own TTL and access cost. L1 is always loaded.
Deeper layers loaded on demand ("tell me more about that session").
"""
from __future__ import annotations

import threading
import time
import json
import os
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal

_L1_PATH = "memory/l1_narratives.json"
_L2_PATH = "memory/l2_operational.json"
_L3_PATH = "memory/l3_detail.json"
_L4_PATH = "memory/l4_raw.json"
_MAX_L3 = 200
_MAX_L4 = 100


@dataclass
class L1Narrative:
    id: str
    summary: str
    category: str
    topic: str
    confidence: float
    created_at: float
    last_recalled: float = 0.0
    recall_count: int = 0
    resolved: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class L2Operational:
    session_id: str
    workflows: list[str]
    key_decisions: list[str]
    tools_used: list[str]
    started_at: float
    ended_at: float = 0.0
    task_count: int = 0
    success_count: int = 0

    def duration_min(self) -> float:
        end = self.ended_at or time.time()
        return (end - self.started_at) / 60

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class L3Detail:
    key: str
    value: str
    category: str
    created_at: float
    last_accessed: float = 0.0
    access_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class L4RawEvent:
    command: str
    result: str
    success: bool
    timestamp: float
    category: str = ""
    intent: str = ""

    def age_h(self) -> float:
        return (time.time() - self.timestamp) / 3600

    def to_dict(self) -> dict:
        return asdict(self)


class LayeredMemory:
    """
    Four-layer memory with progressive detail and access cost.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._l1: list[L1Narrative] = []
        self._l2: list[L2Operational] = []
        self._l3: deque[L3Detail] = deque(maxlen=_MAX_L3)
        self._l4: deque[L4RawEvent] = deque(maxlen=_MAX_L4)
        self._load()

    def _load(self):
        for path, cls, store, key in [
            (_L1_PATH, L1Narrative, self._l1, "narratives"),
            (_L2_PATH, L2Operational, self._l2, "sessions"),
        ]:
            try:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        data = json.load(f)
                        for n in data.get(key, []):
                            store.append(cls(**n))
            except Exception as e:
                print(f"[LayeredMem] Load error {path}: {e}")

        for path, cls, store in [
            (_L3_PATH, L3Detail, self._l3),
            (_L4_PATH, L4RawEvent, self._l4),
        ]:
            try:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        for n in json.load(f):
                            store.append(cls(**n))
            except Exception:
                pass

    def save(self):
        with self._lock:
            try:
                os.makedirs("memory", exist_ok=True)
                with open(_L1_PATH, "w") as f:
                    json.dump({"narratives": [n.to_dict() for n in self._l1]}, f, indent=2)
                with open(_L2_PATH, "w") as f:
                    json.dump({"sessions": [s.to_dict() for s in self._l2]}, f, indent=2)
                with open(_L3_PATH, "w") as f:
                    json.dump([d.to_dict() for d in self._l3], f, indent=2)
                with open(_L4_PATH, "w") as f:
                    json.dump([e.to_dict() for e in self._l4], f, indent=2)
            except Exception as e:
                print(f"[LayeredMem] Save error: {e}")

    def push_raw(self, command: str, result: str, success: bool,
                 category: str = "", intent: str = ""):
        with self._lock:
            self._l4.append(L4RawEvent(
                command=command, result=result, success=success,
                timestamp=time.time(), category=category, intent=intent,
            ))

    def push_l3(self, key: str, value: str, category: str = ""):
        with self._lock:
            self._l3.append(L3Detail(
                key=key, value=value, category=category,
                created_at=time.time(),
            ))

    def push_l2(self, session: L2Operational):
        with self._lock:
            self._l2.append(session)
            if len(self._l2) > 50:
                self._l2 = self._l2[-50:]

    def push_l1(self, summary: str, category: str, topic: str, confidence: float = 0.8):
        with self._lock:
            for existing in self._l1:
                if existing.topic == topic and existing.category == category:
                    existing.summary = summary
                    existing.last_recalled = time.time()
                    return
            self._l1.append(L1Narrative(
                id=f"{category}_{int(time.time())}",
                summary=summary, category=category, topic=topic,
                confidence=confidence, created_at=time.time(),
            ))
            if len(self._l1) > 40:
                self._l1.sort(key=lambda n: n.last_recalled)
                self._l1 = self._l1[-40:]

    def get_l1(self, category: str = "", limit: int = 5) -> list[L1Narrative]:
        with self._lock:
            narratives = self._l1
            if category:
                narratives = [n for n in narratives if n.category == category]
            return narratives[-limit:]

    def get_l2(self, session_id: str = "") -> Optional[L2Operational]:
        with self._lock:
            if session_id:
                for s in reversed(self._l2):
                    if s.session_id == session_id:
                        return s
            return self._l2[-1] if self._l2 else None

    def get_l3(self, key: str = "", category: str = "") -> list[L3Detail]:
        with self._lock:
            results = list(self._l3)
            if key:
                results = [d for d in results if key.lower() in d.key.lower()]
            if category:
                results = [d for d in results if d.category == category]
            return results

    def recall_l3(self, key: str) -> Optional[str]:
        with self._lock:
            for d in reversed(self._l3):
                if key.lower() in d.key.lower():
                    d.access_count += 1
                    d.last_accessed = time.time()
                    return d.value
        return None

    def get_l4(self, limit: int = 20) -> list[L4RawEvent]:
        with self._lock:
            return list(self._l4)[-limit:]

    def prune_l4(self, max_age_h: float = 6):
        cutoff = time.time() - max_age_h * 3600
        with self._lock:
            self._l4 = deque([e for e in self._l4 if e.timestamp > cutoff], maxlen=_MAX_L4)

    def what_were_we_doing(self) -> str:
        narratives = self.get_l1(limit=1)
        if narratives:
            return f"We were {narratives[-1].summary}"
        return "No recent work tracked."


_instance: Optional[LayeredMemory] = None
_lock = threading.Lock()


def get_layered_memory() -> LayeredMemory:
    global _instance
    with _lock:
        if _instance is None:
            _instance = LayeredMemory()
        return _instance