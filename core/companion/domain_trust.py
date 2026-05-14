# core/companion/domain_trust.py — JARVIS DOMAIN-SPECIFIC TRUST
"""
Per-domain trust scores instead of one global trust number.

Tracks:
  - workspace_restore  (offering workflow restoration)
  - browser_actions   (opening/closing tabs, navigation)
  - file_operations   (creating, editing, deleting files)
  - system_changes    (settings, registry, permissions)
  - proactive_suggestions
  - automation_execution

Each domain earns trust independently based on acceptance/rejection patterns.
"""
from __future__ import annotations

import threading
import time
import os
import json
from dataclasses import dataclass, asdict
from typing import Optional

_PATH = "memory/domain_trust.json"


@dataclass
class DomainScore:
    domain: str
    accept_count: int = 0
    reject_count: int = 0
    override_count: int = 0
    trust: float = 0.5
    last_update: float = 0.0

    def acceptance_rate(self) -> float:
        total = self.accept_count + self.reject_count
        if total == 0:
            return 0.5
        return self.accept_count / total

    def to_dict(self) -> dict:
        return asdict(self)


class DomainTrust:
    """
    Per-domain trust. Low trust in system_changes means asking for confirmation
    even when workspace_restore trust is high.
    """

    DOMAINS = [
        "workspace_restore",
        "browser_actions",
        "file_operations",
        "system_changes",
        "proactive_suggestions",
        "automation_execution",
    ]

    def __init__(self):
        self._lock = threading.RLock()
        self._scores: dict[str, DomainScore] = {d: DomainScore(domain=d) for d in self.DOMAINS}
        self._load()

    def _load(self):
        try:
            if os.path.exists(_PATH):
                with open(_PATH, "r") as f:
                    data = json.load(f)
                    for d in self.DOMAINS:
                        if d in data:
                            s = DomainScore(**data[d])
                            self._scores[d] = s
                    print(f"[DomainTrust] Loaded {len(data)} domain scores.")
        except Exception as e:
            print(f"[DomainTrust] Load error: {e}")

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(_PATH), exist_ok=True)
                with open(_PATH, "w") as f:
                    json.dump({d: s.to_dict() for d, s in self._scores.items()}, f, indent=2)
            except Exception as e:
                print(f"[DomainTrust] Save error: {e}")

    def _recompute(self, score: DomainScore):
        total = score.accept_count + score.reject_count
        if total > 0:
            rate = score.accept_count / total
            score.trust = 0.3 + rate * 0.5
        score.trust -= score.override_count * 0.05
        score.trust = max(0.1, min(1.0, score.trust))
        score.last_update = time.time()

    def record_accept(self, domain: str):
        with self._lock:
            if domain not in self._scores:
                self._scores[domain] = DomainScore(domain=domain)
            s = self._scores[domain]
            s.accept_count += 1
            self._recompute(s)

    def record_reject(self, domain: str):
        with self._lock:
            if domain not in self._scores:
                self._scores[domain] = DomainScore(domain=domain)
            s = self._scores[domain]
            s.reject_count += 1
            self._recompute(s)

    def record_override(self, domain: str):
        with self._lock:
            if domain not in self._scores:
                self._scores[domain] = DomainScore(domain=domain)
            s = self._scores[domain]
            s.override_count += 1
            self._recompute(s)

    def get_trust(self, domain: str) -> float:
        with self._lock:
            return self._scores.get(domain, DomainScore(domain=domain)).trust

    def should_confirm(self, domain: str) -> bool:
        return self.get_trust(domain) < 0.5

    def should_auto_act(self, domain: str) -> bool:
        return self.get_trust(domain) > 0.7

    def get_all(self) -> dict[str, float]:
        with self._lock:
            return {d: s.trust for d, s in self._scores.items()}

    def get_weakest_domain(self) -> str | None:
        with self._lock:
            weakest = min(self._scores.items(), key=lambda x: x[1].trust)
            return weakest[0] if weakest[1].trust < 0.4 else None


_instance: Optional[DomainTrust] = None
_lock = threading.Lock()


def get_domain_trust() -> DomainTrust:
    global _instance
    with _lock:
        if _instance is None:
            _instance = DomainTrust()
        return _instance