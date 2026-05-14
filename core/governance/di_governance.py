# core/governance/di_governance.py
"""
DI governance — P4.
Max dependency depth, unused service detection, service lifecycle diagnostics.
Prevents factory explosion, over-abstraction, service bloat.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("DIGoverner")


@dataclass
class DIGovernerConfig:
    max_dependency_depth: int = 5
    max_service_count: int = 50
    unused_threshold_days: float = 7.0
    scan_interval_sec: float = 300.0


class DIGoverner:
    """
    Service container governance.
    Monitors dependency depth, detects unused services,
    provides service lifecycle diagnostics.
    """

    def __init__(self, config: DIGovernerConfig | None = None):
        self.config = config or DIGovernerConfig()
        self._service_stats: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._unused_services: list[str] = []
        self._circular_deps: list[list[str]] = []
        self._max_depth_seen: int = 0

    def analyze(self, container) -> dict:
        """Analyze a service container for governance issues."""
        if not hasattr(container, "_services") and not hasattr(container, "_instances"):
            return {}
        result = {}
        with self._lock:
            if hasattr(container, "list_services"):
                services = container.list_services()
                result["service_count"] = len(services)
                result["initialized_count"] = len([
                    s for s in services if container.is_initialized(s)
                ])
                result["unused_services"] = []
                result["max_depth_seen"] = self._max_depth_seen
                if len(services) > self.config.max_service_count:
                    result["over_limit"] = len(services) - self.config.max_service_count
                    log.warning(f"[DIGoverner] Service count exceeds limit: {len(services)}/{self.config.max_service_count}")
            if hasattr(container, "_creation_count"):
                creation_counts = container._creation_count
                transient = [s for s in services if creation_counts.get(s, 0) > 5]
                if transient:
                    result["frequently_created"] = transient
        return result

    def check_dependency_depth(self, container, service_name: str, current_depth: int = 0) -> tuple[bool, int]:
        """Check if a service's dependency depth exceeds the limit."""
        if current_depth >= self.config.max_dependency_depth:
            with self._lock:
                self._max_depth_seen = max(self._max_depth_seen, current_depth)
            return False, current_depth
        try:
            deps = container.resolve_dependencies(service_name)
            for dep_name, dep_instance in deps.items():
                valid, depth = self.check_dependency_depth(container, dep_name, current_depth + 1)
                if not valid:
                    return False, depth
        except (KeyError, RuntimeError, AttributeError):
            pass
        return True, current_depth

    def detect_circular(self, container) -> list[list[str]]:
        """Detect circular dependencies."""
        cycles = []
        with self._lock:
            if hasattr(container, "_services"):
                services = list(container._services.keys())
        for service in services:
            try:
                deps = container.resolve_dependencies(service)
                visited = {service}
                path = [service]
                detected = self._dfs_detect_cycle(container, service, visited, path)
                if detected:
                    cycles.append(detected)
            except Exception:
                pass
        with self._lock:
            self._circular_deps = cycles
        return cycles

    def _dfs_detect_cycle(self, container, current: str, visited: set, path: list) -> list[str] | None:
        try:
            deps = container.resolve_dependencies(current)
            for dep in deps:
                if dep in visited:
                    idx = path.index(dep)
                    return path[idx:] + [dep]
                visited.add(dep)
                path.append(dep)
                result = self._dfs_detect_cycle(container, dep, visited, path)
                if result:
                    return result
                path.pop()
        except (KeyError, RuntimeError, AttributeError):
            pass
        return None

    def detect_unused_services(self, container) -> list[str]:
        """Detect services that haven't been initialized recently."""
        unused = []
        cutoff = time.time() - self.config.unused_threshold_days * 86400
        with self._lock:
            if hasattr(container, "_creation_count"):
                for name in container.list_services():
                    if container.is_initialized(name):
                        continue
                    last_init = container._creation_count.get(name, 0)
                    if last_init > 0 and last_init < cutoff:
                        unused.append(name)
            self._unused_services = unused
        return unused

    def stats(self) -> dict:
        return {
            "max_depth_limit": self.config.max_dependency_depth,
            "max_depth_seen": self._max_depth_seen,
            "circular_deps": len(self._circular_deps),
            "unused_services": len(self._unused_services),
            "max_service_count": self.config.max_service_count,
        }


_global_di_governor: DIGoverner | None = None
_di_lock = threading.Lock()


def get_di_governor() -> DIGoverner:
    global _global_di_governor
    with _di_lock:
        if _global_di_governor is None:
            _global_di_governor = DIGoverner()
        return _global_di_governor
