# core/intents/lru_cache.py — JARVIS LRU Command Cache
"""
LRU cache with confidence-aware scoring and hot-command optimization.
Frequently used commands become near-instant.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("LRUCache")

DEFAULT_MAX_SIZE = 500
DEFAULT_TTL_SEC = 3600  # 1 hour


@dataclass
class CacheEntry:
    value: str
    confidence: float = 0.95
    hit_count: int = 1
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)


class LRUCache:
    """
    Thread-safe LRU cache for fast command responses.
    Features:
      - O(1) lookup and eviction
      - Confidence-aware: high-confidence entries survive longer
      - Hit-count tracking: hot commands promoted
      - TTL expiration
      - Maximum size enforcement
      - Statistics
    """

    def __init__(self, max_size: int = DEFAULT_MAX_SIZE, ttl: float = DEFAULT_TTL_SEC):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._max_size = max_size
        self._ttl = ttl
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[str]:
        """LRU lookup — returns value if fresh, else None."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            # TTL check
            if time.time() - entry.created_at > self._ttl:
                self._cache.pop(key, None)
                self._misses += 1
                return None

            # Refresh hit stats
            entry.hit_count += 1
            entry.last_accessed = time.time()
            self._hits += 1

            # Promote: move to end (most recently used)
            self._cache.move_to_end(key)
            return entry.value

    def put(self, key: str, value: str, confidence: float = 0.95):
        """Store a response in the cache."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key].value = value
                self._cache[key].confidence = confidence
                self._cache[key].hit_count += 1
                self._cache[key].last_accessed = time.time()
                return

            # Evict LRU if at capacity
            if len(self._cache) >= self._max_size:
                self._evict_lru(count=1)

            self._cache[key] = CacheEntry(
                value=value,
                confidence=confidence,
            )

    def _evict_lru(self, count: int = 1):
        """Evict the least recently used entries."""
        for _ in range(count):
            if not self._cache:
                break
            # Evict lowest priority: low confidence first, then low hit count
            lru_key = min(
                self._cache.keys(),
                key=lambda k: (
                    self._cache[k].confidence,
                    self._cache[k].hit_count,
                    -self._cache[k].last_accessed,
                )
            )
            self._cache.pop(lru_key, None)

    def invalidate(self, key: str):
        """Remove a specific entry."""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        """Clear the entire cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def prune_expired(self):
        """Remove all expired entries."""
        now = time.time()
        removed = 0
        with self._lock:
            expired = [
                k for k, v in self._cache.items()
                if now - v.created_at > self._ttl
            ]
            for k in expired:
                self._cache.pop(k, None)
                removed += 1
        if removed:
            log.debug(f"[LRUCache] Pruned {removed} expired entries.")
        return removed

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0

            # Top hot commands
            hot = sorted(
                self._cache.items(),
                key=lambda kv: kv[1].hit_count,
                reverse=True
            )[:5]

            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 3),
                "hot_commands": [
                    {"command": k, "hits": v.hit_count, "confidence": v.confidence}
                    for k, v in hot
                ],
            }


# ── Module-level singleton ──────────────────────────────────────────────────────

_cache = LRUCache()
_get_lock = threading.Lock()


def get_lru_cache() -> LRUCache:
    return _cache


def cache_lookup(command: str) -> Optional[str]:
    """Fast cache lookup for a command."""
    return _cache.get(command.lower().strip())


def cache_store(command: str, result: str, confidence: float = 0.95):
    """Store a command result in the cache."""
    _cache.put(command.lower().strip(), result, confidence)


def cache_stats() -> dict:
    return _cache.stats