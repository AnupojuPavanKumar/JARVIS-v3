# core/system/cancellation_token.py — JARVIS CANCELLATION TOKEN
"""
Cooperative shutdown propagation.

Every subsystem that performs init work in a background thread or deferred
callable MUST check CancellationToken.cancelled() before completing.

This replaces timing-based race guards: no subsystem continues initializing
once shutdown has been signalled.

Usage:
    token = CancellationToken("model_prewarmer")
    background_init_thread(token=token)
    # inside the thread:
    if token.cancelled():
        return  # abandon init
"""
from __future__ import annotations

import threading
from typing import Optional


class CancellationToken:
    """
    Thread-safe cancellation flag.

    One token per startup task. When cancelled():
      - all concurrent calls to cancelled() return True
      - the token owner is recorded
      - a timestamp is captured

    Subsystems MUST poll cancelled() during any init work that takes >10ms.
    """

    _global: threading.Event = threading.Event()
    _lock: threading.RLock = threading.RLock()
    _cancelled_at: Optional[float] = None
    _owner: Optional[str] = None

    def __init__(self, owner: str = "unknown"):
        self._owner = owner

    @classmethod
    def cancelled(cls) -> bool:
        """True if shutdown/cancellation has been requested."""
        return cls._global.is_set()

    def cancel(self, reason: str = ""):
        """Signal cancellation. Idempotent."""
        with self._lock:
            if not self._global.is_set():
                self._global.set()
                import time
                CancellationToken._cancelled_at = time.time()
                CancellationToken._owner = reason or self._owner
                print(f"[CancellationToken] Cancelled — reason: {reason or self._owner}")

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled()

    @classmethod
    def request_shutdown(cls, reason: str = ""):
        """Global cancellation signal — cancels ALL pending init tasks."""
        cls._global.set()
        import time
        cls._cancelled_at = time.time()
        cls._owner = reason or "shutdown"
        print(f"[CancellationToken] Global shutdown — reason: {reason or 'shutdown'}")

    @classmethod
    def reset(cls):
        """Reset for testing. NEVER call in production."""
        cls._global.clear()
        cls._cancelled_at = None
        cls._owner = None

    @classmethod
    def cancelled_at(cls) -> Optional[float]:
        return cls._cancelled_at

    @classmethod
    def cancelled_by(cls) -> Optional[str]:
        return cls._owner

    @classmethod
    def wait_until_cancelled(cls, timeout: float = None) -> bool:
        """Block until cancelled or timeout. Returns True if cancelled."""
        return cls._global.wait(timeout=timeout)

    @classmethod
    def is_shutdown_requested(cls) -> bool:
        """Alias for cancelled()."""
        return cls._global.is_set()
