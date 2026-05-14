import time
import math
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

from core.system.observability import get_observability

# ── Memory Models ─────────────────────────────────────────────────────────────

class MemoryEntry(BaseModel):
    entry_id: str
    content: str
    layer: str  # "working", "episodic", "semantic", "procedural"
    created_at: float = Field(default_factory=time.time)
    last_accessed: float = Field(default_factory=time.time)
    access_count: int = 1
    confidence: float = 1.0
    tags: List[str] = Field(default_factory=list)

class LayeredMemorySystem:
    """
    Phase 4: Memory Reconstruction
    Segmented memory system with Working, Episodic, Semantic, and Procedural layers.
    Implements relevance scoring, temporal decay, and stale memory filtering.
    """
    def __init__(self):
        self._working: List[MemoryEntry] = []       # Active task context
        self._episodic: List[MemoryEntry] = []      # Historical interactions
        self._semantic: List[MemoryEntry] = []      # Stable facts
        self._procedural: List[MemoryEntry] = []    # Successful workflows
        
        # Retention Budgets (Max entry limits per layer)
        self._budgets = {
            "working": 50,
            "episodic": 500,
            "procedural": 200,
            "semantic": 1000
        }
        
    def calculate_entropy(self) -> Dict[str, float]:
        """
        Phase 2: Memory Entropy Analysis
        Measures the degradation and staleness of each memory layer.
        Entropy = (Stale Entries / Total Entries) + (Duplicate Decay)
        """
        now = time.time()
        entropy = {}
        for layer in ["working", "episodic", "procedural", "semantic"]:
            entries = getattr(self, f"_{layer}")
            if not entries:
                entropy[layer] = 0.0
                continue
                
            stale_count = 0
            for mem in entries:
                age_hours = (now - mem.last_accessed) / 3600.0
                if mem.layer == "working" and age_hours > 2.0: stale_count += 1
                if mem.layer == "episodic" and age_hours > 72.0: stale_count += 1
                
            entropy[layer] = round(stale_count / len(entries), 3)
        return entropy

    def enforce_budgets_and_evict(self) -> dict:
        """
        Phase 2: Retention budgeting and stale context eviction.
        Removes the oldest, least-accessed items when a budget is exceeded.
        """
        evicted_counts = {}
        now = time.time()
        
        for layer, limit in self._budgets.items():
            entries = getattr(self, f"_{layer}")
            if len(entries) > limit:
                # Sort by a combination of last accessed and access count
                entries.sort(key=lambda m: (m.last_accessed + (m.access_count * 3600)))
                
                # Evict the bottom N entries
                excess = len(entries) - limit
                setattr(self, f"_{layer}", entries[excess:])
                evicted_counts[layer] = excess
            else:
                evicted_counts[layer] = 0
                
        return evicted_counts

    def add_memory(self, content: str, layer: str, confidence: float = 1.0, tags: List[str] = None):
        """Adds a memory to the specified layer with duplicate suppression."""
        if not tags:
            tags = []
            
        # Duplicate suppression
        if self._is_duplicate(content, layer):
            return
            
        entry = MemoryEntry(
            entry_id=f"mem_{int(time.time()*1000)}",
            content=content,
            layer=layer,
            confidence=confidence,
            tags=tags
        )
        
        if layer == "working":
            self._working.append(entry)
        elif layer == "episodic":
            self._episodic.append(entry)
        elif layer == "semantic":
            self._semantic.append(entry)
        elif layer == "procedural":
            self._procedural.append(entry)

    def _is_duplicate(self, content: str, layer: str) -> bool:
        """Duplicate suppression based on case-insensitive content matching."""
        norm_content = content.strip().lower()
        target_list = getattr(self, f"_{layer}", [])
        for entry in target_list:
            if entry.content.strip().lower() == norm_content:
                entry.access_count += 1
                entry.last_accessed = time.time()
                return True
        return False

    def retrieve(self, query_tags: List[str], max_results: int = 5) -> List[MemoryEntry]:
        """
        Retrieves memory entries across all layers, applying:
        - relevance scoring (tag matching)
        - temporal decay (time since last access)
        - confidence weighting
        """
        all_memories = self._working + self._episodic + self._semantic + self._procedural
        scored_memories = []
        
        now = time.time()
        
        for mem in all_memories:
            # 1. Relevance Score: overlap in tags
            relevance = len(set(mem.tags).intersection(set(query_tags)))
            if relevance == 0 and len(query_tags) > 0:
                continue # No tag overlap
                
            # 2. Temporal Decay: half-life function based on layer
            age_hours = (now - mem.last_accessed) / 3600.0
            
            # Working memory decays rapidly; Semantic memory decays slowly
            half_life_hours = {
                "working": 2.0,
                "episodic": 72.0,   # 3 days
                "procedural": 720.0, # 30 days
                "semantic": 8760.0   # 1 year
            }.get(mem.layer, 24.0)
            
            decay_factor = math.pow(0.5, age_hours / half_life_hours)
            
            # 3. Frequency boost
            frequency_boost = min(1.5, 1.0 + (math.log10(mem.access_count) * 0.1))
            
            # Final Score Calculation
            final_score = (relevance * mem.confidence * decay_factor * frequency_boost)
            
            # Filter stale memory (score too low)
            if final_score > 0.1:
                scored_memories.append((final_score, mem))
                
        # Sort by score descending
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        
        # Update access times for retrieved entries
        results = []
        for score, mem in scored_memories[:max_results]:
            mem.last_accessed = now
            mem.access_count += 1
            results.append(mem)
            
        get_observability().log_memory_retrieval(
            query=str(query_tags),
            retrieved_tags=query_tags,
            rationale=f"Retrieved {len(results)} memory items based on tag relevance, frequency, and temporal decay."
        )
            
        return results

    def clear_working_memory(self):
        """Purges working memory at the end of a task loop to prevent context pollution."""
        self._working.clear()

# ── Singleton ──────────────────────────────────────────────────────────────────
_layered_memory_instance: Optional[LayeredMemorySystem] = None

def get_layered_memory() -> LayeredMemorySystem:
    global _layered_memory_instance
    if _layered_memory_instance is None:
        _layered_memory_instance = LayeredMemorySystem()
    return _layered_memory_instance
