import json
import logging
import os
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

log = logging.getLogger("TaskGraphEngine")

class TaskState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    ROLLBACK_REQUIRED = "rollback_required"
    AWAITING_VALIDATION = "awaiting_validation"

class TaskNode(BaseModel):
    node_id: str
    description: str
    state: TaskState = TaskState.PENDING
    dependencies: List[str] = Field(default_factory=list)
    retry_history: int = 0
    max_retries: int = 3
    execution_logs: List[str] = Field(default_factory=list)
    artifacts: Dict[str, str] = Field(default_factory=dict)
    validation_results: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

class TaskGraph(BaseModel):
    graph_id: str
    global_objective: str
    nodes: Dict[str, TaskNode] = Field(default_factory=dict)
    state: TaskState = TaskState.PENDING
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

class TaskGraphEngine:
    """
    Phase 3: Persistent Task Orchestration
    Engine ensures tasks survive crashes, track deep context, and manage complex dependency graphs.
    """
    def __init__(self, checkpoint_dir: str = "memory/tasks"):
        self.checkpoint_dir = checkpoint_dir
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        self.active_graphs: Dict[str, TaskGraph] = {}
        self._load_checkpoints()

    def _load_checkpoints(self):
        """Restore tasks from disk on boot to survive crashes."""
        loaded = 0
        for filename in os.listdir(self.checkpoint_dir):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(self.checkpoint_dir, filename), "r", encoding="utf-8") as f:
                        data = json.load(f)
                        graph = TaskGraph(**data)
                        # Only keep active graphs in memory
                        if graph.state not in [TaskState.COMPLETED, TaskState.FAILED]:
                            self.active_graphs[graph.graph_id] = graph
                            loaded += 1
                except Exception as e:
                    log.error(f"[TaskGraph] Failed to load checkpoint {filename}: {e}")
        if loaded > 0:
            log.info(f"[TaskGraph] Restored {loaded} active task graph(s) from checkpoint.")

    def create_graph(self, objective: str, graph_id: Optional[str] = None) -> TaskGraph:
        graph_id = graph_id or f"graph_{int(time.time()*1000)}"
        graph = TaskGraph(graph_id=graph_id, global_objective=objective)
        self.active_graphs[graph_id] = graph
        self._save_checkpoint(graph)
        log.info(f"[TaskGraph] Created new task graph: {graph_id} -> {objective[:50]}...")
        return graph

    def add_node(self, graph_id: str, node: TaskNode):
        if graph_id in self.active_graphs:
            self.active_graphs[graph_id].nodes[node.node_id] = node
            self.active_graphs[graph_id].updated_at = time.time()
            self._save_checkpoint(self.active_graphs[graph_id])
            log.debug(f"[TaskGraph] Added node {node.node_id} to graph {graph_id}")

    def update_node_state(self, graph_id: str, node_id: str, state: TaskState, log_msg: Optional[str] = None):
        """Updates a node's state and cascades state changes to the global graph."""
        if graph_id in self.active_graphs:
            graph = self.active_graphs[graph_id]
            if node_id in graph.nodes:
                node = graph.nodes[node_id]
                node.state = state
                node.updated_at = time.time()
                if log_msg:
                    node.execution_logs.append(log_msg)
                
                # Recalculate global state
                all_completed = all(n.state == TaskState.COMPLETED for n in graph.nodes.values())
                any_failed = any(n.state == TaskState.FAILED for n in graph.nodes.values())
                
                if any_failed:
                    graph.state = TaskState.FAILED
                elif all_completed and len(graph.nodes) > 0:
                    graph.state = TaskState.COMPLETED
                else:
                    graph.state = TaskState.ACTIVE
                    
                graph.updated_at = time.time()
                self._save_checkpoint(graph)

    def record_retry(self, graph_id: str, node_id: str) -> bool:
        """Records a retry attempt for a node. Returns False if max retries exceeded."""
        if graph_id in self.active_graphs:
            graph = self.active_graphs[graph_id]
            if node_id in graph.nodes:
                node = graph.nodes[node_id]
                node.retry_history += 1
                if node.retry_history > node.max_retries:
                    self.update_node_state(graph_id, node_id, TaskState.FAILED, "Max retries exceeded.")
                    return False
                self.update_node_state(graph_id, node_id, TaskState.ROLLBACK_REQUIRED, f"Retry attempt {node.retry_history}")
                return True
        return False

    def _save_checkpoint(self, graph: TaskGraph):
        """Atomic write to prevent corruption during an OS or hardware crash."""
        path = os.path.join(self.checkpoint_dir, f"{graph.graph_id}.json")
        temp_path = path + ".tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(graph.model_dump_json(indent=2))
            os.replace(temp_path, path)
        except Exception as e:
            log.error(f"[TaskGraph] Checkpoint failed for {graph.graph_id}: {e}")

    def get_executable_nodes(self, graph_id: str) -> List[TaskNode]:
        """Finds pending nodes whose dependencies are all COMPLETED."""
        executable = []
        if graph_id in self.active_graphs:
            graph = self.active_graphs[graph_id]
            if graph.state in [TaskState.COMPLETED, TaskState.FAILED]:
                return []
                
            for node in graph.nodes.values():
                if node.state in [TaskState.PENDING, TaskState.AWAITING_VALIDATION]:
                    # Verify dependencies
                    deps_met = all(
                        dep in graph.nodes and graph.nodes[dep].state == TaskState.COMPLETED
                        for dep in node.dependencies
                    )
                    if deps_met:
                        executable.append(node)
        return executable

# ── Singleton ──────────────────────────────────────────────────────────────────
_task_engine_instance: Optional[TaskGraphEngine] = None

def get_task_engine() -> TaskGraphEngine:
    global _task_engine_instance
    if _task_engine_instance is None:
        _task_engine_instance = TaskGraphEngine()
    return _task_engine_instance
