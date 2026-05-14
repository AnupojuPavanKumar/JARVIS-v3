# core/system/runtime_explainability.py — JARVIS ADAPTIVE DECISION LOG
"""
Records every adaptive decision with full context.
Makes adaptive behavior debuggable months later.

Decision types:
  - MITIGATION       — governor applied a mitigation action
  - RECOVERY_SKIP    — recovery deferred or suppressed
  - RECOVERY_ATTEMPT — recovery initiated
  - CONFIDENCE_DROP  — domain confidence fell
  - STABILIZATION    — meta-stability dampening applied
  - REINTEGRATION    — subsystem staged reintegration step
  - PROBE_SKIPPED    — capability probe skipped due to pressure
  - EQUILIBRIUM_WARN — trajectory deteriorating
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import logging

log = logging.getLogger("RuntimeExplainability")

_MAX_LOG_ENTRIES = 2000


@dataclass
class AdaptiveDecision:
    timestamp:   float
    system:      str          # governor | recovery | meta_stability | confidence | probe
    decision:    str          # what was decided
    reason:      str          # why
    context:     dict         # snapshot at time of decision
    tags:        list[str] = field(default_factory=list)

    def to_human(self) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        ctx_str = ", ".join(f"{k}={v}" for k, v in self.context.items()) if self.context else ""
        return (f"[{ts}] [{self.system.upper()}] {self.decision} — {self.reason}"
                + (f" ({ctx_str})" if ctx_str else ""))


class RuntimeExplainability:

    _instance: Optional[RuntimeExplainability] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._log: deque[AdaptiveDecision] = deque(maxlen=_MAX_LOG_ENTRIES)

    # ── Log API ───────────────────────────────────────────────────────────────

    def log(
        self,
        system:   str,
        decision: str,
        reason:   str,
        context:  Optional[dict] = None,
        tags:     Optional[list[str]] = None,
    ):
        entry = AdaptiveDecision(
            timestamp=time.time(),
            system=system,
            decision=decision,
            reason=reason,
            context=context or {},
            tags=tags or [],
        )
        with self._lock:
            self._log.append(entry)
        log.debug(f"[Explain] {entry.to_human()}")

    # ── Shorthand helpers ─────────────────────────────────────────────────────

    def mitigation(self, action: str, level: str, context: str, reason: str):
        self.log("governor", f"MITIGATION:{action}", reason,
                 context={"pressure_level": level, "context_mode": context},
                 tags=["mitigation"])

    def recovery_skip(self, subsystem: str, reason: str, **ctx):
        self.log("recovery", f"SKIP:{subsystem}", reason,
                 context=dict(ctx), tags=["recovery", "skip"])

    def recovery_attempt(self, subsystem: str, stage: str, attempt: int):
        self.log("recovery", f"ATTEMPT:{subsystem}", f"stage={stage} attempt={attempt}",
                 context={"stage": stage, "attempt": attempt},
                 tags=["recovery", "attempt"])

    def confidence_drop(self, domain: str, from_score: float, to_score: float, reason: str):
        self.log("confidence", f"DROP:{domain}", reason,
                 context={"from": round(from_score, 1), "to": round(to_score, 1)},
                 tags=["confidence", "drop"])

    def stabilization(self, dampening: str, reason: str, duration_sec: float):
        self.log("meta_stability", f"DAMPEN:{dampening}", reason,
                 context={"duration_sec": duration_sec},
                 tags=["stabilization"])

    def probe_skipped(self, capability: str, reason: str):
        self.log("probe", f"SKIP:{capability}", reason,
                 tags=["probe", "skip"])

    def equilibrium_warn(self, trajectory: str, slope: float, churn: float):
        self.log("equilibrium", f"TRAJECTORY:{trajectory}", "Predicted instability",
                 context={"conf_slope": slope, "churn_rate": churn},
                 tags=["equilibrium", "warn"])

    # ── Query API ─────────────────────────────────────────────────────────────

    def get_decisions(
        self,
        system:  Optional[str]  = None,
        tags:    Optional[list] = None,
        since:   Optional[float]= None,
        limit:   int            = 50,
    ) -> list[AdaptiveDecision]:
        with self._lock:
            entries = list(self._log)

        if since:
            entries = [e for e in entries if e.timestamp >= since]
        if system:
            entries = [e for e in entries if e.system == system]
        if tags:
            entries = [e for e in entries if any(t in e.tags for t in tags)]

        return entries[-limit:]

    def to_human_readable(self, limit: int = 100) -> str:
        decisions = self.get_decisions(limit=limit)
        return "\n".join(d.to_human() for d in decisions)

    def get_diagnostics(self) -> dict:
        with self._lock:
            total = len(self._log)
            by_system: dict[str, int] = {}
            for e in self._log:
                by_system[e.system] = by_system.get(e.system, 0) + 1
        return {
            "total_decisions": total,
            "by_system":       by_system,
            "last_10":         [e.to_human() for e in self.get_decisions(limit=10)],
        }


_instance: Optional[RuntimeExplainability] = None
_ex_lock = threading.Lock()


def get_runtime_explainability() -> RuntimeExplainability:
    global _instance
    with _ex_lock:
        if _instance is None:
            _instance = RuntimeExplainability()
        return _instance
