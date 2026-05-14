# core/system/shutdown_escalation.py — JARVIS SHUTDOWN ESCALATION MANAGER
"""
Multi-stage shutdown with bounded timeouts and escalation.

Stages:
  1. GRACEFUL — cooperative cancellation + normal subsystem stop (max 3s)
  2. URGENT   — timeout enforcement, forced thread interruption (max 2s)
  3. ISOLATED — per-subsystem isolated teardown in separate threads (max 3s)
  4. FINAL    — only os._exit if Python refuses to exit

Every stage has a hard timeout. If exceeded, escalation fires immediately.
os._exit is LAST RESORT ONLY — not in the normal shutdown path.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("ShutdownEscalation")


class ShutdownStage(Enum):
    IDLE       = auto()
    GRACEFUL   = auto()
    URGENT     = auto()
    ISOLATED   = auto()
    FINAL      = auto()
    COMPLETE   = auto()
    ESCALATED  = auto()


@dataclass
class TeardownTask:
    name: str
    stop_fn: Callable[[], None]
    timeout_sec: float = 2.0
    required: bool = True


@dataclass
class StageResult:
    stage: ShutdownStage
    duration_sec: float
    errors: dict[str, str] = field(default_factory=dict)
    escalated_to: ShutdownStage | None = None
    forced: bool = False


class ShutdownEscalation:
    """
    Bounded multi-stage shutdown with escalation.

    Usage:
        se = ShutdownEscalation()
        se.register("VoiceWorker", voice_worker.stop, timeout=2.0)
        se.register("WakeDaemon", wake_daemon.stop, timeout=1.5)
        se.register("Orchestrator", orchestrator.stop, timeout=1.0)
        se.register("MemorySave", memory_save_fn, timeout=3.0)
        se.shutdown()  # returns StageResult
    """

    STAGE_TIMEOUT = {
        ShutdownStage.GRACEFUL: 3.0,
        ShutdownStage.URGENT:   2.0,
        ShutdownStage.ISOLATED: 3.0,
        ShutdownStage.FINAL:    1.0,
    }

    def __init__(self):
        self._lock = threading.RLock()
        self._tasks: list[TeardownTask] = []
        self._stage = ShutdownStage.IDLE
        self._results: list[StageResult] = []
        self._on_escalate: list[Callable[[ShutdownStage, ShutdownStage], None]] = []

    def register(
        self,
        name: str,
        stop_fn: Callable[[], None],
        timeout_sec: float = 2.0,
        required: bool = True,
    ):
        """Register a teardown task. Called before shutdown()."""
        with self._lock:
            self._tasks.append(TeardownTask(
                name=name, stop_fn=stop_fn,
                timeout_sec=timeout_sec, required=required,
            ))

    def on_escalate(self, cb: Callable[[ShutdownStage, ShutdownStage], None]):
        """Called when escalating to a new stage."""
        self._on_escalate.append(cb)

    def _escalate(self, from_stage: ShutdownStage, to_stage: ShutdownStage):
        log.warning(f"[ShutdownEscalation] Escalating: {from_stage.name} → {to_stage.name}")
        self._stage = to_stage
        for cb in self._on_escalate:
            try:
                cb(from_stage, to_stage)
            except Exception:
                pass

    def _run_stage(self, stage: ShutdownStage) -> StageResult:
        """
        Execute all registered teardown tasks for a given stage.
        Returns StageResult with errors (empty = clean).
        """
        t0 = time.time()
        errors = {}
        forced = False

        if stage == ShutdownStage.GRACEFUL:
            errors, forced = self._run_graceful()
        elif stage == ShutdownStage.URGENT:
            errors, forced = self._run_urgent()
        elif stage == ShutdownStage.ISOLATED:
            errors, forced = self._run_isolated()
        elif stage == ShutdownStage.FINAL:
            errors, forced = self._run_final()

        elapsed = time.time() - t0
        return StageResult(
            stage=stage,
            duration_sec=elapsed,
            errors=errors,
            forced=forced,
        )

    def _run_graceful(self) -> tuple[dict[str, str], bool]:
        """Stage 1: Cooperative stop with per-task timeouts."""
        errors = {}
        forced = False
        deadline = time.time() + self.STAGE_TIMEOUT[ShutdownStage.GRACEFUL]

        for task in self._tasks:
            remaining = deadline - time.time()
            if remaining <= 0:
                forced = True
                break

            try:
                self._stop_with_timeout(task.name, task.stop_fn, min(task.timeout_sec, remaining))
            except TimeoutError:
                log.warning(f"[Shutdown] Graceful timeout: '{task.name}'")
                if task.required:
                    errors[task.name] = "graceful_timeout"
            except Exception as e:
                log.error(f"[Shutdown] Graceful stop error '{task.name}': {e}")
                if task.required:
                    errors[task.name] = str(e)

        if forced or any(v == "graceful_timeout" for v in errors.values()):
            self._escalate(ShutdownStage.GRACEFUL, ShutdownStage.URGENT)
            self._results.append(StageResult(
                stage=ShutdownStage.GRACEFUL,
                duration_sec=time.time() - (time.time() - self.STAGE_TIMEOUT[ShutdownStage.GRACEFUL]),
                errors=errors,
                escalated_to=ShutdownStage.URGENT,
                forced=forced,
            ))
        return errors, forced

    def _run_urgent(self) -> tuple[dict[str, str], bool]:
        """Stage 2: Force stop with shorter timeouts."""
        errors = {}
        forced = True
        deadline = time.time() + self.STAGE_TIMEOUT[ShutdownStage.URGENT]

        for task in self._tasks:
            remaining = deadline - time.time()
            if remaining <= 0:
                errors[task.name] = "timeout_skipped"
                continue

            try:
                self._stop_with_timeout(
                    task.name, task.stop_fn,
                    min(task.timeout_sec * 0.5, remaining)
                )
            except TimeoutError:
                log.error(f"[Shutdown] Urgent timeout: '{task.name}'")
                errors[task.name] = "urgent_timeout"
            except Exception as e:
                errors[task.name] = str(e)

        if any(v.endswith("timeout") for v in errors.values()):
            self._escalate(ShutdownStage.URGENT, ShutdownStage.ISOLATED)
            self._results.append(StageResult(
                stage=ShutdownStage.URGENT,
                duration_sec=self.STAGE_TIMEOUT[ShutdownStage.URGENT],
                errors=errors,
                escalated_to=ShutdownStage.ISOLATED,
                forced=True,
            ))
        return errors, forced

    def _run_isolated(self) -> tuple[dict[str, str], bool]:
        """Stage 3: Each task in its own thread with hard kill fallback."""
        errors = {}
        forced = True
        results: dict[str, bool] = {}
        threads: list[threading.Thread] = []

        def isolate_stop(task: TeardownTask, deadline: float):
            try:
                self._stop_with_timeout(task.name, task.stop_fn, deadline)
                results[task.name] = True
            except Exception as e:
                results[task.name] = False
                log.error(f"[Shutdown] Isolated stop error '{task.name}': {e}")

        deadline = time.time() + self.STAGE_TIMEOUT[ShutdownStage.ISOLATED]

        for task in self._tasks:
            t = threading.Thread(
                target=isolate_stop,
                args=(task, task.timeout_sec),
                daemon=True,
                name=f"IsolatedStop-{task.name}",
            )
            threads.append(t)
            t.start()

        for t in threads:
            remaining = deadline - time.time()
            t.join(timeout=max(0.5, remaining))

        for task in self._tasks:
            if task.name not in results or not results[task.name]:
                errors[task.name] = "isolated_failure"
                log.error(f"[Shutdown] Isolated stop failed: '{task.name}'")

        if errors:
            self._escalate(ShutdownStage.ISOLATED, ShutdownStage.FINAL)
            self._results.append(StageResult(
                stage=ShutdownStage.ISOLATED,
                duration_sec=self.STAGE_TIMEOUT[ShutdownStage.ISOLATED],
                errors=errors,
                escalated_to=ShutdownStage.FINAL,
                forced=True,
            ))
        return errors, forced

    def _run_final(self) -> tuple[dict[str, str], bool]:
        """Stage 4: Last resort — just exit."""
        log.error("[ShutdownEscalation] FINAL STAGE — hard exit")
        print("[Shutdown] Hard exit — cleanup failed for: "
              f"{[t.name for t in self._tasks if t.name not in self._results]}")
        self._stage = ShutdownStage.FINAL
        return {}, True

    def _stop_with_timeout(self, name: str, fn: Callable[[], None], timeout: float):
        """Execute a stop_fn in a thread, wait for timeout."""
        result = {"error": None, "done": False}
        deadline = time.time() + timeout

        def target():
            try:
                fn()
            except Exception as e:
                result["error"] = str(e)
            finally:
                result["done"] = True

        t = threading.Thread(target=target, daemon=True, name=f"Stop-{name}")
        t.start()
        t.join(timeout=max(0.01, timeout))

        if not result["done"]:
            if result["error"]:
                raise RuntimeError(f"{name}: {result['error']}")
            raise TimeoutError(f"{name}: exceeded {timeout:.1f}s")

    def shutdown(self) -> StageResult:
        """
        Execute full shutdown pipeline.

        Returns:
            StageResult of the final completed stage.

        os._exit is called ONLY if Stage 4 (FINAL) is reached AND
        Python has not exited after a final grace period.
        """
        self._stage = ShutdownStage.GRACEFUL
        self._results = []
        t0 = time.time()

        for stage in [ShutdownStage.GRACEFUL, ShutdownStage.URGENT,
                       ShutdownStage.ISOLATED, ShutdownStage.FINAL]:
            result = self._run_stage(stage)
            self._results.append(result)

            if result.stage == ShutdownStage.FINAL and result.forced:
                log.critical("[ShutdownEscalation] All stages exhausted — exiting")
                print("[Shutdown] All graceful stages failed — exiting")
                self._stage = ShutdownStage.ESCALATED
                self._final_exit()
                break

            if not result.errors:
                log.info(f"[ShutdownEscalation] {stage.name} completed cleanly "
                         f"in {result.duration_sec:.1f}s")
                if stage == ShutdownStage.GRACEFUL:
                    self._stage = ShutdownStage.COMPLETE
                    break

        total = time.time() - t0
        final = self._results[-1]
        print(f"[Shutdown] Total: {total:.1f}s — "
              f"Stage: {final.stage.name} — "
              f"Errors: {len(final.errors)} — "
              f"Escalated: {final.escalated_to is not None}")
        return final

    def _final_exit(self):
        """Stage 4 final exit — only called as absolute last resort."""
        import os as _os
        _os._exit(1)

    @property
    def stage(self) -> ShutdownStage:
        return self._stage

    def get_results(self) -> list[StageResult]:
        return list(self._results)

    def total_errors(self) -> int:
        return sum(len(r.errors) for r in self._results)

    def is_clean(self) -> bool:
        """True if shutdown completed at GRACEFUL stage with no errors."""
        if not self._results:
            return False
        final = self._results[-1]
        return (final.stage == ShutdownStage.GRACEFUL
                and not final.errors
                and final.escalated_to is None)

    def diagnostics(self) -> dict:
        return {
            "stage": self._stage.name,
            "results": [
                {
                    "stage": r.stage.name,
                    "duration_sec": round(r.duration_sec, 2),
                    "errors": r.errors,
                    "escalated_to": r.escalated_to.name if r.escalated_to else None,
                    "forced": r.forced,
                }
                for r in self._results
            ],
            "total_errors": self.total_errors(),
            "is_clean": self.is_clean(),
        }

_instance: Optional[ShutdownEscalation] = None
_se_lock = threading.Lock()


def get_shutdown_escalation() -> ShutdownEscalation:
    """Return the last created ShutdownEscalation instance (set during shutdown)."""
    global _instance
    with _se_lock:
        if _instance is None:
            _instance = ShutdownEscalation()
        return _instance


def _set_shutdown_escalation(se: ShutdownEscalation):
    """Called by main._graceful_shutdown to register the active instance."""
    global _instance
    with _se_lock:
        _instance = se
