# core/system/recovery_orchestrator.py — JARVIS RECOVERY ORCHESTRATOR
"""
Containment-first recovery. Order per subsystem:
  1. LOCAL_RETRY       — re-call init fn in-place
  2. ISOLATED_RESTART  — fresh thread, new instance
  3. DEGRADED_FALLBACK — mark degraded, continue without
  4. SUSPENDED         — disable capability entirely
  5. ESCALATED         — signal system-level action

Safeguards:
  - Exponential backoff (base 2s, cap 300s)
  - Restart budget: max 5 per hour per subsystem
  - Quarantine: 10-min hold after budget exhausted
  - Stagger: max 2 concurrent restarts system-wide
  - Priority queue: lower number = higher priority
"""
from __future__ import annotations

import heapq
import threading
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("RecoveryOrchestrator")

_BUDGET_WINDOW_SEC   = 3600.0   # 1 hour
_MAX_RESTARTS_HOUR   = 5
_QUARANTINE_SEC      = 600.0    # 10 minutes
_BACKOFF_BASE_SEC    = 2.0
_BACKOFF_MAX_SEC     = 300.0
_MAX_CONCURRENT      = 2        # max simultaneous restarts

# Dependency graph: subsystem → list of prerequisites that must be READY first
_DEPENDENCIES: dict[str, list[str]] = {
    "command_orchestrator": ["event_bus", "fast_router"],
    "voice_interrupt":      ["voice_tts", "voice_worker"],
    "suggestion_engine":    ["workspace_observer"],
    "model_prewarmer":      ["ollama_manager"],
    "ollama_inference":     ["ollama_manager"],
    "voice_stt":            ["voice_worker"],
    "wake_word":            ["voice_worker"],
    "memory_service":       ["checkpoint_manager"],
    "cognitive_continuity": ["layered_memory", "checkpoint_manager"],
}

# Staged reintegration time gates (seconds at each intermediate stage)
_STAGE_LIMITED_SEC   = 30.0
_STAGE_DEGRADED_SEC  = 60.0


class RecoveryStage(Enum):
    HEALTHY          = auto()
    LOCAL_RETRY      = auto()
    ISOLATED_RESTART = auto()
    DEGRADED_FALLBACK= auto()
    SUSPENDED        = auto()
    ESCALATED        = auto()
    QUARANTINED      = auto()


@dataclass
class RecoveryEntry:
    subsystem:        str
    init_fn:          Optional[Callable] = None
    priority:         int   = 5
    attempt_count:    int   = 0
    hourly_attempts:  list  = field(default_factory=list)
    last_attempt_at:  float = 0.0
    backoff_sec:      float = _BACKOFF_BASE_SEC
    quarantined_until:float = 0.0
    stage:            RecoveryStage = RecoveryStage.HEALTHY
    fail_streak:      int   = 0
    success_count:    int   = 0
    total_failures:   int   = 0
    # Fairness fields
    deferred_count:   int   = 0
    max_defers:       int   = 15     # after this, escalate regardless of deps
    queued_at:        float = 0.0    # when first queued — for starvation detection

    def is_quarantined(self) -> bool:
        return time.time() < self.quarantined_until

    def hourly_count(self) -> int:
        cutoff = time.time() - _BUDGET_WINDOW_SEC
        self.hourly_attempts = [t for t in self.hourly_attempts if t > cutoff]
        return len(self.hourly_attempts)

    def budget_exhausted(self) -> bool:
        return self.hourly_count() >= _MAX_RESTARTS_HOUR

    def record_attempt(self):
        now = time.time()
        self.last_attempt_at  = now
        self.attempt_count   += 1
        self.hourly_attempts.append(now)

    def record_success(self):
        self.fail_streak   = 0
        self.success_count += 1
        self.backoff_sec   = _BACKOFF_BASE_SEC
        self.stage         = RecoveryStage.HEALTHY

    def record_failure(self):
        self.fail_streak    += 1
        self.total_failures += 1
        self.backoff_sec     = min(self.backoff_sec * 2, _BACKOFF_MAX_SEC)

    def next_allowed_at(self) -> float:
        return self.last_attempt_at + self.backoff_sec


@dataclass(order=True)
class _QueueItem:
    priority:   int
    ready_at:   float
    subsystem:  str = field(compare=False)


class RecoveryOrchestrator:
    """
    Serialized, staggered recovery manager.
    Wire in subsystems via register(). Call request_recovery() on failure.
    """

    _instance: Optional[RecoveryOrchestrator] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._entries: dict[str, RecoveryEntry] = {}
        self._queue:   list[_QueueItem]         = []
        self._queue_lock   = threading.Lock()
        self._restart_sem  = threading.Semaphore(_MAX_CONCURRENT)
        self._running      = False
        self._stop_evt     = threading.Event()
        self._thread:  Optional[threading.Thread] = None
        self._callbacks: list[Callable[[str, RecoveryStage], None]] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def register(self, subsystem: str, init_fn: Callable, priority: int = 5):
        with self._lock:
            if subsystem not in self._entries:
                self._entries[subsystem] = RecoveryEntry(
                    subsystem=subsystem, init_fn=init_fn, priority=priority
                )

    def request_recovery(self, subsystem: str, reason: str = ""):
        with self._lock:
            entry = self._entries.get(subsystem)
            if not entry:
                log.warning(f"[Recovery] Unknown subsystem: '{subsystem}'")
                return

            if entry.is_quarantined():
                log.warning(f"[Recovery] '{subsystem}' quarantined until "
                            f"{time.strftime('%H:%M:%S', time.localtime(entry.quarantined_until))}")
                return

            if entry.stage in (RecoveryStage.SUSPENDED, RecoveryStage.ESCALATED):
                log.warning(f"[Recovery] '{subsystem}' is {entry.stage.name} — ignoring request")
                return

        # Check dependencies before queuing
        unmet = self._check_dependencies(subsystem)
        if unmet:
            entry.deferred_count += 1
            if entry.queued_at == 0.0:
                entry.queued_at = time.time()

            # Starvation detection: queued > 5 min without being processed
            waited = time.time() - entry.queued_at if entry.queued_at else 0
            if waited > 300:
                log.warning(f"[Recovery] Starvation detected for '{subsystem}' "
                            f"— waited {waited:.0f}s. Boosting priority.")
                entry.priority = max(1, entry.priority - 2)  # boost

            # Max defer limit — escalate to degraded fallback
            if entry.deferred_count >= entry.max_defers:
                log.error(f"[Recovery] '{subsystem}' max defers reached "
                          f"({entry.max_defers}) — forcing DEGRADED_FALLBACK")
                entry.stage = RecoveryStage.DEGRADED_FALLBACK
                self._mark_degraded(subsystem)
                return

            log.info(f"[Recovery] Deferring '{subsystem}' (defer #{entry.deferred_count}) "
                     f"— unmet deps: {unmet}")
            ready_at = time.time() + 10.0
            item = _QueueItem(priority=entry.priority + 5, ready_at=ready_at, subsystem=subsystem)
            with self._queue_lock:
                heapq.heappush(self._queue, item)
            return

        ready_at = max(time.time(), entry.next_allowed_at())
        item = _QueueItem(priority=entry.priority, ready_at=ready_at, subsystem=subsystem)
        with self._queue_lock:
            heapq.heappush(self._queue, item)
        log.info(f"[Recovery] Queued '{subsystem}' (reason={reason or 'unspecified'}, "
                 f"backoff={entry.backoff_sec:.0f}s)")

    def _check_dependencies(self, subsystem: str) -> list[str]:
        """Return list of unready prerequisite subsystems."""
        deps = _DEPENDENCIES.get(subsystem, [])
        if not deps:
            return []
        try:
            from core.system.readiness_state import get_readiness_tracker
            rt = get_readiness_tracker()
            unmet = []
            for dep in deps:
                state = rt.get_state(dep)
                state_name = state.name if state and hasattr(state, 'name') else "UNKNOWN"
                if state_name not in ("READY",):
                    unmet.append(dep)
            return unmet
        except Exception:
            return []

    def on_recovery_event(self, cb: Callable[[str, RecoveryStage], None]):
        self._callbacks.append(cb)

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="RecoveryOrchestrator"
        )
        self._thread.start()
        log.info("[Recovery] Orchestrator started.")

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    # ── Worker ────────────────────────────────────────────────────────────────

    def _worker_loop(self):
        while self._running and not self._stop_evt.is_set():
            item = self._next_ready_item()
            if item:
                # Fire in a thread to allow staggering via semaphore
                threading.Thread(
                    target=self._process_item,
                    args=(item,),
                    daemon=True,
                    name=f"Recovery-{item.subsystem}",
                ).start()
            else:
                self._stop_evt.wait(timeout=1.0)

    def _next_ready_item(self) -> Optional[_QueueItem]:
        now = time.time()
        with self._queue_lock:
            if not self._queue:
                return None
            if self._queue[0].ready_at <= now:
                return heapq.heappop(self._queue)
        return None

    def _process_item(self, item: _QueueItem):
        if not self._restart_sem.acquire(timeout=5.0):
            # Re-queue if semaphore not available
            with self._queue_lock:
                heapq.heappush(self._queue, item)
            return
        try:
            with self._lock:
                entry = self._entries.get(item.subsystem)
            if not entry:
                return
            self._attempt_recovery(entry)
        finally:
            self._restart_sem.release()

    def _attempt_recovery(self, entry: RecoveryEntry):
        log.info(f"[Recovery] Attempting recovery for '{entry.subsystem}' "
                 f"(streak={entry.fail_streak}, budget={entry.hourly_count()}/{_MAX_RESTARTS_HOUR})")

        if entry.budget_exhausted():
            entry.quarantined_until = time.time() + _QUARANTINE_SEC
            entry.stage = RecoveryStage.QUARANTINED
            log.error(f"[Recovery] '{entry.subsystem}' budget exhausted — quarantined for "
                      f"{_QUARANTINE_SEC/60:.0f}min")
            self._notify(entry.subsystem, RecoveryStage.QUARANTINED)
            self._mark_degraded(entry.subsystem)
            return

        entry.record_attempt()

        # Stage 1: Local retry
        if entry.fail_streak < 2 and entry.init_fn:
            entry.stage = RecoveryStage.LOCAL_RETRY
            self._notify(entry.subsystem, RecoveryStage.LOCAL_RETRY)
            if self._run_init(entry, threaded=False):
                return

        # Stage 2: Isolated restart
        if entry.fail_streak < 4 and entry.init_fn:
            entry.stage = RecoveryStage.ISOLATED_RESTART
            self._notify(entry.subsystem, RecoveryStage.ISOLATED_RESTART)
            if self._run_init(entry, threaded=True):
                return

        # Stage 3: Degraded fallback
        if entry.fail_streak < 6:
            entry.stage = RecoveryStage.DEGRADED_FALLBACK
            self._notify(entry.subsystem, RecoveryStage.DEGRADED_FALLBACK)
            self._mark_degraded(entry.subsystem)
            log.warning(f"[Recovery] '{entry.subsystem}' → DEGRADED_FALLBACK")
            return

        # Stage 4: Suspend
        entry.stage = RecoveryStage.SUSPENDED
        self._notify(entry.subsystem, RecoveryStage.SUSPENDED)
        self._mark_failed(entry.subsystem)
        log.error(f"[Recovery] '{entry.subsystem}' → SUSPENDED after {entry.fail_streak} failures")

    def _run_init(self, entry: RecoveryEntry, threaded: bool) -> bool:
        """Run init_fn, return True on success."""
        result = {"ok": False, "done": threading.Event()}

        def _do():
            try:
                entry.init_fn()
                result["ok"] = True
            except Exception as e:
                log.error(f"[Recovery] Init failed for '{entry.subsystem}': {e}")
            finally:
                result["done"].set()

        if threaded:
            t = threading.Thread(target=_do, daemon=True, name=f"InitRetry-{entry.subsystem}")
            t.start()
            timeout = min(entry.backoff_sec * 2, 30.0)
            result["done"].wait(timeout=timeout)
        else:
            _do()

        if result["ok"]:
            entry.record_success()
            self._staged_reintegration(entry)  # graduated, not immediate READY
            self._notify(entry.subsystem, RecoveryStage.HEALTHY)
            return True
        else:
            entry.record_failure()
            # Record to meta-stability guard
            try:
                from core.system.meta_stability_guard import get_meta_stability_guard
                get_meta_stability_guard().record_event(
                    "recovery", entry.subsystem, direction=+1
                )
            except Exception:
                pass
            return False

    def _staged_reintegration(self, entry: RecoveryEntry):
        """
        Graduated restoration: LIMITED → DEGRADED → READY
        Speed adapts to domain confidence:
          - HIGH confidence domain: times halved
          - LOW confidence domain: times doubled
        """
        subsystem = entry.subsystem
        factor    = self._get_confidence_factor(subsystem)
        lim_sec   = _STAGE_LIMITED_SEC  * factor
        deg_sec   = _STAGE_DEGRADED_SEC * factor
        log.info(f"[Recovery] Reintegrating '{subsystem}' "
                 f"(factor={factor:.1f}, lim={lim_sec:.0f}s, deg={deg_sec:.0f}s)")

        def _stage_up():
            try:
                from core.system.readiness_state import get_readiness_tracker
                rt = get_readiness_tracker()
                rt.mark_degraded(subsystem, "reintegration: limited")
            except Exception:
                pass
            log.info(f"[Recovery] '{subsystem}' → LIMITED (reintegration)")
            time.sleep(lim_sec)

            try:
                rt.mark_degraded(subsystem, "reintegration: degraded")
            except Exception:
                pass
            log.info(f"[Recovery] '{subsystem}' → DEGRADED (reintegration)")
            time.sleep(deg_sec)

            try:
                rt.mark_ready(subsystem)
            except Exception:
                pass
            log.info(f"[Recovery] '{subsystem}' → READY (reintegration complete)")

        threading.Thread(
            target=_stage_up, daemon=True, name=f"Reintegrate-{subsystem}"
        ).start()

    def _get_confidence_factor(self, subsystem: str) -> float:
        """1.0=normal, <1.0=faster (high confidence), >1.0=slower (low confidence)."""
        try:
            from core.system.domain_confidence import (
                get_domain_confidence, _DOMAIN_SUBSYSTEMS, Domain, DomainLevel
            )
            dc = get_domain_confidence()
            for domain, subs in _DOMAIN_SUBSYSTEMS.items():
                if subsystem in subs:
                    level = dc.get_level(domain)
                    return {
                        DomainLevel.CONFIDENT:  0.5,   # faster retries
                        DomainLevel.CAUTIOUS:   1.0,
                        DomainLevel.UNCERTAIN:  1.75,  # slower
                        DomainLevel.LOW:        3.0,   # very conservative
                    }.get(level, 1.0)
        except Exception:
            pass
        return 1.0

    def _mark_ready(self, subsystem: str):
        try:
            from core.system.readiness_state import get_readiness_tracker
            get_readiness_tracker().mark_ready(subsystem)
        except Exception:
            pass

    def _mark_degraded(self, subsystem: str):
        try:
            from core.system.readiness_state import get_readiness_tracker
            get_readiness_tracker().mark_degraded(subsystem, "recovery fallback")
        except Exception:
            pass

    def _mark_failed(self, subsystem: str):
        try:
            from core.system.readiness_state import get_readiness_tracker
            get_readiness_tracker().mark_failed(subsystem, "suspended after repeated failures")
        except Exception:
            pass

    def _notify(self, subsystem: str, stage: RecoveryStage):
        for cb in self._callbacks:
            try:
                cb(subsystem, stage)
            except Exception:
                pass

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def get_diagnostics(self) -> dict:
        with self._lock:
            entries = {}
            for name, e in self._entries.items():
                entries[name] = {
                    "stage":       e.stage.name,
                    "fail_streak": e.fail_streak,
                    "hourly":      e.hourly_count(),
                    "backoff_sec": round(e.backoff_sec, 1),
                    "quarantined": e.is_quarantined(),
                    "quarantine_remaining": max(0, round(e.quarantined_until - time.time(), 0)),
                    "total_failures": e.total_failures,
                    "successes":   e.success_count,
                }
        with self._queue_lock:
            queued = [i.subsystem for i in self._queue]
        return {
            "running":  self._running,
            "queued":   queued,
            "entries":  entries,
        }

    def get_quarantined(self) -> list[str]:
        with self._lock:
            return [n for n, e in self._entries.items() if e.is_quarantined()]

    def get_suspended(self) -> list[str]:
        with self._lock:
            return [n for n, e in self._entries.items()
                    if e.stage in (RecoveryStage.SUSPENDED, RecoveryStage.ESCALATED)]


_instance: Optional[RecoveryOrchestrator] = None
_ro_lock = threading.Lock()


def get_recovery_orchestrator() -> RecoveryOrchestrator:
    global _instance
    with _ro_lock:
        if _instance is None:
            _instance = RecoveryOrchestrator()
        return _instance
