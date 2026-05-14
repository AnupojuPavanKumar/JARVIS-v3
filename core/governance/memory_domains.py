# core/governance/memory_domains.py
"""
Structured memory domains — P6.
conversational/, execution/, semantic/, episodic/, cache/, context/, tracing/.
Ownership boundaries, lifecycle policies, expiration rules.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

log = logging.getLogger("MemoryDomains")


class MemoryDomain(Enum):
    CONVERSATIONAL = auto()
    EXECUTION = auto()
    SEMANTIC = auto()
    EPISODIC = auto()
    CACHE = auto()
    CONTEXT = auto()
    TRACING = auto()


@dataclass
class MemoryPolicy:
    domain: MemoryDomain
    max_entries: int
    ttl_sec: float
    eviction_strategy: str
    persist_to_disk: bool = False


@dataclass
class MemoryEntry:
    key: str
    domain: MemoryDomain
    value: Any
    created_at: float
    last_accessed: float
    access_count: int = 0
    size_bytes: int = 0
    metadata: dict = field(default_factory=dict)


DOMAIN_POLICIES: dict[MemoryDomain, MemoryPolicy] = {
    MemoryDomain.CONVERSATIONAL: MemoryPolicy(
        domain=MemoryDomain.CONVERSATIONAL,
        max_entries=50, ttl_sec=3600.0, eviction_strategy="lru",
    ),
    MemoryDomain.EXECUTION: MemoryPolicy(
        domain=MemoryDomain.EXECUTION,
        max_entries=100, ttl_sec=300.0, eviction_strategy="lru",
    ),
    MemoryDomain.SEMANTIC: MemoryPolicy(
        domain=MemoryDomain.SEMANTIC,
        max_entries=500, ttl_sec=86400.0, eviction_strategy="lru",
    ),
    MemoryDomain.EPISODIC: MemoryPolicy(
        domain=MemoryDomain.EPISODIC,
        max_entries=200, ttl_sec=7200.0, eviction_strategy="lru",
    ),
    MemoryDomain.CACHE: MemoryPolicy(
        domain=MemoryDomain.CACHE,
        max_entries=500, ttl_sec=3600.0, eviction_strategy="lru",
    ),
    MemoryDomain.CONTEXT: MemoryPolicy(
        domain=MemoryDomain.CONTEXT,
        max_entries=20, ttl_sec=600.0, eviction_strategy="lru",
    ),
    MemoryDomain.TRACING: MemoryPolicy(
        domain=MemoryDomain.TRACING,
        max_entries=100, ttl_sec=1800.0, eviction_strategy="lru",
    ),
}


class MemoryDomains:
    """
    Structured memory domain system.
    Each domain has its own policy, max entries, TTL, eviction strategy.
    Prevents cross-domain corruption and enforces ownership boundaries.
    """

    def __init__(self):
        self._domains: dict[MemoryDomain, dict[str, MemoryEntry]] = {
            d: {} for d in MemoryDomain
        }
        self._policies: dict[MemoryDomain, MemoryPolicy] = dict(DOMAIN_POLICIES)
        self._lock = threading.RLock()
        self._total_entries: dict[MemoryDomain, int] = {d: 0 for d in MemoryDomain}
        self._access_counts: dict[str, int] = {}

    def put(self, domain: MemoryDomain, key: str, value: Any, metadata: dict | None = None):
        """Store a value in a domain."""
        policy = self._policies.get(domain)
        if not policy:
            return
        now = time.time()
        entry = MemoryEntry(
            key=key, domain=domain, value=value,
            created_at=now, last_accessed=now,
            metadata=metadata or {},
        )
        with self._lock:
            self._domains[domain][key] = entry
            self._enforce_policy_locked(domain)

    def get(self, domain: MemoryDomain, key: str) -> Any | None:
        """Retrieve a value from a domain."""
        with self._lock:
            entry = self._domains[domain].get(key)
            if not entry:
                return None
            policy = self._policies.get(domain)
            if policy and time.time() - entry.created_at > policy.ttl_sec:
                del self._domains[domain][key]
                return None
            entry.last_accessed = time.time()
            entry.access_count += 1
            self._access_counts[key] = entry.access_count
            return entry.value

    def evict(self, domain: MemoryDomain, key: str) -> bool:
        with self._lock:
            if key in self._domains[domain]:
                del self._domains[domain][key]
                return True
        return False

    def clear_domain(self, domain: MemoryDomain):
        with self._lock:
            self._domains[domain].clear()

    def _enforce_policy_locked(self, domain: MemoryDomain):
        """Enforce domain policy (max entries, TTL)."""
        policy = self._policies.get(domain)
        if not policy:
            return
        now = time.time()
        domain_entries = self._domains[domain]
        expired = [k for k, e in domain_entries.items() if now - e.created_at > policy.ttl_sec]
        for k in expired:
            del domain_entries[k]
        while len(domain_entries) > policy.max_entries:
            lru_key = min(domain_entries, key=lambda k: domain_entries[k].last_accessed)
            del domain_entries[lru_key]

    def get_domain_stats(self, domain: MemoryDomain) -> dict:
        with self._lock:
            entries = self._domains[domain]
            policy = self._policies.get(domain)
        return {
            "domain": domain.name,
            "entries": len(entries),
            "max_entries": policy.max_entries if policy else 0,
            "ttl_sec": policy.ttl_sec if policy else 0,
            "utilization": round(len(entries) / max(policy.max_entries, 1) * 100, 1) if policy else 0,
        }

    def stats(self) -> dict:
        return {
            d.name: self.get_domain_stats(d)
            for d in MemoryDomain
        }


_global_memory_domains: MemoryDomains | None = None
_md_lock = threading.Lock()


def get_memory_domains() -> MemoryDomains:
    global _global_memory_domains
    with _md_lock:
        if _global_memory_domains is None:
            _global_memory_domains = MemoryDomains()
        return _global_memory_domains
