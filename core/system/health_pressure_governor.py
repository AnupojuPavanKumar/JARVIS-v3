# core/system/health_pressure_governor.py — JARVIS HEALTH PRESSURE GOVERNOR
"""
Runtime self-stabilization through pressure monitoring and adaptive mitigation.

Tracks pressure signals across the runtime:
  - thread count growth
  - memory consumption drift
  - callback queue accumulation
  - degraded subsystem frequency
  - event backlog growth
  - audio latency drift

When pressure exceeds thresholds, triggers adaptive mitigations:
  Level 0 (NOMINAL):   no action
  Level 1 (ELEVATED):   increase cleanup frequency, suppress non-critical proactive
  Level 2 (HIGH):      pause warmups, reduce suggestion engine rate
  Level 3 (CRITICAL):   suspend proactive systems, force memory compression
  Level 4 (EMERGENCY):  signal shutdown escalation

Pressure naturally decreases when conditions improve.
"""
from __future__ import annotations

import gc
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("HealthGovernor")


class PressureLevel(IntEnum):
    NOMINAL   = 0
    ELEVATED  = 1
    HIGH      = 2
    CRITICAL  = 3
    EMERGENCY = 4


@dataclass
class PressureMetrics:
    timestamp: float
    thread_count: int
    memory_mb: float | None
    callback_queue_size: int
    degraded_count: int
    degraded_rate_per_hour: float
    event_backlog: int
    ollama_latency_ms: float | None
    pressure_score: int  # weighted sum
    level: PressureLevel


@dataclass
class PressureThresholds:
    thread_count_warn:    int   = 40
    thread_count_critical:int   = 60
    memory_warn_mb:       float = 1500.0
    memory_critical_mb:    float = 2000.0
    callback_queue_warn:  int   = 50
    callback_queue_crit:  int   = 100
    degraded_rate_warn:   float = 3.0   # per hour
    ollama_latency_warn_ms: float = 5000.0
    ollama_latency_crit_ms: float = 15000.0


class HealthPressureGovernor:
    """
    Monitors runtime pressure and triggers adaptive mitigations.

    Runs in a background thread. All mitigations are non-invasive:
      - suppress_proactive → reduces suggestion frequency
      - pause_warmup → stops model prewarming
      - force_gc → triggers garbage collection
      - suspend_context → pauses workspace observer
      - signal_shutdown → triggers shutdown escalation
    """

    _instance: Optional[HealthPressureGovernor] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._thresholds = PressureThresholds()
        self._level = PressureLevel.NOMINAL
        self._history: deque[PressureMetrics] = deque(maxlen=100)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._mitigation_callbacks: list[Callable[[PressureLevel, str], None]] = []
        self._suppressed_systems: set[str] = set()
        self._degraded_events: deque[float] = deque(maxlen=100)
        self._last_gc: float = time.time()
        self._gc_interval_sec = 60.0
        # Hysteresis state
        self._level_entered_at: dict[PressureLevel, float] = {}
        # Separate enter/exit thresholds to prevent flapping
        self._ENTER = {
            PressureLevel.ELEVATED:  5,
            PressureLevel.HIGH:     15,
            PressureLevel.CRITICAL: 25,
            PressureLevel.EMERGENCY:40,
        }
        self._EXIT = {
            PressureLevel.ELEVATED:  2,
            PressureLevel.HIGH:     10,
            PressureLevel.CRITICAL: 20,
            PressureLevel.EMERGENCY:35,
        }
        # Minimum seconds at a level before allowed to drop
        self._COOLDOWN = {
            PressureLevel.ELEVATED:   30,
            PressureLevel.HIGH:       60,
            PressureLevel.CRITICAL:  120,
            PressureLevel.EMERGENCY:  60,
        }
        # Mitigation rate limiting: max 3 changes per 60s window
        self._mitigation_change_times: deque[float] = deque(maxlen=20)
        self._MITIGATION_RATE_WINDOW  = 60.0
        self._MITIGATION_RATE_MAX     = 3
        # Context mode for priority ordering
        self._context: str = "idle"   # idle|coding|gaming|voice_active|degraded
        # Context-specific mitigation priority orders (highest cost first)
        self._CONTEXT_ORDER: dict[str, list[str]] = {
            "idle":         ["model_warmup", "suppress_telemetry", "suppress_proactive", "suspend_context", "force_gc"],
            "coding":       ["model_warmup", "suppress_telemetry", "suppress_proactive", "suspend_context", "force_gc"],
            "gaming":       ["suppress_telemetry", "model_warmup",  "suppress_proactive", "suspend_context", "force_gc"],
            "voice_active": ["model_warmup", "suppress_telemetry", "suspend_context",    "suppress_proactive", "force_gc"],
            "degraded":     ["model_warmup", "suppress_telemetry", "suppress_proactive", "suspend_context", "force_gc"],
        }

    def set_thresholds(self, **kwargs):
        """Override default thresholds."""
        for k, v in kwargs.items():
            if hasattr(self._thresholds, k):
                setattr(self._thresholds, k, v)

    def set_context(self, context: str):
        """Set the active runtime context for mitigation priority ordering."""
        valid = set(self._CONTEXT_ORDER.keys())
        if context in valid:
            self._context = context
            log.info(f"[HealthGovernor] Context set to: {context}")

    def _is_rate_limited(self) -> bool:
        """True if mitigation changes are happening too fast (churn protection)."""
        now = time.time()
        cutoff = now - self._MITIGATION_RATE_WINDOW
        # Trim old entries
        while self._mitigation_change_times and self._mitigation_change_times[0] < cutoff:
            self._mitigation_change_times.popleft()
        if len(self._mitigation_change_times) >= self._MITIGATION_RATE_MAX:
            log.warning("[HealthGovernor] Mitigation rate limit reached — deferring changes")
            return True
        return False

    def _record_mitigation_change(self):
        self._mitigation_change_times.append(time.time())

    def on_mitigation(self, cb: Callable[[PressureLevel, str], None]):
        """Register a mitigation callback (level, action)."""
        self._mitigation_callbacks.append(cb)

    def start(self):
        """Start the governor monitoring loop."""
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="HealthGovernor")
        self._thread.start()
        log.info("[HealthGovernor] Started.")

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        log.info("[HealthGovernor] Stopped.")

    def record_degraded(self):
        """Call when a subsystem goes degraded."""
        self._degraded_events.append(time.time())

    def _degraded_rate_per_hour(self) -> float:
        """Degraded events per hour in the last hour."""
        cutoff = time.time() - 3600
        count = sum(1 for t in self._degraded_events if t > cutoff)
        return count

    def _collect_metrics(self) -> PressureMetrics:
        """Collect current pressure metrics."""
        thread_count = threading.active_count()
        memory_mb = None
        try:
            import psutil
            memory_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        except Exception:
            pass

        callback_queue_size = 0
        try:
            from core.executor.execution_queue import get_execution_queue
            q = get_execution_queue()
            callback_queue_size = getattr(q, '_queue_size', 0)
        except Exception:
            pass

        degraded_count = 0
        try:
            from core.system.readiness_state import get_readiness_tracker
            degraded_count = len(get_readiness_tracker().get_degraded())
        except Exception:
            pass

        ollama_latency = None
        try:
            from core.providers.ollama_manager import get_ollama_manager
            t0 = time.perf_counter()
            om = get_ollama_manager()
            ok = om.is_running() if hasattr(om, 'is_running') else False
            if ok:
                ollama_latency = (time.perf_counter() - t0) * 1000
        except Exception:
            pass

        pressure_score = self._compute_pressure_score(
            thread_count, memory_mb, callback_queue_size,
            self._degraded_rate_per_hour(), ollama_latency,
        )
        level = self._score_to_level_hysteresis(pressure_score)

        return PressureMetrics(
            timestamp=time.time(),
            thread_count=thread_count,
            memory_mb=memory_mb,
            callback_queue_size=callback_queue_size,
            degraded_count=degraded_count,
            degraded_rate_per_hour=self._degraded_rate_per_hour(),
            event_backlog=0,
            ollama_latency_ms=ollama_latency,
            pressure_score=pressure_score,
            level=level,
        )

    def _compute_pressure_score(
        self, threads: int, mem: float | None, queue: int,
        degraded_rate: float, ollama_lat: float | None,
    ) -> int:
        score = 0
        t = self._thresholds
        score += min(20, (threads - t.thread_count_warn) * 0.5)
        score += min(20, (threads - t.thread_count_critical) * 1.0) if threads > t.thread_count_critical else 0
        if mem:
            score += min(15, (mem - t.memory_warn_mb) / 100)
            score += min(15, (mem - t.memory_critical_mb) / 50) if mem > t.memory_critical_mb else 0
        score += min(10, (queue - t.callback_queue_warn) * 0.2)
        score += min(10, (queue - t.callback_queue_crit) * 0.3) if queue > t.callback_queue_crit else 0
        score += min(15, degraded_rate * 3)
        if ollama_lat:
            score += min(10, max(0, (ollama_lat - t.ollama_latency_warn_ms) / 500))
            score += min(10, max(0, (ollama_lat - t.ollama_latency_crit_ms) / 1000))
        return max(0, int(score))

    def _score_to_level(self, score: int) -> PressureLevel:
        """Legacy — used only for raw score mapping without hysteresis."""
        if score >= 40: return PressureLevel.EMERGENCY
        if score >= 25: return PressureLevel.CRITICAL
        if score >= 15: return PressureLevel.HIGH
        if score >= 5:  return PressureLevel.ELEVATED
        return PressureLevel.NOMINAL

    def _score_to_level_hysteresis(self, score: int) -> PressureLevel:
        """Hysteresis-aware level: separate enter/exit thresholds + cooldown."""
        current = self._level
        now     = time.time()

        # Determine what level the raw score wants
        if   score >= self._ENTER[PressureLevel.EMERGENCY]: target = PressureLevel.EMERGENCY
        elif score >= self._ENTER[PressureLevel.CRITICAL]:  target = PressureLevel.CRITICAL
        elif score >= self._ENTER[PressureLevel.HIGH]:      target = PressureLevel.HIGH
        elif score >= self._ENTER[PressureLevel.ELEVATED]:  target = PressureLevel.ELEVATED
        else:                                                target = PressureLevel.NOMINAL

        if target > current:
            # Escalating — always immediate
            self._level_entered_at[target] = now
            return target

        if target < current:
            # De-escalating — check cooldown
            entered   = self._level_entered_at.get(current, 0.0)
            cooldown  = self._COOLDOWN.get(current, 0)
            if now - entered < cooldown:
                return current  # still in cooldown window
            # Check exit threshold — score must be below exit, not just below enter
            exit_thresh = self._EXIT.get(current, 0)
            if score > exit_thresh:
                return current  # not low enough yet
            return target

        return current

    def _loop(self):
        interval = 20.0  # check every 20s
        while self._running and not self._stop_evt.is_set():
            try:
                metrics = self._collect_metrics()
                self._history.append(metrics)
                prev_level = self._level
                self._level = metrics.level

                if metrics.level > prev_level:
                    self._escalate(metrics)
                elif metrics.level < prev_level:
                    self._deescalate(metrics)

                # Only force GC under genuine memory pressure
                if (metrics.level >= PressureLevel.CRITICAL
                        and time.time() - self._last_gc > self._gc_interval_sec):
                    gc.collect()
                    self._last_gc = time.time()

            except Exception as e:
                log.debug(f"[HealthGovernor] metrics error: {e}")

            self._stop_evt.wait(timeout=interval)

    def _escalate(self, metrics: PressureMetrics):
        """Apply mitigations in context-aware cost order. Rate-limited. Survival-first."""
        # Check meta-stability — but survival actions bypass dampening
        dampening_active = False
        try:
            from core.system.meta_stability_guard import get_meta_stability_guard, DampeningLevel
            guard = get_meta_stability_guard()
            dl = guard.get_dampening_level()
            dampening_active = dl >= DampeningLevel.HEAVY
            if dl == DampeningLevel.FROZEN and metrics.level < PressureLevel.EMERGENCY:
                log.debug("[HealthGovernor] MetaStability FROZEN — skipping non-survival mitigations")
                # Still allow survival mitigations below
            guard.record_event("governor", metrics.level.name, direction=+1)
        except Exception:
            pass

        # Survival-critical actions — ALWAYS fire at threshold, ignore context and dampening
        _SURVIVAL = {"suspend_context", "force_gc", "signal_shutdown"}

        survival_actions = []
        if metrics.level >= PressureLevel.CRITICAL:
            survival_actions += [a for a in ("suspend_context", "force_gc") if a not in self._suppressed_systems]
        if metrics.level >= PressureLevel.EMERGENCY:
            survival_actions += ["signal_shutdown"] if "signal_shutdown" not in self._suppressed_systems else []

        for action in survival_actions:
            self._suppressed_systems.add(action)
            for cb in self._mitigation_callbacks:
                try: cb(metrics.level, action)
                except Exception: pass
            log.warning(f"[HealthGovernor] SURVIVAL MITIGATION: {action} (level={metrics.level.name})")
            try:
                from core.system.runtime_explainability import get_runtime_explainability
                get_runtime_explainability().mitigation(action, metrics.level.name, "SURVIVAL", "survival-first override")
            except Exception:
                pass

        # Optional mitigations — subject to dampening and rate limiting
        if dampening_active:
            return

        if self._is_rate_limited():
            return

        order = self._CONTEXT_ORDER.get(self._context, self._CONTEXT_ORDER["idle"])
        optional_actions = []
        if metrics.level >= PressureLevel.ELEVATED:
            optional_actions.append("pause_warmup")
        if metrics.level >= PressureLevel.HIGH:
            optional_actions.append("suppress_telemetry")
            optional_actions.append("suppress_proactive")

        optional_actions.sort(key=lambda a: order.index(a) if a in order else 99)

        applied = False
        for action in optional_actions:
            if action in self._suppressed_systems:
                continue
            self._suppressed_systems.add(action)
            for cb in self._mitigation_callbacks:
                try:
                    cb(metrics.level, action)
                except Exception:
                    pass
            log.warning(f"[HealthGovernor] MITIGATION: {action} (level={metrics.level.name}, ctx={self._context})")
            try:
                from core.system.runtime_explainability import get_runtime_explainability
                get_runtime_explainability().mitigation(action, metrics.level.name, self._context,
                                                        "context-weighted mitigation")
            except Exception:
                pass
            applied = True
            try:
                from core.system.equilibrium_monitor import get_equilibrium_monitor
                get_equilibrium_monitor().record_mitigation()
            except Exception:
                pass

        if applied:
            self._record_mitigation_change()

    def _deescalate(self, metrics: PressureMetrics):
        """Relax mitigations when pressure drops."""
        if metrics.level <= PressureLevel.NOMINAL:
            to_restore = ["suspend_context", "force_gc", "suppress_proactive", "pause_warmup"]
        elif metrics.level <= PressureLevel.ELEVATED:
            to_restore = ["suspend_context", "force_gc"]
        elif metrics.level <= PressureLevel.HIGH:
            to_restore = ["suspend_context"]
        else:
            return

        for action in to_restore:
            if action in self._suppressed_systems:
                self._suppressed_systems.discard(action)
                for cb in self._mitigation_callbacks:
                    try:
                        cb(metrics.level, f"restore_{action}")
                    except Exception:
                        pass
                log.info(f"[HealthGovernor] RESTORED: {action}")

    @property
    def level(self) -> PressureLevel:
        return self._level

    @property
    def suppressed_systems(self) -> set[str]:
        return set(self._suppressed_systems)

    def is_suppressed(self, system: str) -> bool:
        return system in self._suppressed_systems

    def is_nominal(self) -> bool:
        return self._level == PressureLevel.NOMINAL

    def get_metrics(self) -> PressureMetrics | None:
        try:
            return self._history[-1]
        except IndexError:
            return None

    def get_diagnostics(self) -> dict:
        metrics = self.get_metrics()
        history = []
        history_snap = list(self._history)
        base_ts = history_snap[0].timestamp if history_snap else 0.0
        for m in history_snap[-10:]:
            history.append({
                "ts": round(m.timestamp - base_ts, 0),
                "threads": m.thread_count,
                "mem_mb": round(m.memory_mb, 0) if m.memory_mb else None,
                "queue": m.callback_queue_size,
                "degraded": m.degraded_count,
                "score": m.pressure_score,
                "level": m.level.name,
            })
        return {
            "level": self._level.name,
            "suppressed": list(self._suppressed_systems),
            "latest": {
                "threads": metrics.thread_count if metrics else None,
                "mem_mb": round(metrics.memory_mb, 0) if metrics and metrics.memory_mb else None,
                "queue": metrics.callback_queue_size if metrics else None,
                "score": metrics.pressure_score if metrics else None,
            } if metrics else None,
            "history": history,
        }


_instance: Optional[HealthPressureGovernor] = None
_gov_lock = threading.Lock()


def get_health_pressure_governor() -> HealthPressureGovernor:
    global _instance
    with _gov_lock:
        if _instance is None:
            _instance = HealthPressureGovernor()
        return _instance
