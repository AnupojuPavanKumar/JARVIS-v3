import threading
import logging
import time
from typing import Dict, Any, Optional, Callable, List

log = logging.getLogger("ServiceRegistry")

class ServiceRegistry:
    """
    Central orchestrator for JARVIS-v3 services.
    """
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ServiceRegistry, cls).__new__(cls)
                cls._instance._services: Dict[str, Dict[str, Any]] = {}
                cls._instance._ready_events: Dict[str, threading.Event] = {}
        return cls._instance

    def register(self, name: str, instance: Any, start_fn: Optional[Callable] = None, stop_fn: Optional[Callable] = None):
        with self._lock:
            if name in self._services:
                # Update instance but preserve ready state
                self._services[name]["instance"] = instance
                self._services[name]["start"] = start_fn or getattr(instance, 'start', None)
                self._services[name]["stop"] = stop_fn or getattr(instance, 'stop', None)
                log.debug(f"[Registry] Re-registered '{name}' — instance updated.")
                return
            self._services[name] = {
                "instance": instance,
                "start": start_fn or getattr(instance, 'start', None),
                "stop": stop_fn or getattr(instance, 'stop', None),
                "status": "registered"
            }
            self._ready_events[name] = threading.Event()

    def get(self, name: str) -> Any:
        with self._lock:
            return self._services.get(name, {}).get("instance")

    def mark_ready(self, name: str):
        with self._lock:
            if name in self._ready_events:
                self._ready_events[name].set()
            if name in self._services:
                self._services[name]["status"] = "running"

    def is_ready(self, name: str) -> bool:
        with self._lock:
            ev = self._ready_events.get(name)
        return ev.is_set() if ev else False

    def wait_for(self, name: str, timeout: Optional[float] = None) -> bool:
        deadline = time.time() + (timeout or float("inf"))

        # Wait for registration — check under lock to avoid race
        while True:
            with self._lock:
                ev = self._ready_events.get(name)
            if ev is not None:
                break
            if time.time() >= deadline:
                return False
            time.sleep(0.05)

        remaining = max(0.01, deadline - time.time()) if timeout else None
        return ev.wait(timeout=remaining)

    def wait_for_services(self, names: List[str], timeout: Optional[float] = None) -> bool:
        start_time = time.time()
        for name in names:
            remaining = max(0.01, timeout - (time.time() - start_time)) if timeout else None
            if not self.wait_for(name, timeout=remaining):
                log.warning(f"[Registry] Timeout waiting for '{name}'")
                return False
        return True

    def start_service(self, name: str):
        with self._lock:
            if name not in self._services:
                log.warning(f"[Registry] Service '{name}' not found.")
                return
            service_info = self._services[name]

        if service_info["status"] == "running":
            return

        start_fn = service_info["start"]
        if start_fn:
            try:
                log.info(f"[Registry] Starting {name}...")
                start_fn()
                if service_info["status"] == "registered":
                    service_info["status"] = "running"
                    self.mark_ready(name)
            except Exception as e:
                service_info["status"] = "error"
                log.error(f"[Registry] Failed to start {name}: {e}")
        else:
            service_info["status"] = "running"
            self.mark_ready(name)

    def start_all(self):
        with self._lock:
            names = list(self._services.keys())
        for name in names:
            self.start_service(name)

    def stop_service(self, name: str):
        with self._lock:
            if name not in self._services:
                return
            service_info = self._services[name]

        if service_info.get("status") == "stopped":
            return

        stop_fn = service_info["stop"]
        if stop_fn:
            try:
                log.info(f"[Registry] Stopping {name}...")
                stop_fn()
            except Exception as e:
                log.warning(f"[Registry] Error stopping {name}: {e}")
        service_info["status"] = "stopped"
        with self._lock:
            ev = self._ready_events.get(name)
            if ev:
                ev.clear()

    def stop_all(self):
        log.info("[Registry] Shutting down all services...")
        with self._lock:
            names = list(self._services.keys())
        for name in reversed(names):
            self.stop_service(name)

    def resolve(self, name: str, timeout: Optional[float] = 10.0) -> Any:
        if not self.wait_for(name, timeout=timeout):
            log.error(f"[Registry] Dependency '{name}' timeout.")
            return None
        return self.get(name)


def get_service_registry() -> ServiceRegistry:
    return ServiceRegistry()
