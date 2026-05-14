# core/executor/execution_queue.py
"""
Execution queue v3 — with fairness scheduling, starvation prevention,
priority aging, queue health metrics, and action aging.
"""
from __future__ import annotations

import heapq
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum, auto
from queue import Queue, Empty
from typing import Any, Callable, Optional

log = logging.getLogger("ExecutionQueue")

DEFAULT_TIMEOUT_SEC = 8.0


class ActionPriority(Enum):
    CRITICAL = 1
    HIGH = 2
    NORMAL = 5
    LOW = 8
    BACKGROUND = 10


@dataclass
class QueuedAction:
    """An action in the priority queue with aging support."""
    priority: int
    action_id: str
    action_type: str
    payload: Any
    callback: Callable[[Any], None] | None
    error_callback: Callable[[Exception], None] | None
    created_at: float
    submitted_at: float
    timeout: float
    trace_id: str | None = None
    parent_action_id: str | None = None
    age_seconds: float = 0.0
    attempt_count: int = 0

    def __lt__(self, other: "QueuedAction") -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


@dataclass
class ExecutionFuture:
    """Promise-style future for action results."""
    action_id: str
    result: Any = None
    error: Exception | None = None
    state: str = "pending"
    started_at: float = 0.0
    completed_at: float = 0.0
    _condition: threading.Condition = field(default_factory=threading.Condition)
    _done: bool = False

    def wait(self, timeout: float | None = None) -> Any:
        with self._condition:
            if timeout is None:
                timeout = DEFAULT_TIMEOUT_SEC
            start = time.monotonic()
            remaining = timeout
            while not self._done:
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
                elapsed = time.monotonic() - start
                remaining = timeout - elapsed
        if self.error:
            raise self.error
        return self.result

    def then(self, callback: Callable[[Any], None]) -> "ExecutionFuture":
        if self._done:
            callback(self.result)
        else:
            pass
        return self

    def catch(self, callback: Callable[[Exception], None]) -> "ExecutionFuture":
        if self._done and self.error:
            callback(self.error)
        return self

    def _complete(self, result: Any = None, error: Exception | None = None):
        with self._condition:
            self.result = result
            self.error = error
            self.state = "completed" if not error else "failed"
            self.completed_at = time.time()
            self._done = True
            self._condition.notify_all()


@dataclass
class QueueHealth:
    """Queue health metrics for starvation detection."""
    starvation_counts: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    last_starvation_check: float = 0.0
    max_starvation_age: float = 60.0
    fairness_violations: int = 0
    queue_monopolized: bool = False


@dataclass
class ExecutionQueueConfig:
    max_queue_depth: int = 100
    worker_timeout: float = DEFAULT_TIMEOUT_SEC
    max_retries: int = 2
    fairness_check_interval: float = 30.0
    age_action_interval: float = 10.0
    priority_boost_per_age: float = 1.0
    max_age_boost: int = 5


class ExecutionQueue:
    """
    Priority execution queue with:
    - Dedicated worker thread
    - Fairness scheduling (prevent starvation)
    - Priority aging (lower-priority actions boost over time)
    - Queue health monitoring
    - Starvation detection
    - Rolling execution log
    """

    def __init__(self, config: ExecutionQueueConfig | None = None):
        self.config = config or ExecutionQueueConfig()
        self._queue: list[QueuedAction] = []
        self._active_actions: dict[str, QueuedAction] = {}
        self._futures: dict[str, ExecutionFuture] = {}
        self._lock = threading.RLock()
        self._not_empty = threading.Condition(self._lock)
        self._running = False
        self._worker_thread: threading.Thread | None = None
        self._execution_log: deque[dict] = deque(maxlen=500)
        self._type_counts: dict[str, int] = defaultdict(int)
        self._fallback_count: int = 0
        self._started_at: float = 0.0
        self._health = QueueHealth()
        self._last_fairness_check: float = 0.0
        self._total_executed: int = 0
        self._total_success: int = 0
        self._total_failed: int = 0
        self._total_latency_ms: float = 0.0
        self._total_runs: int = 0

    def start(self):
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="ExecQueue-Worker")
        self._worker_thread.start()
        self._schedule_fairness_monitor()

    def stop(self):
        self._running = False
        with self._lock:
            self._not_empty.notify_all()
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)

    @property
    def is_running(self) -> bool:
        return self._running

    def submit(
        self,
        action_type: str,
        payload: Any,
        priority: int = 5,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        callback: Callable[[Any], None] | None = None,
        error_callback: Callable[[Exception], None] | None = None,
        trace_id: str | None = None,
        parent_action_id: str | None = None,
    ) -> ExecutionFuture:
        action_id = str(uuid.uuid4())[:8]
        now = time.time()
        future = ExecutionFuture(action_id=action_id, started_at=now)
        with self._lock:
            action = QueuedAction(
                priority=priority,
                action_id=action_id,
                action_type=action_type,
                payload=payload,
                callback=callback,
                error_callback=error_callback,
                created_at=now,
                submitted_at=now,
                timeout=timeout,
                trace_id=trace_id,
                parent_action_id=parent_action_id,
            )
            heapq.heappush(self._queue, action)
            self._futures[action_id] = future
            self._not_empty.notify()
        return future

    def enqueue(
        self,
        action: dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT_SEC,
        priority: int | None = None,
    ) -> ExecutionFuture:
        """Backward-compatible action-dict enqueue API.

        FastRouter and DeterministicExecutor submit serialized Action objects.
        The v3 queue's native API is callable-oriented, so this adapter wraps
        action dictionaries in a small callable that executes them through the
        deterministic executor on the queue worker.
        """
        action_type = str(action.get("action_type", "UNKNOWN"))
        action_priority = int(priority if priority is not None else action.get("priority", ActionPriority.NORMAL.value))
        return self.submit(
            action_type=action_type,
            payload=lambda: self._execute_action_dict(action),
            priority=action_priority,
            timeout=timeout,
        )

    def enqueue_and_forget(
        self,
        action: dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT_SEC,
        priority: int | None = None,
    ) -> None:
        self.enqueue(action, timeout=timeout, priority=priority)

    def _execute_action_dict(self, action_data: dict[str, Any]) -> dict[str, Any]:
        from core.executor.action import Action, ActionType
        from core.executor.deterministic_executor import get_executor

        action_type_name = str(action_data.get("action_type", ""))
        action_type = ActionType[action_type_name]
        action = Action(
            action_type=action_type,
            target=str(action_data.get("target", "")),
            raw_command=str(action_data.get("raw_command", "")),
            confidence=float(action_data.get("confidence", 0.0)),
            source=str(action_data.get("source", "execution_queue")),
            priority=int(action_data.get("priority", ActionPriority.NORMAL.value)),
            params=dict(action_data.get("params", {}) or {}),
        )
        if action_data.get("action_id"):
            action.action_id = str(action_data["action_id"])

        success, message = get_executor().execute_action(action)
        return {
            "success": success,
            "message": message,
            "action": action.to_dict(),
        }

    def _worker_loop(self):
        while self._running:
            action = self._get_next_action()
            if action is None:
                continue
            self._execute_action(action)

    def _get_next_action(self) -> QueuedAction | None:
        with self._not_empty:
            while self._running and not self._queue:
                self._not_empty.wait(timeout=0.5)
                self._age_actions_locked()
            if not self._running:
                return None
            now = time.time()
            for i, a in enumerate(self._queue):
                a.age_seconds = now - a.created_at
            heapq.heapify(self._queue)
            self._queue.sort(key=lambda a: (a.priority, a.created_at))
            if self._queue:
                return heapq.heappop(self._queue)
        return None

    def _age_actions_locked(self):
        """Age lower-priority actions to prevent starvation."""
        now = time.time()
        for action in self._queue:
            age = now - action.created_at
            if age > 0 and action.priority < self.config.max_age_boost * self.config.priority_boost_per_age:
                boost = int(age / self.config.age_action_interval) * self.config.priority_boost_per_age
                boost = min(boost, self.config.max_age_boost * self.config.priority_boost_per_age)
                action.priority = max(1, action.priority - boost)
        heapq.heapify(self._queue)

    def _schedule_fairness_monitor(self):
        def monitor():
            while self._running:
                time.sleep(self.config.fairness_check_interval)
                self._check_fairness()
        t = threading.Thread(target=monitor, daemon=True, name="FairnessMonitor")
        t.start()

    def _check_fairness(self):
        """Detect starvation and queue monopolization."""
        now = time.time()
        with self._lock:
            for action in self._queue:
                age = now - action.created_at
                if age > self._health.max_starvation_age:
                    self._health.starvation_counts[action.priority] += 1
            self._health.last_starvation_check = now
            priority_counts = defaultdict(int)
            for action in list(self._queue) + list(self._active_actions.values()):
                priority_counts[action.priority] += 1
            if len(self._queue) > 20:
                max_p = max(priority_counts.values(), default=0)
                total = sum(priority_counts.values())
                if total > 0 and max_p / total > 0.8:
                    self._health.queue_monopolized = True
                    self._health.fairness_violations += 1

    def _execute_action(self, action: QueuedAction):
        now = time.time()
        with self._lock:
            self._active_actions[action.action_id] = action
            action.started_at = now
        try:
            result = action.payload() if callable(action.payload) else action.payload
            with self._lock:
                self._total_executed += 1
                self._total_success += 1
                self._total_latency_ms += (now - action.created_at) * 1000
                self._type_counts[action.action_type] += 1
            if action.callback:
                try:
                    action.callback(result)
                except Exception as e:
                    log.warning(f"[ExecQueue] callback error: {e}")
            future = self._futures.get(action.action_id)
            if future:
                future._complete(result=result)
            self._log_execution(action, "completed", result, None)
        except Exception as e:
            with self._lock:
                self._total_executed += 1
                self._total_failed += 1
                self._total_latency_ms += (now - action.created_at) * 1000
            if action.error_callback:
                try:
                    action.error_callback(e)
                except Exception:
                    pass
            future = self._futures.get(action.action_id)
            if future:
                future._complete(error=e)
            self._log_execution(action, "failed", None, str(e))
        finally:
            with self._lock:
                self._active_actions.pop(action.action_id, None)

    def _log_execution(self, action: QueuedAction, status: str, result: Any, error: str | None):
        self._execution_log.append({
            "action_id": action.action_id,
            "action_type": action.action_type,
            "priority": action.priority,
            "status": status,
            "duration_ms": round((time.time() - action.created_at) * 1000, 2),
            "result": str(result)[:100] if result else None,
            "error": error,
            "trace_id": action.trace_id,
            "parent_action_id": action.parent_action_id,
            "age_seconds": action.age_seconds,
            "timestamp": time.time(),
        })

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._total_executed
            success_rate = self._total_success / total if total > 0 else 1.0
            avg_latency = self._total_latency_ms / total if total > 0 else 0.0
            return {
                "total": total,
                "success_rate": round(success_rate, 3),
                "avg_latency_ms": round(avg_latency, 2),
                "type_counts": dict(self._type_counts),
                "fallback_rate": round(self._fallback_count / total, 3) if total > 0 else 0.0,
                "queue_depth": len(self._queue),
                "active_count": len(self._active_actions),
                "running": self._running,
                "fairness_violations": self._health.fairness_violations,
                "queue_monopolized": self._health.queue_monopolized,
                "starvation_counts": dict(self._health.starvation_counts),
                "uptime_seconds": round(time.time() - self._started_at, 1),
            }

    @property
    def active_actions(self) -> dict[str, QueuedAction]:
        with self._lock:
            return dict(self._active_actions)

    def get_log(self, last_n: int | None = None) -> list[dict]:
        with self._lock:
            log_list = list(self._execution_log)
        if last_n:
            return log_list[-last_n:]
        return log_list


def get_execution_queue() -> ExecutionQueue:
    global _execution_queue
    if _execution_queue is None:
        _execution_queue = ExecutionQueue()
    return _execution_queue

_execution_queue: ExecutionQueue | None = None
