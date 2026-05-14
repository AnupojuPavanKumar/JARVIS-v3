# core/system/domain_confidence.py — JARVIS DOMAIN CONFIDENCE MODEL
"""
Per-domain confidence replaces the scalar model.

Domains:
  VOICE      — wake word, STT, TTS, mic
  AI         — Ollama inference, model warmup
  RUNTIME    — watchdog, governor, recovery
  MEMORY     — checkpoint, session, layered memory
  AUTOMATION — suggestions, workspace, telemetry

Each domain has an independent score (0-100) and level.
Behavior suppression is domain-targeted, not global.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("DomainConfidence")


class Domain(Enum):
    VOICE      = "voice"
    AI         = "ai"
    RUNTIME    = "runtime"
    MEMORY     = "memory"
    AUTOMATION = "automation"


class DomainLevel(Enum):
    CONFIDENT  = 3
    CAUTIOUS   = 2
    UNCERTAIN  = 1
    LOW        = 0


class OverrideState(Enum):
    """Hard-failure states that bypass the confidence floor."""
    NONE               = "none"
    HARD_FAILED        = "hard_failed"         # unrecoverable hardware/OS failure
    RECOVERY_EXHAUSTED = "recovery_exhausted"  # budget + quarantine both expired
    QUARANTINED_FATAL  = "quarantined_fatal"   # quarantine with no viable recovery path


# Subsystems that belong to each domain
_DOMAIN_SUBSYSTEMS: dict[Domain, list[str]] = {
    Domain.VOICE: [
        "voice_tts", "voice_stt", "wake_word",
        "voice_worker", "voice_interrupt", "tts",
    ],
    Domain.AI: [
        "ollama_manager", "model_prewarmer",
        "ollama_inference", "memory_service",
    ],
    Domain.RUNTIME: [
        "watchdog", "pressure_governor", "recovery_orchestrator",
        "runtime_confidence", "capability_validator", "hardware_sentinel",
    ],
    Domain.MEMORY: [
        "checkpoint_manager", "session_continuity", "layered_memory",
        "cognitive_continuity", "cognitive_compression",
        "fatigue_model", "behavior_drift",
    ],
    Domain.AUTOMATION: [
        "suggestion_engine", "workspace_observer",
        "telemetry", "graceful_degradation",
    ],
}

# Capability probes belonging to each domain
_DOMAIN_PROBES: dict[Domain, list[str]] = {
    Domain.VOICE:      ["tts"],
    Domain.AI:         ["ollama", "ollama_inference"],
    Domain.RUNTIME:    [],
    Domain.MEMORY:     [],
    Domain.AUTOMATION: [],
}

# Minimum score to preserve baseline behaviors (confidence floor)
_FLOOR_SCORE = 20.0


@dataclass
class DomainSnapshot:
    domain:     Domain
    score:      float
    level:      DomainLevel
    timestamp:  float
    ready:      int
    degraded:   int
    failed:     int


@dataclass
class DomainState:
    domain:  Domain
    score:   float = 100.0
    level:   DomainLevel = DomainLevel.CONFIDENT
    history: deque = field(default_factory=lambda: deque(maxlen=60))


class DomainConfidence:
    """
    Per-domain confidence tracker.
    Scores each domain from its subsystem readiness states.
    """

    _instance: Optional[DomainConfidence] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._domains: dict[Domain, DomainState] = {
            d: DomainState(domain=d) for d in Domain
        }
        self._overrides: dict[Domain, OverrideState] = {
            d: OverrideState.NONE for d in Domain
        }
        self._callbacks: list[Callable[[Domain, DomainLevel, float], None]] = []
        self._running   = False
        self._stop_evt  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._interval  = 30.0

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="DomainConfidence"
        )
        self._thread.start()
        log.info("[DomainConfidence] Started.")

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def on_change(self, cb: Callable[[Domain, DomainLevel, float], None]):
        self._callbacks.append(cb)

    # ── Scoring ──────────────────────────────────────────────────────────────

    def _loop(self):
        while self._running and not self._stop_evt.is_set():
            try:
                self._compute_all()
            except Exception as e:
                log.debug(f"[DomainConfidence] Error: {e}")
            self._stop_evt.wait(timeout=self._interval)

    def _compute_all(self):
        try:
            from core.system.readiness_state import get_readiness_tracker
            rt = get_readiness_tracker()
        except Exception:
            return

        for domain, state in self._domains.items():
            subsystems = _DOMAIN_SUBSYSTEMS.get(domain, [])
            if not subsystems:
                continue

            ready = degraded = failed = 0
            for sub in subsystems:
                s = rt.get_state(sub)
                if s is None:
                    continue
                s_name = s.name if hasattr(s, 'name') else str(s)
                if   s_name == "READY":    ready    += 1
                elif s_name == "DEGRADED": degraded += 1
                elif s_name == "FAILED":   failed   += 1

            total = max(1, ready + degraded + failed)
            prev_level = state.level

            # Check override state — hard failures bypass floor
            override = self._overrides.get(domain, OverrideState.NONE)
            if override != OverrideState.NONE:
                score = 0.0   # floor does NOT apply
                level = DomainLevel.LOW
            else:
                score = max(
                    _FLOOR_SCORE,  # confidence floor while recovery is viable
                    (ready * 100 + degraded * 50) / total
                )
                if domain != Domain.RUNTIME:
                    score = self._apply_pressure_penalty(score)
                if   score >= 80: level = DomainLevel.CONFIDENT
                elif score >= 60: level = DomainLevel.CAUTIOUS
                elif score >= 40: level = DomainLevel.UNCERTAIN
                else:             level = DomainLevel.LOW

            with self._lock:
                state.score = round(score, 1)
                state.level = level
                state.history.append(DomainSnapshot(
                    domain=domain, score=score, level=level,
                    timestamp=time.time(),
                    ready=ready, degraded=degraded, failed=failed,
                ))

            if level != prev_level:
                log.info(f"[DomainConfidence] {domain.value}: "
                         f"{prev_level.name} → {level.name} (score={score:.1f})"
                         + (f" [OVERRIDE:{override.value}]" if override != OverrideState.NONE else ""))
                for cb in self._callbacks:
                    try:
                        cb(domain, level, score)
                    except Exception:
                        pass

    def _apply_pressure_penalty(self, score: float) -> float:
        try:
            from core.system.health_pressure_governor import (
                get_health_pressure_governor, PressureLevel
            )
            level = get_health_pressure_governor().level
            penalty = {
                PressureLevel.NOMINAL:    0,
                PressureLevel.ELEVATED:   5,
                PressureLevel.HIGH:      15,
                PressureLevel.CRITICAL:  25,
                PressureLevel.EMERGENCY: 40,
            }.get(level, 0)
            return max(_FLOOR_SCORE, score - penalty)
        except Exception:
            return score

    # ── Public API ────────────────────────────────────────────────────────────

    def get_score(self, domain: Domain) -> float:
        with self._lock:
            return self._domains[domain].score

    def get_level(self, domain: Domain) -> DomainLevel:
        with self._lock:
            return self._domains[domain].level

    def set_override(self, domain: Domain, state: OverrideState):
        """Mark a domain as hard-failed. Bypasses confidence floor."""
        with self._lock:
            prev = self._overrides.get(domain, OverrideState.NONE)
            self._overrides[domain] = state
        if state != prev:
            log.error(f"[DomainConfidence] Override set: {domain.value} → {state.value}")

    def clear_override(self, domain: Domain):
        """Clear a hard-failure override (e.g. after manual recovery)."""
        with self._lock:
            self._overrides[domain] = OverrideState.NONE
        log.info(f"[DomainConfidence] Override cleared for {domain.value}")

    def get_override(self, domain: Domain) -> OverrideState:
        with self._lock:
            return self._overrides.get(domain, OverrideState.NONE)

    def is_domain_healthy(self, domain: Domain) -> bool:
        return self.get_level(domain) >= DomainLevel.CAUTIOUS

    def should_suppress(self, domain: Domain) -> bool:
        return self.get_level(domain) <= DomainLevel.UNCERTAIN

    def should_disable(self, domain: Domain) -> bool:
        return self.get_level(domain) == DomainLevel.LOW

    # Specific helpers used by governor / recovery
    def voice_ok(self)      -> bool: return self.is_domain_healthy(Domain.VOICE)
    def ai_ok(self)         -> bool: return self.is_domain_healthy(Domain.AI)
    def automation_ok(self) -> bool: return self.is_domain_healthy(Domain.AUTOMATION)
    def memory_ok(self)     -> bool: return self.is_domain_healthy(Domain.MEMORY)
    def runtime_ok(self)    -> bool: return self.is_domain_healthy(Domain.RUNTIME)

    def get_all_levels(self) -> dict[str, str]:
        with self._lock:
            return {d.value: s.level.name for d, s in self._domains.items()}

    def get_all_scores(self) -> dict[str, float]:
        with self._lock:
            return {d.value: s.score for d, s in self._domains.items()}

    def get_diagnostics(self) -> dict:
        with self._lock:
            overrides = {d.value: s.value for d, s in self._overrides.items()
                         if s != OverrideState.NONE}
        return {
            "scores":    self.get_all_scores(),
            "levels":    self.get_all_levels(),
            "floor":     _FLOOR_SCORE,
            "overrides": overrides,
        }


_instance: Optional[DomainConfidence] = None
_dc_lock = threading.Lock()


def get_domain_confidence() -> DomainConfidence:
    global _instance
    with _dc_lock:
        if _instance is None:
            _instance = DomainConfidence()
        return _instance
