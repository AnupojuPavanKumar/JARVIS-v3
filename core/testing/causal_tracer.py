import logging
import json
import os
from typing import List, Dict

log = logging.getLogger("CausalTracer")

class CausalTracer:
    """
    Phase 6: Causal Observability
    Reconstructs end-to-end failure chains and execution timelines from Observability logs.
    """
    def __init__(self, trace_dir: str = "logs/observability"):
        self.trace_dir = trace_dir

    def get_latest_trace_file(self) -> str:
        """Finds the most recent TraceEvent JSONL file."""
        if not os.path.exists(self.trace_dir):
            return None
            
        files = [f for f in os.listdir(self.trace_dir) if f.startswith("trace_") and f.endswith(".jsonl")]
        if not files:
            return None
            
        files.sort(reverse=True)
        return os.path.join(self.trace_dir, files[0])

    def reconstruct_failure_chain(self, trace_file: str = None) -> str:
        """Parses a trace log and builds a causal graph explaining a failure."""
        if not trace_file:
            trace_file = self.get_latest_trace_file()
            
        if not trace_file or not os.path.exists(trace_file):
            return "No trace data available for causal reconstruction."
            
        events = []
        try:
            with open(trace_file, "r", encoding="utf-8") as f:
                for line in f:
                    events.append(json.loads(line))
        except Exception as e:
            return f"Failed to read trace log: {e}"

        # Find the first failure event to work backwards from
        failure_idx = -1
        for i, event in enumerate(events):
            if event.get("event_type") == "failure":
                failure_idx = i
                break
                
        if failure_idx == -1:
            return "No failures detected in the specified trace timeline."
            
        # Reconstruct the causal chain leading to the failure
        chain = ["[CAUSAL RECONSTRUCTION] =================================="]
        chain.append("Tracing the lineage of a detected system failure...")
        
        # Look at the 5 events preceding the failure
        start_idx = max(0, failure_idx - 5)
        for i in range(start_idx, failure_idx + 1):
            e = events[i]
            prefix = "├──" if i < failure_idx else "└── [FAILURE TRIGGER]"
            chain.append(f"{prefix} {e['component'].upper()} -> {e['action']}")
            chain.append(f"    │   WHY: {e['rationale']}")
            if e.get("metadata"):
                chain.append(f"    │   CTX: {json.dumps(e['metadata'])}")
                
        chain.append("==========================================================")
        return "\n".join(chain)

    def print_dag_replay(self, trace_file: str = None):
        """Generates a text-based visual timeline of the execution."""
        replay = self.reconstruct_failure_chain(trace_file)
        print(replay)
        log.warning(f"\n{replay}")
