# core/architecture/validation.py
"""
Architecture validation — module boundary enforcement,
circular import detection, dependency boundary checks.
"""
from __future__ import annotations

import importlib
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto

log = logging.getLogger("ArchValidator")


class BoundaryViolation(Enum):
    CIRCULAR_IMPORT = auto()
    CROSS_MODULE_ACCESS = auto()
    PROTOCOL_VIOLATION = auto()
    TYPE_MISMATCH = auto()


@dataclass
class ModuleBoundary:
    """Defines allowed imports between modules."""
    module: str
    allowed_imports: list[str] = field(default_factory=list)
    blocked_imports: list[str] = field(default_factory=list)


ALLOWED_BOUNDARIES: list[ModuleBoundary] = [
    ModuleBoundary("core.executor", allowed_imports=["core.platform", "core.services"]),
    ModuleBoundary("core.intents", allowed_imports=["core.apps", "core.resource"]),
    ModuleBoundary("core.router", allowed_imports=["core.intents", "core.executor", "core.resource"]),
    ModuleBoundary("core.services", allowed_imports=[]),
    ModuleBoundary("core.events", allowed_imports=["core.tracing"]),
    ModuleBoundary("core.resource", allowed_imports=["core.platform"]),
    ModuleBoundary("core.capabilities", allowed_imports=["core.platform", "core.apps"]),
]


class ArchitectureValidator:
    """
    Validates architecture boundaries and detects violations.
    Checks module boundaries, circular imports, protocol compliance.
    """

    def __init__(self):
        self._violations: list[dict] = []
        self._lock = threading.RLock()
        self._import_graph: dict[str, set[str]] = defaultdict(set)
        self._boundary_map: dict[str, ModuleBoundary] = {b.module: b for b in ALLOWED_BOUNDARIES}

    def record_import(self, importer: str, imported: str):
        """Record an import relationship for validation."""
        with self._lock:
            self._import_graph[importer].add(imported)

    def check_circular_imports(self, module: str) -> list[list[str]]:
        """Detect circular import chains starting from a module."""
        visited: set[str] = set()
        path: list[str] = []
        cycles: list[list[str]] = []

        def dfs(current: str, path: list[str]):
            if current in path:
                idx = path.index(current)
                cycles.append(path[idx:] + [current])
                return
            if current in visited:
                return
            visited.add(current)
            path.append(current)
            for dep in self._import_graph.get(current, []):
                dfs(dep, list(path))
            path.pop()

        dfs(module, [])
        return cycles

    def check_boundary(self, importer: str, imported: str) -> bool:
        """Check if an import respects module boundaries."""
        boundary = self._boundary_map.get(importer)
        if not boundary:
            return True
        if boundary.blocked_imports:
            for blocked in boundary.blocked_imports:
                if imported.startswith(blocked):
                    return False
        if boundary.allowed_imports:
            for allowed in boundary.allowed_imports:
                if imported.startswith(allowed):
                    return True
            return False
        return True

    def validate_protocol(
        self, instance: Any, protocol_class: type, protocol_name: str
    ) -> tuple[bool, str]:
        """Check if an instance implements a protocol."""
        try:
            if isinstance(instance, type(protocol_class)):
                return True, f"{protocol_name} implemented"
            return False, f"{protocol_name} NOT implemented by {type(instance).__name__}"
        except Exception as e:
            return False, f"Protocol check error: {e}"

    def record_violation(self, violation_type: BoundaryViolation, details: str):
        """Record a boundary violation."""
        import time
        with self._lock:
            self._violations.append({
                "type": violation_type.name,
                "details": details,
                "timestamp": time.time(),
            })

    def get_violations(self) -> list[dict]:
        with self._lock:
            return list(self._violations)

    def clear_violations(self):
        with self._lock:
            self._violations.clear()

    def stats(self) -> dict:
        with self._lock:
            by_type = defaultdict(int)
            for v in self._violations:
                by_type[v["type"]] += 1
            return {
                "total_violations": len(self._violations),
                "by_type": dict(by_type),
                "module_count": len(self._import_graph),
            }


_global_validator: ArchitectureValidator | None = None
_val_lock = threading.Lock()


def get_architecture_validator() -> ArchitectureValidator:
    global _global_validator
    with _val_lock:
        if _global_validator is None:
            _global_validator = ArchitectureValidator()
        return _global_validator
