# core/tracing/__init__.py
"""
Execution lineage tracing — trace_id, parent_action_id, causal tracing.
Hierarchical diagnostics for command → decomposed actions → executor ops → subprocesses.
"""
from core.tracing.lineage import TraceContext, TracingSession, get_tracer, ActionSpan

__all__ = ["TraceContext", "TracingSession", "get_tracer", "ActionSpan"]
