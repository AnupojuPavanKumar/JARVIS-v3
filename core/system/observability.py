import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

log = logging.getLogger("Observability")

class TraceEvent(BaseModel):
    timestamp: float = Field(default_factory=time.time)
    component: str  # e.g., "agent", "memory", "tool", "vram"
    event_type: str # e.g., "decision", "failure", "retrieval", "execution"
    action: str
    rationale: str  # The "WHY"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ObservabilityEngine:
    """
    Phase 7: System Observability
    Provides complete transparency into system decisions, tool executions,
    memory retrievals, and failure diagnostics. No black-box execution.
    """
    def __init__(self, log_dir: str = "logs/observability"):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.trace_log_path = os.path.join(self.log_dir, f"trace_{int(time.time())}.jsonl")
        self._active_timeline: List[TraceEvent] = []

    def log_decision(self, component: str, action: str, rationale: str, metadata: dict = None):
        """Records WHY an action was chosen."""
        self._record_event(TraceEvent(
            component=component,
            event_type="decision",
            action=action,
            rationale=rationale,
            metadata=metadata or {}
        ))

    def log_memory_retrieval(self, query: str, retrieved_tags: List[str], rationale: str):
        """Records WHY specific memories were retrieved."""
        self._record_event(TraceEvent(
            component="memory",
            event_type="retrieval",
            action=f"query: {query}",
            rationale=rationale,
            metadata={"tags": retrieved_tags}
        ))

    def log_tool_execution(self, tool_name: str, success: bool, rationale: str, duration_ms: int):
        """Records WHY a tool was selected and its execution outcome."""
        self._record_event(TraceEvent(
            component="tool",
            event_type="execution",
            action=tool_name,
            rationale=rationale,
            metadata={"success": success, "duration_ms": duration_ms}
        ))

    def log_failure(self, component: str, operation: str, error: str, rationale: str):
        """Records WHY a failure occurred and context surrounding it."""
        self._record_event(TraceEvent(
            component=component,
            event_type="failure",
            action=operation,
            rationale=rationale,
            metadata={"error": error}
        ))

    def log_vram_usage(self, model_name: str, pct_used: float, rationale: str = "Periodic VRAM check"):
        """Records VRAM state and tracking."""
        self._record_event(TraceEvent(
            component="vram",
            event_type="telemetry",
            action=f"Model: {model_name}",
            rationale=rationale,
            metadata={"vram_pct": pct_used}
        ))

    def _record_event(self, event: TraceEvent):
        """Writes the event to the timeline and persists it to disk."""
        self._active_timeline.append(event)
        
        # Log to console for active debugging
        log_msg = f"[{event.component.upper()}] {event.action} | WHY: {event.rationale}"
        if event.event_type == "failure":
            log.error(log_msg)
        else:
            log.info(log_msg)
            
        # Append to JSONL trace log
        try:
            with open(self.trace_log_path, "a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
        except Exception as e:
            log.error(f"[Observability] Failed to write trace log: {e}")

    def generate_diagnostic_report(self) -> str:
        """Compiles a human-readable diagnostic report from the current timeline."""
        report = ["=== JARVIS SYSTEM DIAGNOSTICS ==="]
        for e in self._active_timeline[-50:]:  # Last 50 events
            time_str = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
            report.append(f"[{time_str}] {e.component.upper()} -> {e.action}")
            report.append(f"    Rationale: {e.rationale}")
            if e.metadata:
                report.append(f"    Metadata: {json.dumps(e.metadata)}")
            report.append("")
        return "\n".join(report)

# ── Singleton ──────────────────────────────────────────────────────────────────
_observability_instance: Optional[ObservabilityEngine] = None

def get_observability() -> ObservabilityEngine:
    global _observability_instance
    if _observability_instance is None:
        _observability_instance = ObservabilityEngine()
    return _observability_instance
