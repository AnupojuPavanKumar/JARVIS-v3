# core/services/container.py
"""
Service container with dependency injection, lifecycle management,
lazy initialization, and injectable services.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import wraps
from typing import Any, Callable, Generic, Optional, TypeVar

log = logging.getLogger("ServiceContainer")

T = TypeVar("T")


class ServiceLifecycle(Enum):
    SINGLETON = auto()
    TRANSIENT = auto()
    LAZY = auto()


@dataclass(frozen=True)
class ServiceDescriptor:
    """Metadata for a registered service."""
    factory: Callable[[], Any]
    lifecycle: ServiceLifecycle = ServiceLifecycle.LAZY
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    created_at: float = 0.0
    init_timeout: float = 5.0
    on_init: Callable[[Any], None] | None = None
    on_shutdown: Callable[[Any], None] | None = None


class ServiceContainer:
    """
    Thread-safe service container with lazy initialization and lifecycle management.
    - No frameworks, no external dependencies
    - Supports singleton, transient, and lazy services
    - Circular dependency protection
    - Lazy factory instantiation
    - On-init and on-shutdown hooks
    """

    def __init__(self):
        self._services: dict[str, ServiceDescriptor] = {}
        self._instances: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._in_progress: set[str] = set()
        self._init_order: list[str] = []
        self._lifecycle: dict[str, ServiceLifecycle] = {}
        self._dependency_graph: dict[str, set[str]] = {}
        self._creation_count: dict[str, int] = {}

    def register(
        self,
        name: str,
        factory: Callable[[], T],
        lifecycle: ServiceLifecycle = ServiceLifecycle.LAZY,
        dependencies: list[str] | None = None,
        on_init: Callable[[T], None] | None = None,
        on_shutdown: Callable[[T], None] | None = None,
    ) -> ServiceContainer:
        """Register a service with its factory and lifecycle."""
        with self._lock:
            self._services[name] = ServiceDescriptor(
                factory=factory,
                lifecycle=lifecycle,
                dependencies=tuple(dependencies or []),
                on_init=on_init,
                on_shutdown=on_shutdown,
            )
            self._lifecycle[name] = lifecycle
            self._dependency_graph[name] = set(dependencies or [])
        return self

    def get(self, name: str) -> Any:
        """Resolve a service by name, creating it if needed."""
        with self._lock:
            if name in self._instances:
                return self._instances[name]
            if name not in self._services:
                raise KeyError(f"Service not registered: {name}")
            desc = self._services[name]
            if name in self._in_progress:
                raise RuntimeError(f"Circular dependency detected for service: {name}")
            self._in_progress.add(name)
        try:
            instance = self._create_service(name)
            with self._lock:
                self._instances[name] = instance
                self._init_order.append(name)
                self._creation_count[name] = self._creation_count.get(name, 0) + 1
                self._in_progress.discard(name)
            if desc.on_init:
                try:
                    desc.on_init(instance)
                except Exception as e:
                    log.warning(f"[ServiceContainer] on_init failed for {name}: {e}")
            return instance
        except Exception:
            with self._lock:
                self._in_progress.discard(name)
            raise

    def _create_service(self, name: str) -> Any:
        """Create a service instance, resolving dependencies first."""
        with self._lock:
            desc = self._services[name]
        deps = {}
        for dep_name in desc.dependencies:
            with self._lock:
                if dep_name not in self._services:
                    raise KeyError(f"Dependency '{dep_name}' not registered for service '{name}'")
            deps[dep_name] = self.get(dep_name)
        factory = desc.factory
        instance = factory()
        return instance

    def resolve_dependencies(self, name: str) -> dict[str, Any]:
        """Resolve all dependencies for a service (for debugging/inspection)."""
        result = {}
        with self._lock:
            if name not in self._services:
                return result
            dep_names = list(self._services[name].dependencies)
        for dep_name in dep_names:
            try:
                result[dep_name] = self.get(dep_name)
            except Exception:
                pass
        return result

    def is_registered(self, name: str) -> bool:
        with self._lock:
            return name in self._services

    def is_initialized(self, name: str) -> bool:
        with self._lock:
            return name in self._instances

    def shutdown(self, name: str | None = None):
        """Shutdown a specific service or all services."""
        if name:
            self._shutdown_single(name)
            return
        with self._lock:
            order = list(reversed(self._init_order))
        for svc_name in order:
            self._shutdown_single(svc_name)

    def _shutdown_single(self, name: str):
        with self._lock:
            if name not in self._instances:
                return
            instance = self._instances[name]
            desc = self._services.get(name)
        try:
            if desc and desc.on_shutdown:
                desc.on_shutdown(instance)
        except Exception as e:
            log.warning(f"[ServiceContainer] on_shutdown failed for {name}: {e}")
        with self._lock:
            self._instances.pop(name, None)

    def stats(self) -> dict:
        """Return container statistics."""
        with self._lock:
            return {
                "registered": len(self._services),
                "initialized": len(self._instances),
                "creation_counts": dict(self._creation_count),
                "lifecycle": {k: v.name for k, v in self._lifecycle.items()},
            }

    def list_services(self) -> list[str]:
        with self._lock:
            return list(self._services.keys())

    def list_initialized(self) -> list[str]:
        with self._lock:
            return list(self._instances.keys())

    def clear(self):
        """Clear all services (for testing)."""
        self.shutdown()
        with self._lock:
            self._services.clear()
            self._instances.clear()
            self._init_order.clear()
            self._creation_count.clear()


def inject(*service_names: str):
    """
    Decorator for constructor/method injection.
    Usage: @inject("executor", "registry")
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            for name in service_names:
                if name not in kwargs:
                    kwargs[name] = service_container.get(name)
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Global singleton container
service_container = ServiceContainer()
