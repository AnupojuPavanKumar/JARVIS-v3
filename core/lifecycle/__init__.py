# core/lifecycle/__init__.py
"""
Lifecycle subsystems for JARVIS.
  - RuntimeLifecycle (core/system/runtime_lifecycle.py): centralized ownership authority
  - LifecycleController (core/lifecycle/controller.py): legacy phase-based coordinator
"""
from core.lifecycle.controller import LifecycleController, LifecyclePhase, get_lifecycle_controller
from core.system.runtime_lifecycle import RuntimeLifecycle, get_runtime_lifecycle

__all__ = [
    "RuntimeLifecycle", "get_runtime_lifecycle",
    "LifecycleController", "LifecyclePhase", "get_lifecycle_controller",
]
