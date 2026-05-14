import os
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

class FailureJournal:
    """
    Phase 2: Failure Journal System
    Records real operational failures to expose real-world pain points.
    Phase 3: Human Friction Analysis
    Also records manual overrides and frustration events.
    """
    def __init__(self, log_path: str = "memory/operational_failures.jsonl"):
        self.log_path = Path("d:/JARVIS-v3") / log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_failure(self, 
                    task_objective: str, 
                    context: str, 
                    root_cause: str,
                    category: str,
                    recovery_attempt: str,
                    retry_count: int,
                    human_intervention_required: bool,
                    operational_impact_severity: str) -> None:
        """
        Record a structured operational failure.
        Categories: "planning_failure", "context_failure", "recovery_failure", 
                    "memory_pollution", "execution_drift", "user_ambiguity", 
                    "dependency_instability", "hallucinated_execution", "resource_exhaustion"
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "SYSTEM_FAILURE",
            "task_objective": task_objective,
            "execution_context": context,
            "root_cause": root_cause,
            "category": category,
            "recovery_attempt": recovery_attempt,
            "retry_count": retry_count,
            "human_intervention_required": human_intervention_required,
            "operational_impact_severity": operational_impact_severity
        }
        self._write_entry(entry)

    def log_friction(self,
                     event_type: str,
                     task_objective: str,
                     wasted_time_est_sec: int) -> None:
        """
        Phase 3: Human Friction Analysis
        Record human operational friction.
        Event Types: "manual_override", "rejected_plan", "corrected_output", 
                     "abandoned_execution", "excessive_clarification", "annoyance"
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": "HUMAN_FRICTION",
            "event_type": event_type,
            "task_objective": task_objective,
            "wasted_time_est_sec": wasted_time_est_sec
        }
        self._write_entry(entry)

    def _write_entry(self, entry: Dict) -> None:
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"[FailureJournal] Failed to log: {e}")

_instance = None
def get_failure_journal() -> FailureJournal:
    global _instance
    if not _instance:
        _instance = FailureJournal()
    return _instance
