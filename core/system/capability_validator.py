# core/system/capability_validator.py — JARVIS CAPABILITY VALIDATOR
"""
Continuous capability health verification.

Problem:
  ReadinessTracker marks subsystems READY at init time, but those states
  can become stale:
    - Ollama goes down 30 minutes after startup
    - Wake-word daemon crashes silently
    - TTS engine becomes unresponsive
    - Provider throttles requests

Solution:
  Periodic health probes that verify each capability is still operational.
  If a probe fails, the subsystem is marked stale → degraded.
  If it recovers, mark READY again.

Probes are lightweight (socket probes, not full inference calls).
Full probe frequency: every 60s. Fast probe: every 15s.
"""
from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("CapabilityValidator")

_PROBE_INTERVAL_SEC = 60.0
_FAST_INTERVAL_SEC = 15.0
_STALE_THRESHOLD_SEC = 180.0  # 3 min of failed probes → mark stale


class CapabilityHealth(Enum):
    HEALTHY  = auto()
    STALE    = auto()   # probes failing, likely degraded
    DEAD     = auto()   # confirmed unresponsive


class CapabilityQuality(Enum):
    """Finer-grained quality state surfaced to UI and confidence model."""
    READY    = auto()   # full capability, functional probe passed
    DEGRADED = auto()   # probe passed but with elevated latency/errors
    FALLBACK = auto()   # using a fallback path (e.g. deterministic only)
    LIMITED  = auto()   # partially functional
    OFFLINE  = auto()   # confirmed unavailable


@dataclass
class ProbeResult:
    capability: str
    health: CapabilityHealth
    checked_at: float
    latency_ms: float | None = None
    error: str | None = None
    consecutive_failures: int = 0


@dataclass
class ProbeFn:
    """A health probe function. Returns (ok: bool, latency_ms: float, error: str)."""
    check: Callable[[], tuple[bool, float | None, str | None]]


class CapabilityValidator:
    """
    Background validator that probes each capability continuously.

    Tracks:
      - consecutive probe failures
      - stale state (no failures but last_success too old)
      - recovery events

    Emits events when capabilities change state.
    """

    _instance: Optional[CapabilityValidator] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._probes: dict[str, ProbeFn] = {}
        self._results: dict[str, ProbeResult] = {}
        self._last_success: dict[str, float] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._state: dict[str, CapabilityHealth] = {}
        self._quality: dict[str, CapabilityQuality] = {}
        self._callbacks: list[Callable[[str, CapabilityHealth, ProbeResult], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

    def register_probe(self, capability: str, probe: ProbeFn):
        """Register a health probe for a named capability."""
        with self._lock:
            self._probes[capability] = probe
            self._state[capability]   = CapabilityHealth.HEALTHY
            self._quality[capability] = CapabilityQuality.READY
            self._consecutive_failures[capability] = 0

    def register_socket_probe(self, capability: str, host: str, port: int, timeout: float = 1.0):
        """Convenience: register a TCP socket probe."""
        def probe() -> tuple[bool, float | None, str | None]:
            t0 = time.perf_counter()
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True, (time.perf_counter() - t0) * 1000, None
            except OSError as e:
                return False, (time.perf_counter() - t0) * 1000, str(e)
            except Exception as e:
                return False, None, str(e)

        self.register_probe(capability, ProbeFn(check=probe))

    def register_function_probe(self, capability: str, fn: Callable[[], bool], timeout_sec: float = 5.0):
        """Register a callable probe. fn() must return True/False."""
        def probe() -> tuple[bool, float | None, str | None]:
            t0 = time.perf_counter()
            try:
                result = fn()
                latency = (time.perf_counter() - t0) * 1000
                if latency > timeout_sec * 1000:
                    return False, latency, f"timeout after {timeout_sec}s"
                return result, latency, None
            except Exception as e:
                return False, (time.perf_counter() - t0) * 1000, str(e)

        self.register_probe(capability, ProbeFn(check=probe))

    def on_state_change(self, cb: Callable[[str, CapabilityHealth, ProbeResult], None]):
        """Register a callback for capability state changes."""
        self._callbacks.append(cb)

    def start(self):
        """Start the background validation loop."""
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="CapabilityValidator")
        self._thread.start()
        log.info("[CapabilityValidator] Started.")

    def stop(self):
        """Stop validation loop."""
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        log.info("[CapabilityValidator] Stopped.")

    def _loop(self):
        while self._running and not self._stop_evt.is_set():
            interval = self._adaptive_interval()
            self._probe_all()
            self._stop_evt.wait(timeout=interval)

    def _adaptive_interval(self) -> float:
        """Reduce probe frequency under high pressure to avoid self-induced load."""
        base = _PROBE_INTERVAL_SEC
        try:
            from core.system.health_pressure_governor import (
                get_health_pressure_governor, PressureLevel
            )
            level = get_health_pressure_governor().level
            # Scale up interval (less frequent) as pressure rises
            multiplier = {
                PressureLevel.NOMINAL:   1.0,
                PressureLevel.ELEVATED:  1.5,
                PressureLevel.HIGH:      2.0,
                PressureLevel.CRITICAL:  4.0,
                PressureLevel.EMERGENCY: 8.0,
            }.get(level, 1.0)
            base = base * multiplier
        except Exception:
            pass
        try:
            from core.system.runtime_confidence import get_runtime_confidence, ConfidenceLevel
            conf = get_runtime_confidence().level
            # At low confidence, probe less (targeted only)
            if conf == ConfidenceLevel.LOW:
                base = max(base, _PROBE_INTERVAL_SEC * 3)
        except Exception:
            pass
        return min(base, 600.0)  # cap at 10 minutes

    def _probe_all(self):
        """Run all registered probes, skipping heavyweight ones under pressure."""
        heavy_ok = self._heavy_probes_allowed()
        for capability, probe_fn in list(self._probes.items()):
            # Skip function probes (AI inference) when under CRITICAL+ pressure
            if not heavy_ok and capability in ("ollama_inference",):
                log.debug(f"[CapabilityValidator] Skipping heavy probe '{capability}' under pressure")
                continue
            self._probe(capability, probe_fn)

    def _heavy_probes_allowed(self) -> bool:
        """False when pressure is CRITICAL or EMERGENCY."""
        try:
            from core.system.health_pressure_governor import (
                get_health_pressure_governor, PressureLevel
            )
            level = get_health_pressure_governor().level
            return level < PressureLevel.CRITICAL
        except Exception:
            return True

    def _probe(self, capability: str, probe_fn: ProbeFn):
        """Run a single probe and update state."""
        try:
            ok, latency, error = probe_fn.check()
        except Exception as e:
            ok, latency, error = False, None, str(e)

        now = time.time()
        result = ProbeResult(
            capability=capability,
            health=CapabilityHealth.HEALTHY if ok else CapabilityHealth.STALE,
            checked_at=now,
            latency_ms=latency,
            error=error,
            consecutive_failures=self._consecutive_failures.get(capability, 0),
        )

        prev_state = self._state.get(capability, CapabilityHealth.HEALTHY)

        if ok:
            self._last_success[capability] = now
            self._consecutive_failures[capability] = 0
            if prev_state != CapabilityHealth.HEALTHY:
                result.health = CapabilityHealth.HEALTHY
                self._set_state(capability, CapabilityHealth.HEALTHY, result)
            self._set_quality(capability, latency, failures=0)
        else:
            failures = self._consecutive_failures.get(capability, 0) + 1
            self._consecutive_failures[capability] = failures
            result.consecutive_failures = failures

            if failures >= 3:
                self._set_state(capability, CapabilityHealth.DEAD, result)
                self._set_quality_offline(capability)
            elif prev_state == CapabilityHealth.HEALTHY:
                self._set_state(capability, CapabilityHealth.STALE, result)
                self._set_quality_degraded(capability)

        self._results[capability] = result

    def _set_state(self, capability: str, health: CapabilityHealth, result: ProbeResult):
        with self._lock:
            if self._state.get(capability) == health:
                return
            self._state[capability] = health
        log.info(f"[CapabilityValidator] {capability}: {health.name}")
        for cb in self._callbacks:
            try:
                cb(capability, health, result)
            except Exception:
                pass

    def _set_quality(self, capability: str, latency_ms: float | None, failures: int):
        """Map latency + consecutive failures to a CapabilityQuality."""
        if failures == 0 and (latency_ms is None or latency_ms < 2000):
            q = CapabilityQuality.READY
        elif failures == 0:
            q = CapabilityQuality.DEGRADED
        elif failures < 3:
            q = CapabilityQuality.LIMITED
        else:
            q = CapabilityQuality.OFFLINE
        with self._lock:
            self._quality[capability] = q

    def _set_quality_degraded(self, capability: str):
        with self._lock:
            self._quality[capability] = CapabilityQuality.DEGRADED

    def _set_quality_offline(self, capability: str):
        with self._lock:
            self._quality[capability] = CapabilityQuality.OFFLINE

    def get_quality(self, capability: str) -> CapabilityQuality:
        with self._lock:
            return self._quality.get(capability, CapabilityQuality.OFFLINE)

    def get_all_quality(self) -> dict[str, str]:
        with self._lock:
            return {k: v.name for k, v in self._quality.items()}

    def get_health(self, capability: str) -> CapabilityHealth:
        with self._lock:
            return self._state.get(capability, CapabilityHealth.STALE)

    def is_healthy(self, capability: str) -> bool:
        return self.get_health(capability) == CapabilityHealth.HEALTHY

    def get_result(self, capability: str) -> ProbeResult | None:
        with self._lock:
            return self._results.get(capability)

    def get_all(self) -> dict[str, CapabilityHealth]:
        with self._lock:
            return dict(self._state)

    def get_summary(self) -> dict:
        with self._lock:
            healthy = [k for k, v in self._state.items() if v == CapabilityHealth.HEALTHY]
            stale = [k for k, v in self._state.items() if v == CapabilityHealth.STALE]
            dead = [k for k, v in self._state.items() if v == CapabilityHealth.DEAD]
        return {
            "healthy": healthy,
            "stale": stale,
            "dead": dead,
            "total": len(self._state),
        }

    def diagnostics(self) -> dict:
        with self._lock:
            snapshot = dict(self._results)
            last_success = dict(self._last_success)
        results = {}
        now = time.time()
        for cap, result in snapshot.items():
            results[cap] = {
                "health": result.health.name,
                "latency_ms": round(result.latency_ms, 1) if result.latency_ms else None,
                "error": result.error,
                "consecutive_failures": result.consecutive_failures,
                "last_success_age_sec": round(now - last_success.get(cap, 0), 1),
            }
        return {
            "running": self._running,
            "probe_count": len(self._probes),
            "results": results,
            "summary": self.get_summary(),
        }


_instance: Optional[CapabilityValidator] = None
_validator_lock = threading.Lock()


def get_capability_validator() -> CapabilityValidator:
    global _instance
    with _validator_lock:
        if _instance is None:
            _instance = CapabilityValidator()
        return _instance
