import threading
import concurrent.futures
import logging
from typing import Callable, Any, Optional

log = logging.getLogger("ThreadManager")

# ── Global cooperative shutdown signal ──────────────────────────────────────
# All long-running background loops should check this event periodically.
# Call request_shutdown() to signal all threads to exit gracefully.
_SHUTDOWN_EVENT = threading.Event()
_DRAIN_EVENT    = threading.Event()  # set by workers when they finish

def request_shutdown():
    """Signal all managed background threads to exit their loops."""
    _SHUTDOWN_EVENT.set()
    log.info("[ThreadManager] Shutdown requested — all workers notified.")

def signal_drained():
    """Workers call this when they have exited their loops."""
    _DRAIN_EVENT.set()

def reset_for_restart():
    """Reset shutdown events for a new session (after graceful shutdown)."""
    _SHUTDOWN_EVENT.clear()
    _DRAIN_EVENT.clear()
    log.info("[ThreadManager] Reset for restart - events cleared.")

def wait_for_shutdown(timeout: float = 3.0) -> bool:
    """Block until the shutdown event fires or the timeout expires."""
    return _SHUTDOWN_EVENT.wait(timeout=timeout)

def is_shutdown_requested() -> bool:
    """Non-blocking check — returns True if shutdown has been requested."""
    return _SHUTDOWN_EVENT.is_set()

class ThreadManager:
    """
    Central manager for background threads in JARVIS-v3.
    Replaces raw threading.Thread calls with a managed pool and 
    provides lifecycle tracking.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ThreadManager, cls).__new__(cls)
                cls._instance._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=20, 
                    thread_name_prefix="JARVIS-Worker"
                )
                cls._instance._active_threads = {}
        return cls._instance

    def run_in_background(self, target: Callable, args: tuple = (), kwargs: dict = None, name: Optional[str] = None) -> concurrent.futures.Future:
        """
        Execute a function in the background thread pool.
        Ensures COM is initialized for the thread.
        """
        if kwargs is None:
            kwargs = {}
        
        def _wrapper(*a, **kw):
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except (ImportError, OSError):
                pass   # pythoncom unavailable on Linux/Mac — expected
            try:
                return target(*a, **kw)
            finally:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except (ImportError, OSError):
                    pass   # pythoncom unavailable on Linux/Mac — expected
        
        future = self._executor.submit(_wrapper, *args, **kwargs)
        if name:
            self._active_threads[name] = future
            future.add_done_callback(lambda f: self._active_threads.pop(name, None))
        
        return future

    def shutdown(self, wait=True, timeout: float = 3.0):
        """Signal shutdown, wait for workers to drain, then shut down the pool."""
        log.info("[ThreadManager] Shutting down thread pool...")
        request_shutdown()
        if wait:
            # Wait on the drain event (set by workers), not the signal we just set
            _DRAIN_EVENT.wait(timeout=timeout)
        self._executor.shutdown(wait=wait)

def get_thread_manager() -> ThreadManager:
    return ThreadManager()
