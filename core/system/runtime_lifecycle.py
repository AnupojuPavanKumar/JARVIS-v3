# core/system/runtime_lifecycle.py — JARVIS RUNTIME LIFECYCLE MANAGER
"""
Centralized runtime authority. ONE owner per subsystem.

Responsibilities:
  - Subsystem ownership: no duplicate instances
  - Lifecycle sequencing: init → ready → shutdown → disposed
  - Cancellation propagation: all init tasks respect CancellationToken
  - Shutdown choreography: ordered teardown
  - Audit trail: creation, init order, shutdown order, ownership transfers
  - Quiescence detection: idle state awareness

Rules:
  - Every subsystem registers before creating its instance
  - Ownership is exclusive — registering the same name twice is an error
  - Shutdown is always ordered (reverse of init by default)
  - No subsystem continues init after CancellationToken.cancelled() is True
"""
from __future__ import annotations

import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional, Any

log_audit = True


class SubsystemState(Enum):
    UNREGISTERED = auto()
    REGISTERED   = auto()
    INITIALIZING = auto()
    READY        = auto()
    SHUTTING_DOWN= auto()
    SHUTDOWN     = auto()
    FAILED       = auto()


@dataclass
class LifecycleEvent:
    timestamp: float
    subsystem: str
    event: str  # registered|initializing|ready|shutdown|failed|cancelled
    details: str = ""
    thread: str = ""


@dataclass
class SubsystemEntry:
    name: str
    owner: str  # module/class that owns this subsystem
    init_fn: Callable[[], Any]
    shutdown_fn: Callable[[], None] | None = None
    state: SubsystemState = SubsystemState.UNREGISTERED
    instance: Any = None
    depends_on: list[str] = field(default_factory=list)
    shutdown_order: int = 0
    thread_name: str = ""
    init_duration_ms: float | None = None
    failure_reason: str = ""

    def is_lifecycle_safe(self) -> bool:
        """Can this subsystem proceed with init?"""
        return self.state in (SubsystemState.REGISTERED, SubsystemState.FAILED)


class RuntimeLifecycle:
    """
    Single authoritative owner of all JARVIS subsystem lifecycles.

    Boot orchestrator delegates here. ServiceRegistry delegates here.
    All subsystem init/shutdown goes through this manager.
    """

    _instance: Optional[RuntimeLifecycle] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._entries: dict[str, SubsystemEntry] = {}
        self._audit: deque[LifecycleEvent] = deque(maxlen=500)
        self._shutdown_order_counter = 0
        self._state = SubsystemState.UNREGISTERED
        self._quiescent = False
        self._quiescent_since: float | None = None
        self._activity_lock = threading.RLock()
        self._last_activity: float = time.time()
        self._idle_callbacks: list[Callable[[], None]] = []
        self._monitor_stop = threading.Event()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="RuntimeLifecycle-Monitor")

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        owner: str,
        init_fn: Callable[[], Any],
        shutdown_fn: Callable[[], None] | None = None,
        depends_on: list[str] | None = None,
    ) -> SubsystemEntry:
        """
        Register a subsystem. MUST be called before creating the instance.

        Raises:
            ValueError: if name already registered (duplicate ownership)
        """
        with self._lock:
            if name in self._entries:
                entry = self._entries[name]
                if entry.owner != owner:
                    raise ValueError(
                        f"[RuntimeLifecycle] Ownership conflict: '{name}' "
                        f"owned by '{entry.owner}', cannot register as '{owner}'"
                    )
                return entry  # idempotent re-registration

            entry = SubsystemEntry(
                name=name,
                owner=owner,
                init_fn=init_fn,
                shutdown_fn=shutdown_fn,
                depends_on=depends_on or [],
                state=SubsystemState.REGISTERED,
                thread_name=threading.current_thread().name,
                shutdown_order=self._shutdown_order_counter,
            )
            self._shutdown_order_counter += 1
            self._entries[name] = entry
            self._audit.append(LifecycleEvent(
                timestamp=time.time(),
                subsystem=name,
                event="registered",
                details=f"owner={owner}",
                thread=threading.current_thread().name,
            ))
            return entry

    def acquire(self, name: str, factory: Callable[[], Any]) -> Any:
        """
        Register + init a subsystem in one call. Returns the instance.

        The factory MUST check CancellationToken.cancelled() if it takes >50ms.
        """
        entry = self.register(
            name=name,
            owner=factory.__module__ + "." + factory.__qualname__,
            init_fn=factory,
        )
        if entry.instance is not None:
            return entry.instance
        return self._init_subsystem(entry)

    def _init_subsystem(self, entry: SubsystemEntry) -> Any:
        from core.system.cancellation_token import CancellationToken
        token = CancellationToken(entry.name)

        def _do_init():
            if CancellationToken.cancelled():
                entry.state = SubsystemState.FAILED
                entry.failure_reason = "cancelled during init"
                self._audit.append(LifecycleEvent(
                    timestamp=time.time(), subsystem=entry.name,
                    event="cancelled", details="init abandoned", thread=threading.current_thread().name,
                ))
                return None

            t0 = time.time()
            entry.state = SubsystemState.INITIALIZING
            self._audit.append(LifecycleEvent(
                timestamp=t0, subsystem=entry.name,
                event="initializing", thread=threading.current_thread().name,
            ))
            try:
                inst = entry.init_fn()
                entry.instance = inst
                entry.state = SubsystemState.READY
                entry.init_duration_ms = (time.time() - t0) * 1000
                self._audit.append(LifecycleEvent(
                    timestamp=time.time(), subsystem=entry.name,
                    event="ready",
                    details=f"{entry.init_duration_ms:.1f}ms",
                    thread=threading.current_thread().name,
                ))
                self._record_activity()
                return inst
            except Exception as e:
                entry.state = SubsystemState.FAILED
                entry.failure_reason = str(e)
                tb = traceback.format_exc()
                self._audit.append(LifecycleEvent(
                    timestamp=time.time(), subsystem=entry.name,
                    event="failed", details=f"{e}\n{tb}", thread=threading.current_thread().name,
                ))
                return None

        t = threading.Thread(target=_do_init, daemon=True, name=f"Lifecycle-{entry.name}")
        t.start()
        t.join()
        return entry.instance

    def is_ready(self, name: str) -> bool:
        with self._lock:
            e = self._entries.get(name)
            return e is not None and e.state == SubsystemState.READY

    def get_instance(self, name: str) -> Any:
        with self._lock:
            return self._entries.get(name, SubsystemEntry("", "", lambda: None)).instance

    def get_entry(self, name: str) -> Optional[SubsystemEntry]:
        with self._lock:
            return self._entries.get(name)

    # ── Lifecycle transitions ─────────────────────────────────────────────────

    def mark_initializing(self, name: str):
        with self._lock:
            e = self._entries.get(name)
            if e:
                e.state = SubsystemState.INITIALIZING

    def mark_ready(self, name: str):
        with self._lock:
            e = self._entries.get(name)
            if e:
                e.state = SubsystemState.READY
                self._audit.append(LifecycleEvent(
                    timestamp=time.time(), subsystem=name, event="ready",
                    thread=threading.current_thread().name,
                ))

    def mark_failed(self, name: str, reason: str = ""):
        with self._lock:
            e = self._entries.get(name)
            if e:
                e.state = SubsystemState.FAILED
                e.failure_reason = reason
                self._audit.append(LifecycleEvent(
                    timestamp=time.time(), subsystem=name, event="failed",
                    details=reason, thread=threading.current_thread().name,
                ))

    def mark_shutdown(self, name: str):
        with self._lock:
            e = self._entries.get(name)
            if e:
                e.state = SubsystemState.SHUTTING_DOWN

    # ── Shutdown choreography ─────────────────────────────────────────────────

    def shutdown_all(self, timeout_per_subsystem: float = 3.0) -> dict[str, str]:
        """
        Execute ordered shutdown of all subsystems.

        Order:
          1. Stop new actions (proactive, telemetry, suggestion engines)
          2. Stop voice input (wake-word, voice interrupt, STT)
          3. Flush checkpoints (companion memory)
          4. Stop voice output (TTS, worker)
          5. Release microphone
          6. Stop workers (orchestrator, execution queue)
          7. Stop monitors (hardware sentinel, workspace observer)
          8. Dispose resources

        Returns: dict of name → error message (empty = clean)
        """
        from core.system.cancellation_token import CancellationToken
        CancellationToken.request_shutdown("runtime_shutdown")

        errors = {}
        t0 = time.time()

        # Sort by shutdown_order DESC (reverse registration order)
        with self._lock:
            sorted_entries = sorted(
                [e for e in self._entries.values() if e.state == SubsystemState.READY],
                key=lambda e: e.shutdown_order,
                reverse=True,
            )

        self._audit.append(LifecycleEvent(
            timestamp=time.time(), subsystem="RUNTIME",
            event="shutdown_began",
            details=f"{len(sorted_entries)} subsystems",
            thread=threading.current_thread().name,
        ))

        for entry in sorted_entries:
            entry.state = SubsystemState.SHUTTING_DOWN
            if entry.shutdown_fn is None and entry.instance is not None:
                entry.shutdown_fn = getattr(entry.instance, 'stop', None)

            if entry.shutdown_fn is None:
                continue

            self._audit.append(LifecycleEvent(
                timestamp=time.time(), subsystem=entry.name,
                event="shutdown", thread=threading.current_thread().name,
            ))

            try:
                done = threading.Event()
                exc_holder = [None]

                def _stop(fn=entry.shutdown_fn, ev=done, ex=exc_holder):
                    try:
                        fn()
                    except Exception as e:
                        ex[0] = e
                    finally:
                        ev.set()

                t = threading.Thread(target=_stop, daemon=True, name=f"Shutdown-{entry.name}")
                t.start()
                finished = done.wait(timeout=timeout_per_subsystem)

                if not finished:
                    errors[entry.name] = f"timeout after {timeout_per_subsystem}s"
                    entry.state = SubsystemState.FAILED
                elif exc_holder[0]:
                    raise exc_holder[0]
                else:
                    entry.state = SubsystemState.SHUTDOWN
                self._audit.append(LifecycleEvent(
                    timestamp=time.time(), subsystem=entry.name,
                    event="shutdown_complete", thread=threading.current_thread().name,
                ))
            except Exception as e:
                errors[entry.name] = str(e)
                entry.state = SubsystemState.FAILED
                self._audit.append(LifecycleEvent(
                    timestamp=time.time(), subsystem=entry.name,
                    event="shutdown_error", details=str(e),
                    thread=threading.current_thread().name,
                ))

        self._state = SubsystemState.SHUTDOWN
        self._monitor_stop.set()  # stop the monitor loop cleanly
        elapsed = (time.time() - t0) * 1000
        print(f"[RuntimeLifecycle] Shutdown complete in {elapsed:.1f}ms — "
              f"{len(errors)} errors in {len(sorted_entries)} subsystems")
        return errors

    # ── Quiescence detection ─────────────────────────────────────────────────

    def _record_activity(self):
        with self._activity_lock:
            self._last_activity = time.time()
            if self._quiescent:
                self._quiescent = False
                self._quiescent_since = None

    def record_activity(self):
        """Call from any thread when user activity occurs."""
        self._record_activity()

    def is_idle(self, idle_threshold_sec: float = 30.0) -> bool:
        """True if no activity for idle_threshold seconds."""
        with self._activity_lock:
            return (time.time() - self._last_activity) >= idle_threshold_sec

    def idle_duration_sec(self) -> float:
        with self._activity_lock:
            return time.time() - self._last_activity

    def on_idle(self, callback: Callable[[], None]):
        """Register a callback to fire when the runtime goes idle."""
        self._idle_callbacks.append(callback)

    def _monitor_loop(self):
        """Background loop: detects idle state and fires callbacks."""
        idle_callbacks_triggered = set()
        while not self._monitor_stop.is_set():
            try:
                self._monitor_stop.wait(timeout=5.0)
                if self._monitor_stop.is_set():
                    break
                idle_dur = self.idle_duration_sec()
                if idle_dur >= 30.0 and not self._quiescent:
                    self._quiescent = True
                    self._quiescent_since = time.time()
                    print(f"[RuntimeLifecycle] Quiescent — idle for {idle_dur:.0f}s")
                    for cb in self._idle_callbacks:
                        try:
                            cb()
                            idle_callbacks_triggered.add(cb)
                        except Exception as e:
                            print(f"[RuntimeLifecycle] Idle callback error: {e}")
                elif idle_dur < 10.0 and self._quiescent:
                    self._quiescent = False
                    self._quiescent_since = None
                    idle_callbacks_triggered.clear()
            except Exception:
                pass

    @property
    def is_quiescent(self) -> bool:
        return self._quiescent

    @property
    def state(self) -> SubsystemState:
        return self._state

    # ── Audit trail ───────────────────────────────────────────────────────────

    def get_audit(self, limit: int = 50) -> list[LifecycleEvent]:
        with self._lock:
            return list(self._audit)[-limit:]

    def audit_summary(self) -> dict:
        """Human-readable lifecycle audit summary."""
        with self._lock:
            ready = sum(1 for e in self._entries.values() if e.state == SubsystemState.READY)
            failed = [e.name for e in self._entries.values() if e.state == SubsystemState.FAILED]
            initializing = [e.name for e in self._entries.values() if e.state == SubsystemState.INITIALIZING]
            registered = [e.name for e in self._entries.values() if e.state == SubsystemState.REGISTERED]
            return {
                "total": len(self._entries),
                "ready": ready,
                "failed": failed,
                "initializing": initializing,
                "registered": registered,
                "quiescent": self._quiescent,
                "state": self._state.name,
            }

    def get_diagnostics(self) -> dict:
        """Full diagnostic snapshot for debugging."""
        with self._lock:
            entries = {}
            for name, entry in self._entries.items():
                entries[name] = {
                    "owner": entry.owner,
                    "state": entry.state.name,
                    "init_ms": entry.init_duration_ms,
                    "failure": entry.failure_reason,
                    "thread": entry.thread_name,
                    "depends_on": entry.depends_on,
                    "shutdown_order": entry.shutdown_order,
                    "has_instance": entry.instance is not None,
                }
            return {
                "runtime_state": self._state.name,
                "quiescent": self._quiescent,
                "idle_sec": self.idle_duration_sec(),
                "subsystems": entries,
                "audit_count": len(self._audit),
            }


_instance: Optional[RuntimeLifecycle] = None
_lifecycle_lock = threading.Lock()


def get_runtime_lifecycle() -> RuntimeLifecycle:
    global _instance
    with _lifecycle_lock:
        if _instance is None:
            _instance = RuntimeLifecycle()
        return _instance
