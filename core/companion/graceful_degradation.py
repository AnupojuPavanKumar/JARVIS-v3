# core/companion/graceful_degradation.py — JARVIS GRACEFUL DEGRADATION
"""
Soft degradation awareness — monitors system health beyond binary health checks.

Tracks:
  - inference latency trends
  - VRAM pressure
  - model load frequency
  - audio buffer health
  - provider responsiveness

Adapts:
  - verbosity (reduce on slow inference)
  - proactive behavior (fewer suggestions under load)
  - model selection (auto-switch on persistent slowdown)
  - background task deferral

Wire into: jarvis_brain, CalmEngine, SuggestionEngine.
"""
from __future__ import annotations

import threading
import time
import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

log = logging.getLogger("GracefulDegrade")


class HealthState(Enum):
    NOMINAL     = auto()
    SOFT        = auto()   # mild slowdown, slight adaptation
    MODERATE   = auto()   # noticeable latency, reduce proactive
    HEAVY      = auto()   # high latency, minimal responses
    CRITICAL   = auto()   # nearly unusable, emergency only


@dataclass
class InferenceSample:
    latency_s: float
    timestamp: float
    model: str


@dataclass
class HealthSnapshot:
    state: HealthState
    avg_latency: float
    vram_mb: float | None
    inference_rate: float
    suggestion_suppressed: bool
    verbosity_reduced: bool
    proactive_paused: bool


class GracefulDegradation:
    """
    Monitors system health and adjusts JARVIS behavior accordingly.
    Smooth transitions between states — no sudden switches.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._state = HealthState.NOMINAL
        self._latency_history: list[InferenceSample] = []
        self._last_inference: float = 0
        self._vram_history: list[float] = []
        self._suggestion_suppressed = False
        self._verbosity_reduced = False
        self._proactive_paused = False
        self._prev_verbosity = 1.0
        self._prev_density = 1.0
        self._state_since = time.time()
        self._slow_consecutive = 0

    def record_inference(self, latency_s: float, model: str = ""):
        """Record an inference latency sample."""
        with self._lock:
            self._last_inference = time.time()
            sample = InferenceSample(latency_s=latency_s, timestamp=time.time(), model=model)
            self._latency_history.append(sample)
            if len(self._latency_history) > 50:
                self._latency_history = self._latency_history[-50:]

    def record_vram(self, vram_mb: float):
        """Record a VRAM usage sample."""
        with self._lock:
            self._vram_history.append(vram_mb)
            if len(self._vram_history) > 20:
                self._vram_history = self._vram_history[-20:]

    def record_failure(self):
        """Increment failure counter."""
        with self._lock:
            self._slow_consecutive += 1

    def record_success(self):
        """Reset failure counter."""
        with self._lock:
            self._slow_consecutive = 0

    def _compute_state(self) -> HealthState:
        if not self._latency_history:
            return HealthState.NOMINAL

        recent = [s for s in self._latency_history if time.time() - s.timestamp < 120]
        if not recent:
            return HealthState.NOMINAL

        avg_lat = sum(s.latency_s for s in recent) / len(recent)

        if avg_lat < 3.0:
            return HealthState.NOMINAL
        elif avg_lat < 8.0:
            return HealthState.SOFT
        elif avg_lat < 15.0:
            return HealthState.MODERATE
        elif avg_lat < 30.0:
            return HealthState.HEAVY
        else:
            return HealthState.CRITICAL

    def _update_state(self):
        new_state = self._compute_state()
        if new_state != self._state:
            log.info(f"[Degrade] State → {new_state.name} "
                     f"(avg latency: {self._avg_latency:.1f}s)")
            self._state = new_state
            self._state_since = time.time()
            self._apply_adaptations(new_state)

    def _apply_adaptations(self, state: HealthState):
        self._suggestion_suppressed = (
            state in (HealthState.MODERATE, HealthState.HEAVY, HealthState.CRITICAL)
        )
        self._verbosity_reduced = (
            state in (HealthState.HEAVY, HealthState.CRITICAL)
        )
        self._proactive_paused = (state == HealthState.CRITICAL)
        state_weights = {
            HealthState.NOMINAL: 1.0, HealthState.SOFT: 0.8,
            HealthState.MODERATE: 0.6, HealthState.HEAVY: 0.35, HealthState.CRITICAL: 0.15,
        }
        density = {
            HealthState.NOMINAL: 1.0, HealthState.SOFT: 0.85,
            HealthState.MODERATE: 0.65, HealthState.HEAVY: 0.4, HealthState.CRITICAL: 0.15,
        }
        self._prev_verbosity = state_weights.get(state, 1.0)
        self._prev_density = density.get(state, 1.0)

    def get_smoothed_verbosity(self) -> float:
        """Return 0.0-1.0 verbosity multiplier for gradual transitions."""
        with self._lock:
            state = self._state
            elapsed = time.time() - self._state_since
            t = min(1.0, elapsed / 30.0)
            state_weights = {
                HealthState.NOMINAL: 1.0,
                HealthState.SOFT: 0.8,
                HealthState.MODERATE: 0.6,
                HealthState.HEAVY: 0.35,
                HealthState.CRITICAL: 0.15,
            }
            target = state_weights.get(state, 1.0)
            return self._prev_verbosity * (1 - t) + target * t

    def get_smoothed_speech_density(self) -> float:
        """Return 0.0-1.0 speech density for gradual pacing changes."""
        with self._lock:
            state = self._state
            elapsed = time.time() - self._state_since
            t = min(1.0, elapsed / 45.0)
            density = {
                HealthState.NOMINAL: 1.0,
                HealthState.SOFT: 0.85,
                HealthState.MODERATE: 0.65,
                HealthState.HEAVY: 0.4,
                HealthState.CRITICAL: 0.15,
            }
            target = density.get(state, 1.0)
            return self._prev_density * (1 - t) + target * t

    @property
    def state(self) -> HealthState:
        with self._lock:
            self._update_state()
            return self._state

    @property
    def _avg_latency(self) -> float:
        recent = [s for s in self._latency_history if time.time() - s.timestamp < 120]
        if not recent:
            return 0.0
        return sum(s.latency_s for s in recent) / len(recent)

    @property
    def _avg_vram(self) -> float | None:
        if not self._vram_history:
            return None
        return sum(self._vram_history) / len(self._vram_history)

    @property
    def is_healthy(self) -> bool:
        return self.state == HealthState.NOMINAL

    @property
    def is_soft_degraded(self) -> bool:
        return self.state != HealthState.NOMINAL

    def should_reduce_verbosity(self) -> bool:
        with self._lock:
            self._update_state()
            return self._verbosity_reduced

    def should_suppress_suggestions(self) -> bool:
        with self._lock:
            self._update_state()
            return self._suggestion_suppressed

    def pacing_delay(self) -> float:
        """Return pacing delay in seconds (for natural response feel)."""
        with self._lock:
            if self._state == HealthState.SOFT:
                return 0.05
            elif self._state == HealthState.MODERATE:
                return 0.1
            elif self._state in (HealthState.HEAVY, HealthState.CRITICAL):
                return 0.2
            return 0.0

    def should_pause_proactive(self) -> bool:
        with self._lock:
            self._update_state()
            return self._proactive_paused

    def should_defer_background_tasks(self) -> bool:
        with self._lock:
            return self.state in (HealthState.HEAVY, HealthState.CRITICAL)

    def get_latency_class(self) -> str:
        """Human-readable latency class."""
        avg = self._avg_latency
        if avg < 1.0:
            return "fast"
        elif avg < 5.0:
            return "normal"
        elif avg < 10.0:
            return "slow"
        elif avg < 20.0:
            return "very slow"
        else:
            return "critical"

    def get_health_summary(self) -> str:
        state = self.state
        lat = self._avg_latency
        lat_class = self.get_latency_class()
        vram = self._avg_vram

        if state == HealthState.NOMINAL:
            return f"Systems nominal ({lat_class})."
        elif state == HealthState.SOFT:
            return f"Slightly slowed ({lat_class})."
        elif state == HealthState.MODERATE:
            return f"Moderate slowdown detected ({lat_class})."
        elif state == HealthState.HEAVY:
            return f"Heavy slowdown — responses limited."
        else:
            return "Critical slowdown — emergency mode."

    def get_snapshot(self) -> HealthSnapshot:
        with self._lock:
            self._update_state()
            return HealthSnapshot(
                state=self._state,
                avg_latency=self._avg_latency,
                vram_mb=self._avg_vram,
                inference_rate=len([s for s in self._latency_history
                                    if time.time() - s.timestamp < 60]),
                suggestion_suppressed=self._suggestion_suppressed,
                verbosity_reduced=self._verbosity_reduced,
                proactive_paused=self._proactive_paused,
            )


_instance: Optional[GracefulDegradation] = None
_lock = threading.Lock()


def get_graceful_degradation() -> GracefulDegradation:
    global _instance
    with _lock:
        if _instance is None:
            _instance = GracefulDegradation()
        return _instance