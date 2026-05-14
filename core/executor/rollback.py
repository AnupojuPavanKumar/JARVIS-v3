# core/executor/rollback.py
"""
Transactional action chains with rollback support.
Compensating actions, failure recovery, partial execution recovery.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

log = logging.getLogger("RollbackExecutor")


class TransactionStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    ROLLED_BACK = auto()
    FAILED = auto()
    PARTIAL = auto()


@dataclass
class TransactionStep:
    """A single step in a transactional chain."""
    step_id: str
    name: str
    execute_fn: Callable[[], Any]
    rollback_fn: Callable[[], None] | None = None
    timeout: float = 30.0
    retry_count: int = 0
    max_retries: int = 2
    status: str = "pending"
    error: str | None = None
    result: Any = None
    executed_at: float | None = None
    rolled_back_at: float | None = None


@dataclass
class Transaction:
    """A transactional execution chain with rollback support."""
    tx_id: str
    name: str
    steps: list[TransactionStep] = field(default_factory=list)
    status: TransactionStatus = TransactionStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    error: str | None = None
    rollback_log: list[dict] = field(default_factory=list)

    def add_step(self, step: TransactionStep):
        self.steps.append(step)

    def is_complete(self) -> bool:
        return self.status in (TransactionStatus.COMPLETED, TransactionStatus.ROLLED_BACK, TransactionStatus.FAILED)


class TransactionExecutor:
    """
    Execute action chains with transactional rollback.
    If any step fails, all previous steps are rolled back in reverse order.
    """

    def __init__(self):
        self._transactions: dict[str, Transaction] = {}
        self._lock = threading.RLock()
        self._history: deque[Transaction] = deque(maxlen=100)

    def create(self, name: str) -> Transaction:
        """Create a new transaction."""
        tx_id = str(uuid.uuid4())[:8]
        tx = Transaction(tx_id=tx_id, name=name)
        with self._lock:
            self._transactions[tx_id] = tx
        return tx

    def add_step(
        self,
        tx: Transaction,
        name: str,
        execute_fn: Callable[[], Any],
        rollback_fn: Callable[[], None] | None = None,
        timeout: float = 30.0,
    ) -> TransactionStep:
        """Add a step to a transaction."""
        step = TransactionStep(
            step_id=str(uuid.uuid4())[:8],
            name=name,
            execute_fn=execute_fn,
            rollback_fn=rollback_fn,
            timeout=timeout,
        )
        tx.add_step(step)
        return step

    def execute(self, tx: Transaction) -> Transaction:
        """Execute all steps in order. Roll back on failure."""
        tx.status = TransactionStatus.RUNNING
        executed: list[TransactionStep] = []
        try:
            for step in tx.steps:
                step.executed_at = time.time()
                try:
                    step.result = step.execute_fn()
                    step.status = "completed"
                    executed.append(step)
                except Exception as e:
                    step.status = "failed"
                    step.error = str(e)
                    log.warning(f"[TransactionExecutor] Step '{step.name}' failed: {e}")
                    self._rollback_steps(tx, executed, step)
                    tx.status = TransactionStatus.ROLLED_BACK
                    tx.error = f"Step '{step.name}' failed: {e}"
                    tx.completed_at = time.time()
                    with self._lock:
                        self._history.append(tx)
                    return tx
            tx.status = TransactionStatus.COMPLETED
            tx.completed_at = time.time()
        except Exception as e:
            tx.status = TransactionStatus.FAILED
            tx.error = str(e)
            tx.completed_at = time.time()
        with self._lock:
            self._history.append(tx)
        return tx

    def _rollback_steps(self, tx: Transaction, executed: list[TransactionStep], failed_step: TransactionStep):
        """Roll back all executed steps in reverse order."""
        for step in reversed(executed):
            if step.rollback_fn is None:
                tx.rollback_log.append({
                    "step": step.name,
                    "status": "skipped",
                    "reason": "no rollback function defined",
                })
                continue
            try:
                step.rollback_fn()
                step.rolled_back_at = time.time()
                step.status = "rolled_back"
                tx.rollback_log.append({
                    "step": step.name,
                    "status": "success",
                })
                log.info(f"[TransactionExecutor] Rolled back step: {step.name}")
            except Exception as e:
                step.status = "rollback_failed"
                tx.rollback_log.append({
                    "step": step.name,
                    "status": "failed",
                    "error": str(e),
                })
                log.error(f"[TransactionExecutor] Rollback failed for step '{step.name}': {e}")

    def get_transaction(self, tx_id: str) -> Transaction | None:
        with self._lock:
            return self._transactions.get(tx_id)

    def recent_transactions(self, limit: int = 10) -> list[Transaction]:
        with self._lock:
            return list(self._history)[-limit:]

    def stats(self) -> dict:
        with self._lock:
            total = len(self._history)
            completed = sum(1 for t in self._history if t.status == TransactionStatus.COMPLETED)
            rolled_back = sum(1 for t in self._history if t.status == TransactionStatus.ROLLED_BACK)
            failed = sum(1 for t in self._history if t.status == TransactionStatus.FAILED)
            return {
                "total": total,
                "completed": completed,
                "rolled_back": rolled_back,
                "failed": failed,
                "active": len(self._transactions),
            }


_tx_executor: TransactionExecutor | None = None


def get_transaction_executor() -> TransactionExecutor:
    global _tx_executor
    if _tx_executor is None:
        _tx_executor = TransactionExecutor()
    return _tx_executor
