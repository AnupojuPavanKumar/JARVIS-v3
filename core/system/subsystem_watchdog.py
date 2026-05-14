# core/system/subsystem_watchdog.py — JARVIS SUBSYSTEM WATCHDOG
"""
Hung-task detection and cancellation escalation for subsystems.

Every long-running subsystem init task gets a watchdog entry.
If the task exceeds its timeout, the watchdog:
  1. Records the hang
  2. Attempts cooperative cancellation
  3. Escalates to forced termination if needed

This prevents:
  - Model warmup from hanging forever
  - Ollama probe from blocking
  - Audio stream from stalling
  - Deferred init from leaking
"""
from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("SubsystemWatchdog")


class WatchdogAction(Enum):
    NONE        = auto()
    CANCEL      = auto()
    FORCE       = auto()
    RESTART     = auto()
    ESCALATE    = auto()


@dataclass
class WatchdogEntry:
    name: str
    started_at: float
    timeout_sec: float
    task_thread: threading.Thread | None = None
    cancel_fn: Callable[[], None] | None = None
    on_timeout: Callable[[], None] | None = None
    action_taken: WatchdogAction = WatchdogAction.NONE
    completed: bool = False
    timed_out: bool = False


@dataclass
class WatchdogEvent:
    timestamp: float
    entry_name: str
    action: WatchdogAction
    duration_sec: float
    details: str = ""


class SubsystemWatchdog:
    """
    Tracks in-progress subsystem tasks and detects hangs.

    Usage:
        wd = get_watchdog()
        token = wd.watch("model_prewarmer", timeout_sec=30.0,
                          cancel_fn=lambda: CancellationToken.request_shutdown())
        # ... do init work ...
        wd.complete(token)  # call when done
    """

    _instance: Optional[SubsystemWatchdog] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._entries: dict[str, WatchdogEntry] = {}
        self._events: deque[WatchdogEvent] = deque(maxlen=200)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._hung_count: dict[str, int] = {}

    def watch(
        self,
        name: str,
        timeout_sec: float = 30.0,
        cancel_fn: Callable[[], None] | None = None,
        on_timeout: Callable[[], None] | None = None,
    ) -> WatchdogEntry:
        """Start watching a subsystem task."""
        with self._lock:
            if name in self._entries:
                log.warning(f"[Watchdog] Already watching '{name}'")
                return self._entries[name]
            entry = WatchdogEntry(
                name=name,
                started_at=time.time(),
                timeout_sec=timeout_sec,
                task_thread=threading.current_thread(),
                cancel_fn=cancel_fn,
                on_timeout=on_timeout,
            )
            self._entries[name] = entry
            self._log_event(name, WatchdogAction.NONE, f"watching (timeout={timeout_sec}s)")
            return entry

    def complete(self, name: str | WatchdogEntry):
        """Mark a task as complete (call from the watched thread)."""
        name_str = name.name if isinstance(name, WatchdogEntry) else name
        with self._lock:
            entry = self._entries.get(name_str)
            if not entry:
                return
            entry.completed = True
            duration = time.time() - entry.started_at
            self._log_event(name_str, WatchdogAction.NONE, f"completed in {duration:.1f}s")
            self._entries.pop(name_str, None)

    def fail(self, name: str | WatchdogEntry, reason: str = ""):
        """Mark a task as failed."""
        name_str = name.name if isinstance(name, WatchdogEntry) else name
        with self._lock:
            entry = self._entries.pop(name_str, None)
            if entry:
                self._log_event(name_str, WatchdogAction.NONE, f"failed: {reason}")

    def _cancel(self, entry: WatchdogEntry) -> WatchdogAction:
        """Attempt cooperative cancellation."""
        try:
            if entry.cancel_fn:
                entry.cancel_fn()
                self._log_event(entry.name, WatchdogAction.CANCEL, "cooperative cancel sent")
                return WatchdogAction.CANCEL
        except Exception as e:
            self._log_event(entry.name, WatchdogAction.CANCEL, f"cancel error: {e}")
        return WatchdogAction.NONE

    def _force(self, entry: WatchdogEntry) -> WatchdogAction:
        """Force termination attempt."""
        try:
            if entry.task_thread and entry.task_thread.is_alive():
                self._log_event(entry.name, WatchdogAction.FORCE,
                               f"thread alive={entry.task_thread.is_alive()}, "
                               f"not forcibly killed (Python limitation)")
                return WatchdogAction.FORCE
        except Exception as e:
            self._log_event(entry.name, WatchdogAction.FORCE, f"force error: {e}")
        return WatchdogAction.NONE

    def _on_timeout(self, entry: WatchdogEntry, action: WatchdogAction):
        """Fire the on_timeout callback if registered."""
        if entry.on_timeout:
            try:
                entry.on_timeout()
                self._log_event(entry.name, action, "on_timeout callback fired")
            except Exception as e:
                self._log_event(entry.name, action, f"on_timeout error: {e}")

        self._hung_count[entry.name] = self._hung_count.get(entry.name, 0) + 1
        if self._hung_count[entry.name] >= 3:
            log.error(f"[Watchdog] SUBSYSTEM HUNG: '{entry.name}' failed 3 times — escalating")
            self._log_event(entry.name, WatchdogAction.ESCALATE,
                           f"3 failures, escalating to shutdown")

    def _log_event(self, name: str, action: WatchdogAction, details: str):
        self._events.append(WatchdogEvent(
            timestamp=time.time(),
            entry_name=name,
            action=action,
            duration_sec=0.0,
            details=details,
        ))

    def start(self):
        """Start the watchdog monitoring loop."""
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Watchdog")
        self._thread.start()
        log.info("[Watchdog] Started.")

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        log.info("[Watchdog] Stopped.")

    def _loop(self):
        """Check all watched tasks for timeout."""
        while self._running and not self._stop_evt.is_set():
            self._check_all()
            self._stop_evt.wait(timeout=1.0)

    def _check_all(self):
        """Check for hung tasks."""
        now = time.time()
        to_remove = []

        with self._lock:
            entries = list(self._entries.items())

        for name, entry in entries:
            if entry.completed:
                to_remove.append(name)
                continue

            elapsed = now - entry.started_at

            if elapsed >= entry.timeout_sec and not entry.timed_out:
                entry.timed_out = True
                log.warning(f"[Watchdog] TIMEOUT: '{name}' — {elapsed:.1f}s elapsed "
                           f"(limit: {entry.timeout_sec}s)")

                # Stage 1: cooperative cancel
                action = self._cancel(entry)

                # Stage 2: force
                if action == WatchdogAction.NONE:
                    action = self._force(entry)

                # Stage 3: on_timeout callback
                self._on_timeout(entry, action)

                # Remove if completed after cancellation
                if entry.completed:
                    to_remove.append(name)
                    self._log_event(name, WatchdogAction.NONE, "recovered after cancel")

            elif elapsed >= entry.timeout_sec * 1.5 and not entry.completed:
                log.error(f"[Watchdog] DOUBLE TIMEOUT: '{name}' — force removing from watch")
                to_remove.append(name)

        for name in to_remove:
            with self._lock:
                self._entries.pop(name, None)

    @property
    def watched(self) -> list[str]:
        with self._lock:
            return [e.name for e in self._entries.values() if not e.completed]

    def hung_count(self, name: str) -> int:
        return self._hung_count.get(name, 0)

    def get_events(self, limit: int = 30) -> list[WatchdogEvent]:
        with self._lock:
            return list(self._events)[-limit:]

    def diagnostics(self) -> dict:
        with self._lock:
            entries = {}
            for name, entry in self._entries.items():
                entries[name] = {
                    "elapsed_sec": round(time.time() - entry.started_at, 1),
                    "timeout_sec": entry.timeout_sec,
                    "timed_out": entry.timed_out,
                    "completed": entry.completed,
                    "action": entry.action_taken.name,
                }
        return {
            "watched_count": len(entries),
            "entries": entries,
            "hung_counts": dict(self._hung_count),
            "total_events": len(self._events),
        }


_instance: Optional[SubsystemWatchdog] = None
_watchdog_lock = threading.Lock()


def get_watchdog() -> SubsystemWatchdog:
    global _instance
    with _watchdog_lock:
        if _instance is None:
            _instance = SubsystemWatchdog()
        return _instance
