import time
import json
import os
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
import logging

log = logging.getLogger("MetricsCollector")

class TaskMetrics(BaseModel):
    task_id: str
    task_name: str
    success: bool = False
    retry_count: int = 0
    hallucinated_tool_calls: int = 0
    invalid_shell_commands: int = 0
    context_corruption_events: int = 0
    file_operation_failures: int = 0
    memory_retrieval_accuracy: float = 0.0
    recovery_success_rate: float = 0.0
    task_completion_time_sec: float = 0.0
    agent_loop_depth: int = 0
    planner_executor_disagreements: int = 0
    start_time: float = Field(default_factory=time.time)
    end_time: Optional[float] = None
    error_message: Optional[str] = None

class MetricsCollector:
    """
    Collects execution metrics for the Reliability Evaluation Framework.
    """
    def __init__(self, log_dir: str = "logs/evaluation"):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.current_task: Optional[TaskMetrics] = None
        self.completed_tasks: List[TaskMetrics] = []

    def start_task(self, task_id: str, task_name: str):
        if self.current_task:
            log.warning(f"Starting new task {task_id} while {self.current_task.task_id} is still active. Closing previous.")
            self.end_task(success=False, error_message="Interrupted by new task")
            
        self.current_task = TaskMetrics(task_id=task_id, task_name=task_name)
        log.info(f"[Metrics] Started task {task_id}: {task_name}")

    def end_task(self, success: bool, error_message: Optional[str] = None):
        if not self.current_task:
            log.warning("[Metrics] Called end_task but no task is currently active.")
            return
            
        self.current_task.success = success
        self.current_task.error_message = error_message
        self.current_task.end_time = time.time()
        self.current_task.task_completion_time_sec = self.current_task.end_time - self.current_task.start_time
        
        self.completed_tasks.append(self.current_task)
        self._save_report(self.current_task)
        
        log.info(f"[Metrics] Ended task {self.current_task.task_id}: Success={success}, Time={self.current_task.task_completion_time_sec:.2f}s")
        self.current_task = None

    def _save_report(self, task: TaskMetrics):
        report_path = os.path.join(self.log_dir, f"task_{task.task_id}_{int(task.start_time)}.json")
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(task.model_dump_json(indent=2))
        except Exception as e:
            log.error(f"[Metrics] Failed to save report: {e}")

    # ── Metric Tracking Methods ────────────────────────────────────────────────
    
    def record_retry(self):
        if self.current_task: 
            self.current_task.retry_count += 1
            
    def record_hallucinated_tool_call(self):
        if self.current_task: 
            self.current_task.hallucinated_tool_calls += 1
            
    def record_invalid_shell_command(self):
        if self.current_task: 
            self.current_task.invalid_shell_commands += 1
            
    def record_context_corruption(self):
        if self.current_task: 
            self.current_task.context_corruption_events += 1
            
    def record_file_operation_failure(self):
        if self.current_task: 
            self.current_task.file_operation_failures += 1
            
    def record_planner_disagreement(self):
        if self.current_task: 
            self.current_task.planner_executor_disagreements += 1

    def update_agent_loop_depth(self, depth: int):
        if self.current_task and depth > self.current_task.agent_loop_depth:
            self.current_task.agent_loop_depth = depth

    def set_memory_accuracy(self, accuracy: float):
        if self.current_task:
            self.current_task.memory_retrieval_accuracy = accuracy


# ── Singleton ──────────────────────────────────────────────────────────────────
_metrics_instance: Optional[MetricsCollector] = None

def get_metrics() -> MetricsCollector:
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = MetricsCollector()
    return _metrics_instance
