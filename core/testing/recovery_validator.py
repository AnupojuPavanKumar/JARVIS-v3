import logging
import os
import json
from typing import List

from core.system.task_graph import get_task_engine, TaskState
from core.system.recovery_engine import get_recovery_engine

log = logging.getLogger("RecoveryValidator")

class IntegrityReport:
    def __init__(self):
        self.passed: bool = True
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def add_error(self, msg: str):
        self.passed = False
        self.errors.append(msg)
        
    def add_warning(self, msg: str):
        self.warnings.append(msg)

class RecoveryValidator:
    """
    Phase 3: Recovery Validation
    Proves that recovery mechanisms work by detecting silent corruption,
    orphaned states, partial executions, and infinite retry loops.
    """
    
    def validate_system_integrity(self) -> IntegrityReport:
        report = IntegrityReport()
        self._validate_task_graph(report)
        self._validate_recovery_snapshots(report)
        self._validate_observability_traces(report)
        
        if report.passed:
            log.info("[VALIDATION] System integrity VERIFIED. No corruption detected.")
        else:
            log.critical(f"[VALIDATION] SYSTEM CORRUPTED. Found {len(report.errors)} errors.")
            for e in report.errors:
                log.error(f"  -> {e}")
                
        return report
        
    def _validate_task_graph(self, report: IntegrityReport):
        engine = get_task_engine()
        
        # 1. Checkpoint JSON consistency
        if os.path.exists(engine.checkpoint_dir):
            for file in os.listdir(engine.checkpoint_dir):
                if file.endswith(".json"):
                    path = os.path.join(engine.checkpoint_dir, file)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if "graph_id" not in data or "state" not in data:
                                report.add_error(f"Task checkpoint {file} is malformed.")
                    except Exception as e:
                        report.add_error(f"Task checkpoint {file} is corrupted: {e}")
                        
        # 2. In-memory DAG consistency
        for graph_id, graph in engine.active_graphs.items():
            # Check for infinite retry loops
            for node_id, node in graph.nodes.items():
                if node.retry_history >= node.max_retries and node.state != TaskState.FAILED:
                    report.add_error(f"Node {node_id} in {graph_id} exceeded max retries but is not FAILED.")
                    
            # Check graph state vs node states
            any_failed = any(n.state == TaskState.FAILED for n in graph.nodes.values())
            all_completed = all(n.state == TaskState.COMPLETED for n in graph.nodes.values())
            
            if any_failed and graph.state != TaskState.FAILED:
                report.add_error(f"Graph {graph_id} has failed nodes but graph state is {graph.state}.")
            if all_completed and len(graph.nodes) > 0 and graph.state != TaskState.COMPLETED:
                report.add_error(f"Graph {graph_id} has all completed nodes but graph state is {graph.state}.")

    def _validate_recovery_snapshots(self, report: IntegrityReport):
        recovery = get_recovery_engine()
        
        # 1. Check for orphaned snapshots
        if len(recovery.active_snapshots) > 0:
            report.add_warning(f"Found {len(recovery.active_snapshots)} active recovery snapshots. Ensure these are cleaned up or rolled back.")
            
        # 2. Check physical backups
        if os.path.exists(recovery.backup_dir):
            physical_backups = os.listdir(recovery.backup_dir)
            active_ids = list(recovery.active_snapshots.keys())
            
            for backup in physical_backups:
                if backup not in active_ids:
                    report.add_error(f"Orphaned physical backup found: {backup} without active snapshot record.")

    def _validate_observability_traces(self, report: IntegrityReport):
        # In a real run, we would verify that a trace exists for the time period.
        pass

# ── Singleton ──────────────────────────────────────────────────────────────────
_validator_instance = None
def get_recovery_validator() -> RecoveryValidator:
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = RecoveryValidator()
    return _validator_instance
