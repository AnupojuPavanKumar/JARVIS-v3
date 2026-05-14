# core/lifecycle/controller.py
"""
Lifecycle controller — P14.
Manages startup phases, readiness checks, graceful shutdown, subsystem dependencies.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

log = logging.getLogger("LifecycleController")


class LifecyclePhase(Enum):
    PRE_INIT = auto()
    UI_BOOTSTRAP = auto()
    EXECUTION_CORE = auto()
    EVENT_BUS = auto()
    RESOURCE_MONITOR = auto()
    APP_REGISTRY = auto()
    AI_PROVIDERS = auto()
    OPTIONAL_SYSTEMS = auto()
    READY = auto()
    SHUTTING_DOWN = auto()
    SHUTDOWN = auto()


@dataclass
class PhaseResult:
    phase: LifecyclePhase
    success: bool
    duration_ms: float
    error: str | None = None
    subsystems_ready: list[str] = field(default_factory=list)


@dataclass
class SubsystemConfig:
    name: str
    phase: LifecyclePhase
    init_fn: Callable[[], None]
    shutdown_fn: Callable[[], None] | None = None
    depends_on: list[str] = field(default_factory=list)
    required: bool = True
    timeout_sec: float = 30.0


class LifecycleController:
    """
    Manages system lifecycle from startup to shutdown.
    Phase-based initialization with readiness checks, dependency resolution,
    graceful shutdown sequencing.
    """

    def __init__(self):
        self._current_phase: LifecyclePhase = LifecyclePhase.PRE_INIT
        self._phase_results: dict[LifecyclePhase, PhaseResult] = {}
        self._subsystems: dict[str, SubsystemConfig] = {}
        self._ready_subsystems: set[str] = set()
        self._lock = threading.RLock()
        self._phase_history: deque[PhaseResult] = deque(maxlen=50)
        self._startup_time: float = 0.0
        self._shutdown_time: float | None = None
        self._on_phase_change: list[Callable[[LifecyclePhase, LifecyclePhase], None]] = []
        self._running = False

    def register_subsystem(self, config: SubsystemConfig):
        """Register a subsystem for lifecycle management."""
        with self._lock:
            self._subsystems[config.name] = config

    def start(self) -> PhaseResult:
        """Execute the full startup sequence."""
        self._startup_time = time.time()
        self._running = True
        phase_order = [
            LifecyclePhase.UI_BOOTSTRAP,
            LifecyclePhase.EXECUTION_CORE,
            LifecyclePhase.EVENT_BUS,
            LifecyclePhase.RESOURCE_MONITOR,
            LifecyclePhase.APP_REGISTRY,
            LifecyclePhase.AI_PROVIDERS,
            LifecyclePhase.OPTIONAL_SYSTEMS,
            LifecyclePhase.READY,
        ]
        for phase in phase_order:
            result = self._execute_phase(phase)
            self._phase_results[phase] = result
            self._phase_history.append(result)
            if not result.success and result.phase != LifecyclePhase.OPTIONAL_SYSTEMS:
                log.error(f"[Lifecycle] Phase {phase.name} failed: {result.error}")
                self._current_phase = LifecyclePhase.SHUTTING_DOWN
                return result
            self._set_phase(phase)
        log.info(f"[Lifecycle] Startup complete in {(time.time() - self._startup_time) * 1000:.1f}ms")
        return self._phase_results[LifecyclePhase.READY]

    def _execute_phase(self, phase: LifecyclePhase) -> PhaseResult:
        t0 = time.time()
        subsystems_ready = []
        error = None
        try:
            phase_subsystems = {
                name: cfg for name, cfg in self._subsystems.items()
                if cfg.phase == phase
            }
            for name, cfg in phase_subsystems.items():
                for dep in cfg.depends_on:
                    if dep not in self._ready_subsystems:
                        if self._subsystems[dep].required:
                            raise RuntimeError(f"Dependency not ready: {dep} required by {name}")
                success = self._init_subsystem(name, cfg)
                if success:
                    subsystems_ready.append(name)
                    self._ready_subsystems.add(name)
        except Exception as e:
            error = str(e)
            log.error(f"[Lifecycle] Phase {phase.name} error: {e}")
        duration_ms = (time.time() - t0) * 1000
        return PhaseResult(
            phase=phase, success=(error is None), duration_ms=duration_ms,
            error=error, subsystems_ready=subsystems_ready,
        )

    def _init_subsystem(self, name: str, cfg: SubsystemConfig) -> bool:
        """Initialize a single subsystem with timeout."""
        import threading as th
        result = {"success": False, "error": None}
        def init():
            try:
                cfg.init_fn()
                result["success"] = True
            except Exception as e:
                result["error"] = str(e)
        t = th.Thread(target=init, daemon=True)
        t.start()
        t.join(timeout=cfg.timeout_sec)
        if t.is_alive():
            log.error(f"[Lifecycle] Subsystem '{name}' init timed out after {cfg.timeout_sec}s")
            return False
        if result["error"]:
            log.error(f"[Lifecycle] Subsystem '{name}' init failed: {result['error']}")
            return False
        return result["success"]

    def _set_phase(self, phase: LifecyclePhase):
        with self._lock:
            old = self._current_phase
            self._current_phase = phase
        for cb in self._on_phase_change:
            try:
                cb(old, phase)
            except Exception as e:
                log.warning(f"[Lifecycle] phase change callback error: {e}")

    def on_phase_change(self, callback: Callable[[LifecyclePhase, LifecyclePhase], None]):
        self._on_phase_change.append(callback)

    def shutdown(self, force: bool = False) -> PhaseResult:
        """Execute graceful shutdown sequence."""
        self._set_phase(LifecyclePhase.SHUTTING_DOWN)
        self._shutdown_time = time.time()
        t0 = time.time()
        shutdown_errors = []
        shutdown_order = list(reversed([
            LifecyclePhase.OPTIONAL_SYSTEMS,
            LifecyclePhase.AI_PROVIDERS,
            LifecyclePhase.APP_REGISTRY,
            LifecyclePhase.RESOURCE_MONITOR,
            LifecyclePhase.EVENT_BUS,
            LifecyclePhase.EXECUTION_CORE,
            LifecyclePhase.UI_BOOTSTRAP,
        ]))
        for phase in shutdown_order:
            phase_subsystems = {
                name: cfg for name, cfg in self._subsystems.items()
                if cfg.phase == phase
            }
            for name, cfg in phase_subsystems.items():
                if cfg.shutdown_fn:
                    try:
                        cfg.shutdown_fn()
                    except Exception as e:
                        shutdown_errors.append(f"{name}: {e}")
                        if not force:
                            log.warning(f"[Lifecycle] Shutdown error for '{name}': {e}")
        duration_ms = (time.time() - t0) * 1000
        self._set_phase(LifecyclePhase.SHUTDOWN)
        self._running = False
        error = "; ".join(shutdown_errors) if shutdown_errors else None
        result = PhaseResult(
            phase=LifecyclePhase.SHUTDOWN, success=len(shutdown_errors) == 0,
            duration_ms=duration_ms, error=error,
        )
        self._phase_history.append(result)
        return result

    def is_ready(self) -> bool:
        with self._lock:
            return self._current_phase == LifecyclePhase.READY

    @property
    def current_phase(self) -> LifecyclePhase:
        with self._lock:
            return self._current_phase

    def get_startup_duration_ms(self) -> float:
        if self._startup_time > 0:
            return (time.time() - self._startup_time) * 1000
        return 0.0

    def get_phase_history(self) -> list[PhaseResult]:
        with self._lock:
            return list(self._phase_history)

    def get_subsystems_status(self) -> dict:
        with self._lock:
            return {
                name: {
                    "phase": cfg.phase.name,
                    "ready": name in self._ready_subsystems,
                    "required": cfg.required,
                    "dependencies": cfg.depends_on,
                }
                for name, cfg in self._subsystems.items()
            }

    def stats(self) -> dict:
        with self._lock:
            total_ms = sum(r.duration_ms for r in self._phase_results.values())
            return {
                "phase": self._current_phase.name,
                "startup_ms": self.get_startup_duration_ms(),
                "ready_subsystems": len(self._ready_subsystems),
                "total_subsystems": len(self._subsystems),
                "phase_count": len(self._phase_results),
                "total_phase_ms": round(total_ms, 2),
            }


_global_lifecycle: LifecycleController | None = None
_lc_lock = threading.Lock()


def get_lifecycle_controller() -> LifecycleController:
    global _global_lifecycle
    with _lc_lock:
        if _global_lifecycle is None:
            _global_lifecycle = LifecycleController()
        return _global_lifecycle
