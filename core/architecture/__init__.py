# core/architecture/__init__.py
"""
Architecture enforcement — strict typing, protocol interfaces,
dataclass validation, architecture linting, dependency boundary checks.
Prevents circular imports, executor coupling, random cross-module access.
"""
from core.architecture.protocols import (
    ExecutorProtocol, RouterProtocol, CacheProtocol,
    SafetyProtocol, IntentScorerProtocol, PlatformAdapterProtocol,
)
from core.architecture.validation import ArchitectureValidator, ModuleBoundary

__all__ = [
    "ExecutorProtocol", "RouterProtocol", "CacheProtocol",
    "SafetyProtocol", "IntentScorerProtocol", "PlatformAdapterProtocol",
    "ArchitectureValidator", "ModuleBoundary",
]
