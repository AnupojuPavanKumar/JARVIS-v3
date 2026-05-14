# core/observability/dashboard.py
"""
Pipeline visualization & diagnostics hooks.
Lightweight developer diagnostics dashboard for action lifecycles,
queue state, event bus activity, execution traces, and resource usage.
Debug-mode only, non-blocking.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

log = logging.getLogger("Diagnostics")

DEBUG_MODE = False


def set_debug_mode(enabled: bool):
    global DEBUG_MODE
    DEBUG_MODE = enabled


@dataclass
class PipelineSnapshot:
    """A snapshot of the entire pipeline state."""
    timestamp: float
    queue_depth: int
    active_count: int
    event_bus_queue: int
    event_bus_subscribers: int
    event_bus_stats: dict
    queue_stats: dict
    resource_stats: dict
    recent_traces: list[dict]
    recent_logs: list[dict]
    shortcuts_hot: int
    total_shortcuts: int
    cpu_percent: float
    ram_percent: float
    vram_free_mb: float


class PipelineDiagnostics:
    """
    Lightweight pipeline diagnostics for developer debugging.
    Collects and exposes state across all subsystems.
    """

    def __init__(self, max_snapshots: int = 60):
        self._snapshots: deque[PipelineSnapshot] = deque(maxlen=max_snapshots)
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        if self._running or not DEBUG_MODE:
            return
        self._running = True
        self._thread = threading.Thread(target=self._collect_loop, daemon=True, name="PipelineDiagnostics")
        self._thread.start()

    def stop(self):
        self._running = False

    def _collect_loop(self):
        while self._running:
            try:
                snapshot = self._collect_snapshot()
                with self._lock:
                    self._snapshots.append(snapshot)
            except Exception as e:
                log.debug(f"[Diagnostics] Collection error: {e}")
            time.sleep(2.0)

    def _collect_snapshot(self) -> PipelineSnapshot:
        queue_stats = {}
        event_bus_stats = {}
        resource_stats = {}
        recent_traces = []
        recent_logs = []
        shortcuts_hot = 0
        total_shortcuts = 0
        cpu = 0.0
        ram_pct = 0.0
        vram_free = 0

        try:
            from core.executor.execution_queue import get_execution_queue
            q = get_execution_queue()
            queue_stats = q.stats
        except Exception:
            pass

        try:
            from core.events.bus import get_event_bus
            bus = get_event_bus()
            event_bus_stats = bus.stats()
        except Exception:
            pass

        try:
            from core.resource.monitor import get_resource_monitor
            mon = get_resource_monitor()
            snap = mon.current_snapshot()
            resource_stats = mon.stats()
            if snap:
                cpu = snap.cpu_percent
                ram_pct = snap.ram_percent
                vram_free = snap.vram_free_mb
        except Exception:
            pass

        try:
            from core.tracing.lineage import get_tracer
            tracer = get_tracer()
            traces = tracer.recent_traces(5)
            recent_traces = [t.to_dict() for t in traces]
        except Exception:
            pass

        try:
            from core.intents.shortcuts import get_shortcut_registry
            sc = get_shortcut_registry()
            st = sc.stats()
            shortcuts_hot = st["hot_shortcuts"]
            total_shortcuts = st["total_shortcuts"]
        except Exception:
            pass

        return PipelineSnapshot(
            timestamp=time.time(),
            queue_depth=queue_stats.get("queue_depth", 0),
            active_count=queue_stats.get("active_count", 0),
            event_bus_queue=event_bus_stats.get("queue_depth", 0),
            event_bus_subscribers=event_bus_stats.get("subscribers", 0),
            event_bus_stats=event_bus_stats,
            queue_stats=queue_stats,
            resource_stats=resource_stats,
            recent_traces=recent_traces,
            recent_logs=recent_logs,
            shortcuts_hot=shortcuts_hot,
            total_shortcuts=total_shortcuts,
            cpu_percent=round(cpu, 1),
            ram_percent=round(ram_pct, 1),
            vram_free_mb=vram_free,
        )

    def get_snapshot(self) -> PipelineSnapshot | None:
        if not DEBUG_MODE:
            return None
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def get_history(self, seconds: float = 60.0) -> list[PipelineSnapshot]:
        cutoff = time.time() - seconds
        with self._lock:
            return [s for s in self._snapshots if s.timestamp >= cutoff]

    def summary(self) -> dict:
        snap = self.get_snapshot()
        if not snap:
            return {"debug_mode": False, "status": "disabled"}
        return {
            "debug_mode": True,
            "timestamp": time.strftime("%H:%M:%S", time.localtime(snap.timestamp)),
            "queue": f"depth={snap.queue_depth}, active={snap.active_count}",
            "event_bus": f"queue={snap.event_bus_queue}, subs={snap.event_bus_subscribers}",
            "cpu": f"{snap.cpu_percent}%",
            "ram": f"{snap.ram_percent}%",
            "vram_free": f"{snap.vram_free_mb}MB",
            "traces": len(snap.recent_traces),
            "shortcuts": f"hot={snap.shortcuts_hot}/{snap.total_shortcuts}",
            "traces": [t.get("root_command", "?") for t in snap.recent_traces],
        }


_global_diagnostics: PipelineDiagnostics | None = None
_diag_lock = threading.Lock()


def get_diagnostics() -> PipelineDiagnostics:
    global _global_diagnostics
    with _diag_lock:
        if _global_diagnostics is None:
            _global_diagnostics = PipelineDiagnostics()
            if DEBUG_MODE:
                _global_diagnostics.start()
        return _global_diagnostics
