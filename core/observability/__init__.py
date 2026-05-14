# core/observability/__init__.py
"""
Pipeline visualization & diagnostics hooks.
Lightweight, non-blocking, debug-mode only developer diagnostics.
"""
from core.observability.dashboard import PipelineDiagnostics, get_diagnostics

__all__ = ["PipelineDiagnostics", "get_diagnostics"]
