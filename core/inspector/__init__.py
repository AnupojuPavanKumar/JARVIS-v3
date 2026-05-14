# core/inspector/__init__.py
"""
Runtime graph inspector — P1.
Live action graph, event propagation tree, subscriber chain viewer,
execution dependency graph, rollback visualization, action lineage inspection.
Lightweight, debug-mode only, non-blocking.
"""
from core.inspector.graph import RuntimeGraphInspector, get_inspector

__all__ = ["RuntimeGraphInspector", "get_inspector"]
