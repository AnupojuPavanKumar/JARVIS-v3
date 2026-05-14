# core/tracing/lineage.py
"""
Execution lineage tracing — hierarchical causal chains.
trace_id + parent_action_id for full execution lineage.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional

log = logging.getLogger("Tracing")


class SpanStatus(Enum):
    STARTED = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class ActionSpan:
    """A single span in the execution trace tree."""
    span_id: str
    trace_id: str
    parent_span_id: str | None
    operation: str
    executor: str
    start_time: float
    end_time: float | None = None
    status: SpanStatus = SpanStatus.STARTED
    metadata: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    error: str | None = None

    def duration_ms(self) -> float:
        if self.end_time is None:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000

    def add_event(self, name: str, data: dict | None = None):
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "data": data or {},
        })

    def complete(self, status: SpanStatus = SpanStatus.COMPLETED, error: str | None = None):
        self.end_time = time.time()
        self.status = status
        self.error = error

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "operation": self.operation,
            "executor": self.executor,
            "duration_ms": round(self.duration_ms(), 2),
            "status": self.status.name,
            "metadata": self.metadata,
            "events": self.events,
            "error": self.error,
            "start": datetime.fromtimestamp(self.start_time).strftime("%H:%M:%S.%f")[:-3],
        }


@dataclass
class TraceContext:
    """Carries trace context through the execution chain."""
    trace_id: str
    parent_action_id: str | None = None
    parent_span_id: str | None = None
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def new(parent: TraceContext | None = None) -> TraceContext:
        """Create a new trace context, optionally inheriting from parent."""
        trace_id = str(uuid.uuid4())[:8]
        parent_id = None
        parent_span = None
        meta = {}
        if parent:
            trace_id = f"{parent.trace_id}.{trace_id.split('.')[0]}"
            parent_id = parent.parent_action_id
            parent_span = parent.parent_span_id
            meta = dict(parent.metadata)
        return TraceContext(
            trace_id=trace_id,
            parent_action_id=parent_id,
            parent_span_id=parent_span,
            metadata=meta,
        )


@dataclass
class TracingSession:
    """A tracing session containing all spans for a single user command."""
    trace_id: str
    root_command: str
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    spans: list[ActionSpan] = field(default_factory=list)
    status: SpanStatus = SpanStatus.RUNNING
    metadata: dict = field(default_factory=dict)

    def add_span(self, span: ActionSpan):
        self.spans.append(span)

    def complete(self, status: SpanStatus = SpanStatus.COMPLETED):
        self.end_time = time.time()
        self.status = status

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "root_command": self.root_command,
            "duration_ms": round((self.end_time or time.time()) - self.start_time, 2) * 1000,
            "status": self.status.name,
            "span_count": len(self.spans),
            "spans": [s.to_dict() for s in self.spans],
        }


class Tracing:
    """
    Tracing system for execution lineage.
    Maintains trace trees, manages span lifecycle, stores recent traces.
    Thread-safe, non-blocking.
    """

    def __init__(self, max_traces: int = 100):
        self._max_traces = max_traces
        self._traces: dict[str, TracingSession] = {}
        self._current_span: dict[str, ActionSpan] = {}
        self._lock = threading.RLock()
        self._trace_counter = 0

    def start_trace(self, root_command: str, metadata: dict | None = None) -> TraceContext:
        """Start a new tracing session for a root command."""
        with self._lock:
            self._trace_counter += 1
            trace_id = f"trace-{self._trace_counter:04d}-{str(uuid.uuid4())[:8]}"
            session = TracingSession(
                trace_id=trace_id,
                root_command=root_command,
                metadata=metadata or {},
            )
            self._traces[trace_id] = session
            if len(self._traces) > self._max_traces:
                oldest = min(self._traces.keys())
                del self._traces[oldest]
        ctx = TraceContext(trace_id=trace_id, metadata=metadata or {})
        return ctx

    def start_span(
        self,
        ctx: TraceContext,
        operation: str,
        executor: str,
        parent_span_id: str | None = None,
        metadata: dict | None = None,
    ) -> ActionSpan:
        """Start a new span within the current trace."""
        with self._lock:
            span_id = str(uuid.uuid4())[:8]
            span = ActionSpan(
                span_id=span_id,
                trace_id=ctx.trace_id,
                parent_span_id=parent_span_id or ctx.parent_span_id,
                operation=operation,
                executor=executor,
                start_time=time.time(),
                metadata=metadata or {},
            )
            if ctx.trace_id in self._traces:
                self._traces[ctx.trace_id].add_span(span)
            self._current_span[ctx.trace_id] = span
        return span

    def end_span(self, ctx: TraceContext, span: ActionSpan, status: SpanStatus = SpanStatus.COMPLETED, error: str | None = None):
        """End a span."""
        span.complete(status=status, error=error)
        with self._lock:
            self._current_span.pop(ctx.trace_id, None)

    def end_trace(self, ctx: TraceContext, status: SpanStatus = SpanStatus.COMPLETED):
        """End the entire tracing session."""
        with self._lock:
            if ctx.trace_id in self._traces:
                self._traces[ctx.trace_id].complete(status=status)
            self._current_span.pop(ctx.trace_id, None)

    def get_trace(self, trace_id: str) -> TracingSession | None:
        with self._lock:
            return self._traces.get(trace_id)

    def recent_traces(self, limit: int = 10) -> list[TracingSession]:
        with self._lock:
            traces = sorted(self._traces.values(), key=lambda t: t.start_time, reverse=True)
            return traces[:limit]

    def stats(self) -> dict:
        with self._lock:
            total = len(self._traces)
            completed = sum(1 for t in self._traces.values() if t.status == SpanStatus.COMPLETED)
            failed = sum(1 for t in self._traces.values() if t.status == SpanStatus.FAILED)
            running = sum(1 for t in self._traces.values() if t.status == SpanStatus.RUNNING)
            total_spans = sum(len(t.spans) for t in self._traces.values())
            return {
                "total_traces": total,
                "completed": completed,
                "failed": failed,
                "running": running,
                "total_spans": total_spans,
                "max_traces": self._max_traces,
            }


_global_tracer: Tracing | None = None
_tracer_lock = threading.Lock()


def get_tracer() -> Tracing:
    global _global_tracer
    with _tracer_lock:
        if _global_tracer is None:
            _global_tracer = Tracing()
        return _global_tracer
