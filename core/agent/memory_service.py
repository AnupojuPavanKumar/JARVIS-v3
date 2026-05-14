"""
core/agent/memory_service.py — Unified Memory Service
======================================================
Consolidates all memory subsystems into LayeredMemorySystem.
"""
from __future__ import annotations

import logging
import threading
from typing import List, Optional

from core.memory.layered_memory import get_layered_memory

log = logging.getLogger("MemoryService")

class MemoryService:
    """
    Thin façade over LayeredMemorySystem for JARVIS-v3 backward compatibility.
    """

    def __init__(self):
        self.memory = get_layered_memory()

    # ── Conversation History (Mapped to Episodic/Working) ─────────────────────────

    def record_user(self, text: str):
        self.memory.add_memory(content=f"User: {text}", layer="working", tags=["conversation", "user"])

    def record_jarvis(self, text: str):
        self.memory.add_memory(content=f"JARVIS: {text}", layer="working", tags=["conversation", "jarvis"])

    def get_recent(self, n: int = 6) -> list:
        # Mock recent history format expected by legacy code: [{"speaker": "...", "text": "..."}]
        memories = self.memory.retrieve(query_tags=["conversation"], max_results=n)
        history = []
        for m in memories:
            if m.content.startswith("User: "):
                history.append({"speaker": "user", "text": m.content[6:]})
            elif m.content.startswith("JARVIS: "):
                history.append({"speaker": "jarvis", "text": m.content[8:]})
        return history

    # ── Semantic Knowledge Graph (Mapped to Semantic) ─────────────────────────────

    def search_graph(self, query: str) -> List[str]:
        # Simple extraction of keywords as tags
        tags = [t for t in query.lower().split() if len(t) > 3]
        results = self.memory.retrieve(query_tags=tags, max_results=5)
        return [r.content for r in results if r.layer == "semantic"]

    def build_context_block(self, query: str) -> str:
        tags = [t for t in query.lower().split() if len(t) > 3]
        results = self.memory.retrieve(query_tags=tags, max_results=5)
        if not results:
            return ""
        return "[MEMORY CONTEXT]\n" + "\n".join(f"- {r.content}" for r in results)

    # ── Pattern Cache (Mapped to Procedural) ──────────────────────────────────────

    def recall_best(self, query: str) -> Optional[str]:
        tags = [t for t in query.lower().split() if len(t) > 3]
        results = self.memory.retrieve(query_tags=tags, max_results=1)
        for r in results:
            if r.layer == "procedural" and r.confidence > 0.8: return r.content
        return None

    # ── Operational Analysis (Phase 2 Entropy) ───────────────────────────────────
    
    def get_entropy_stats(self):
        return {
            "entropy": self.memory.calculate_entropy(),
            "evicted": self.memory.enforce_budgets_and_evict()
        }

    # ── Episodic Timeline (Mapped to Episodic) ────────────────────────────────────

    def record_event(self, summary: str, category: str = "general"):
        self.memory.add_memory(content=summary, layer="episodic", tags=[category, "event"])


# ── Module singleton ─────────────────────────────────────────────────────────

_instance: Optional[MemoryService] = None
_instance_lock = threading.Lock()

def get_memory_service() -> MemoryService:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MemoryService()
    return _instance
