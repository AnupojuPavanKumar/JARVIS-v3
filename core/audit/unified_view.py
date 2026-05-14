# core/audit/unified_view.py
"""
Unified debugging view — P9.
Single timeline: User Command → Intent → Actions → Events → Policies → Executors → Result.
Condensed execution summaries, failure root-cause extraction, automatic anomaly highlighting.
Reduces debugging complexity from dozens of disconnected logs to one coherent view.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, List, Optional

log = logging.getLogger("UnifiedDebugView")


class AnomalyLevel(Enum):
    NONE = auto()
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()


@dataclass
class DebugSpan:
    """A single span in the unified debugging timeline."""
    id: str
    layer: str
    operation: str
    start_ms: float
    end_ms: float | None = None
    status: str = "running"
    anomaly: AnomalyLevel = AnomalyLevel.NONE
    anomaly_reason: str = ""
    result: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        end = self.end_ms if self.end_ms is not None else time.time() * 1000
        return end - self.start_ms

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "layer": self.layer,
            "operation": self.operation,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "anomaly": self.anomaly.name,
            "anomaly_reason": self.anomaly_reason,
            "result": self.result[:100] if self.result else "",
            "metadata": self.metadata,
        }


@dataclass
class ExecutionSummary:
    """A complete execution summary in one view."""
    command: str
    timestamp: float
    spans: List[DebugSpan]
    total_duration_ms: float
    status: str
    anomaly_level: AnomalyLevel
    anomalies: List[str]
    root_cause: str
    human_readable: str

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "timestamp": self.timestamp,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "status": self.status,
            "anomaly_level": self.anomaly_level.name,
            "anomaly_count": len(self.anomalies),
            "root_cause": self.root_cause,
            "spans": [s.to_dict() for s in self.spans],
            "human_readable": self.human_readable,
        }

    def to_text(self) -> str:
        """Plain text summary that a human can read in 10 seconds."""
        lines = [
            f"Command: {self.command}",
            f"Duration: {self.total_duration_ms:.1f}ms",
            f"Status: {self.status}",
        ]
        if self.anomaly_level != AnomalyLevel.NONE:
            lines.append(f"Anomaly: {self.anomaly_level.name} — {self.root_cause}")
        for span in self.spans:
            icon = "OK" if span.status == "completed" and span.anomaly == AnomalyLevel.NONE else "!!" if span.anomaly != AnomalyLevel.NONE else "--"
            lines.append(f"  {icon} [{span.layer}] {span.operation}: {span.duration_ms:.1f}ms")
        if self.anomalies:
            lines.append("Anomalies:")
            for a in self.anomalies:
                lines.append(f"  - {a}")
        return "\n".join(lines)


class UnifiedDebugView:
    """
    Single unified view for human-centric debugging.
    Consolidates spans from ALL subsystems into one coherent timeline.
    Provides root-cause extraction and anomaly highlighting.
    """

    def __init__(self, max_summaries: int = 50):
        self._max_summaries = max_summaries
        self._current_command: str = ""
        self._current_spans: List[DebugSpan] = []
        self._span_counter: int = 0
        self._lock = threading.RLock()
        self._summaries: deque[ExecutionSummary] = deque(maxlen=max_summaries)
        self._anomaly_patterns: List[tuple[str, str, AnomalyLevel]] = [
            ("timeout", "Action timed out", AnomalyLevel.MEDIUM),
            ("failed", "Execution failed", AnomalyLevel.HIGH),
            ("blocked", "Action blocked by safety", AnomalyLevel.CRITICAL),
            ("queue full", "Queue capacity reached", AnomalyLevel.MEDIUM),
            ("no providers", "No AI provider available", AnomalyLevel.HIGH),
            ("rollback", "Transaction rolled back", AnomalyLevel.MEDIUM),
            ("unverifiable", "Trust level insufficient", AnomalyLevel.MEDIUM),
            ("circular", "Circular dependency detected", AnomalyLevel.HIGH),
            ("storm", "Event storm detected", AnomalyLevel.CRITICAL),
        ]
        self._anomalies_detected: List[str] = []

    def begin_command(self, command: str):
        """Begin tracking a new user command."""
        with self._lock:
            self._current_command = command
            self._current_spans = []
            self._span_counter = 0
            self._anomalies_detected = []

    def start_span(self, layer: str, operation: str, metadata: dict | None = None) -> str:
        """Start a span in the unified timeline."""
        with self._lock:
            self._span_counter += 1
            span_id = f"span-{self._span_counter:03d}"
            span = DebugSpan(
                id=span_id, layer=layer, operation=operation,
                start_ms=time.time() * 1000, metadata=metadata or {},
            )
            self._current_spans.append(span)
            return span_id

    def end_span(self, span_id: str, status: str = "completed", result: str = "", anomaly: AnomalyLevel = AnomalyLevel.NONE):
        """End a span and check for anomalies."""
        with self._lock:
            for span in self._current_spans:
                if span.id == span_id:
                    span.end_ms = time.time() * 1000
                    span.status = status
                    span.result = result
                    span.anomaly = anomaly
                    if anomaly != AnomalyLevel.NONE:
                        span.anomaly_reason = self._detect_anomaly_reason(result, span.metadata)
                        self._anomalies_detected.append(f"[{span.layer}] {span.operation}: {span.anomaly_reason}")
                    break

    def detect_span_anomaly(self, span_id: str) -> AnomalyLevel:
        """Check if a span's metadata/result indicates an anomaly."""
        with self._lock:
            for span in self._current_spans:
                if span.id == span_id:
                    result = span.result.lower()
                    metadata_str = str(span.metadata).lower()
                    combined = result + " " + metadata_str
                    for pattern, reason, level in self._anomaly_patterns:
                        if pattern in combined:
                            return level
                    return AnomalyLevel.NONE
        return AnomalyLevel.NONE

    def _detect_anomaly_reason(self, result: str, metadata: dict) -> str:
        result_lower = result.lower()
        for pattern, reason, level in self._anomaly_patterns:
            if pattern in result_lower:
                return reason
        return "Unknown anomaly"

    def end_command(self, status: str = "completed") -> ExecutionSummary:
        """Finalize the command and produce a human-readable summary."""
        with self._lock:
            spans = list(self._current_spans)
            total_ms = (time.time() * 1000 - spans[0].start_ms) if spans else 0
            max_anomaly = max((s.anomaly for s in spans), key=lambda x: x.value, default=AnomalyLevel.NONE)
            root_cause = self._extract_root_cause(spans)
            human = self._generate_human_summary(spans, total_ms, status, max_anomaly)
            summary = ExecutionSummary(
                command=self._current_command,
                timestamp=time.time(),
                spans=spans,
                total_duration_ms=total_ms,
                status=status,
                anomaly_level=max_anomaly,
                anomalies=list(self._anomalies_detected),
                root_cause=root_cause,
                human_readable=human,
            )
            self._summaries.append(summary)
            self._current_spans = []
            return summary

    def _extract_root_cause(self, spans: List[DebugSpan]) -> str:
        """Extract the root cause from the anomalous spans."""
        for span in spans:
            if span.anomaly != AnomalyLevel.NONE:
                return f"{span.layer}/{span.operation}: {span.anomaly_reason}"
        if any(s.status == "failed" for s in spans):
            failed = [s for s in spans if s.status == "failed"]
            return f"Root cause: {failed[0].layer}/{failed[0].operation}"
        if any(s.status == "timeout" for s in spans):
            return "Root cause: timeout in execution chain"
        return "No anomaly detected"

    def _generate_human_summary(
        self, spans: List[DebugSpan], total_ms: float, status: str, max_anomaly: AnomalyLevel
    ) -> str:
        """Generate a condensed human-readable summary."""
        layers = {}
        for s in spans:
            if s.layer not in layers:
                layers[s.layer] = []
            layers[s.layer].append(s)
        lines = [f"Command: \"{self._current_command}\" | {total_ms:.0f}ms | {status}"]
        if max_anomaly != AnomalyLevel.NONE:
            lines.append(f"  !! {max_anomaly.name} anomaly detected")
        for layer, layer_spans in layers.items():
            layer_time = sum(s.duration_ms for s in layer_spans)
            layer_status = "OK" if all(s.anomaly == AnomalyLevel.NONE for s in layer_spans) else "ANOMALY"
            lines.append(f"  [{layer_status}] {layer}: {layer_time:.0f}ms ({len(layer_spans)} ops)")
            for s in layer_spans:
                if s.anomaly != AnomalyLevel.NONE:
                    lines.append(f"       !! {s.operation}: {s.anomaly_reason}")
        return "\n".join(lines)

    def get_recent_summaries(self, limit: int = 10) -> List[ExecutionSummary]:
        with self._lock:
            return list(self._summaries)[-limit:]

    def get_last_summary(self) -> ExecutionSummary | None:
        with self._lock:
            return self._summaries[-1] if self._summaries else None

    def stats(self) -> dict:
        with self._lock:
            total = len(self._summaries)
            anomalies = sum(1 for s in self._summaries if s.anomaly_level != AnomalyLevel.NONE)
            by_layer = {}
            for span in (s for summ in self._summaries for s in summ.spans):
                by_layer[span.layer] = by_layer.get(span.layer, 0) + 1
            return {
                "summaries": total,
                "with_anomalies": anomalies,
                "avg_duration_ms": round(
                    sum(s.total_duration_ms for s in self._summaries) / total, 1
                ) if total > 0 else 0,
                "by_layer": by_layer,
            }


_global_debug_view: UnifiedDebugView | None = None
_dv_lock = threading.Lock()


def get_debug_view() -> UnifiedDebugView:
    global _global_debug_view
    with _dv_lock:
        if _global_debug_view is None:
            _global_debug_view = UnifiedDebugView()
        return _global_debug_view
