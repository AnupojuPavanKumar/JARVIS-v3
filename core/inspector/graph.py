# core/inspector/graph.py
"""
Runtime graph inspector — live visualization of the action graph.
Non-blocking, bounded memory, debug-mode only.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

log = logging.getLogger("RuntimeInspector")


class NodeType(Enum):
    COMMAND = auto()
    ACTION = auto()
    EVENT = auto()
    SUBSCRIBER = auto()
    EXECUTOR = auto()
    SUBPROCESS = auto()
    ROLLBACK = auto()
    STATE = auto()
    DECISION = auto()


@dataclass
class GraphNode:
    """A node in the runtime graph."""
    node_id: str
    type: NodeType
    label: str
    timestamp: float
    duration_ms: float | None = None
    parent_id: str | None = None
    status: str = "running"
    metadata: dict = field(default_factory=dict)
    children: list[str] = field(default_factory=list)


@dataclass
class GraphEdge:
    """An edge connecting nodes in the runtime graph."""
    from_id: str
    to_id: str
    edge_type: str
    propagation_depth: int = 0


@dataclass
class GraphSnapshot:
    """A snapshot of the runtime graph at a point in time."""
    timestamp: float
    node_count: int
    edge_count: int
    active_nodes: int
    completed_nodes: int
    failed_nodes: int
    max_depth: int
    event_propagation_depth: int


class RuntimeGraphInspector:
    """
    Lightweight runtime graph inspector.
    Tracks live action graphs, event propagation trees, and execution lineage.
    Non-blocking, bounded memory usage.
    """

    def __init__(self, max_nodes: int = 500, max_events: int = 1000):
        self._max_nodes = max_nodes
        self._max_events = max_events
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._active_chains: dict[str, str] = {}
        self._lock = threading.RLock()
        self._event_propagation: deque[tuple[str, int]] = deque(maxlen=max_events)
        self._running = False
        self._trace_id_to_root: dict[str, str] = {}

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def add_node(
        self, node_id: str, node_type: NodeType, label: str,
        parent_id: str | None = None, metadata: dict | None = None
    ) -> GraphNode:
        """Add a node to the runtime graph."""
        with self._lock:
            node = GraphNode(
                node_id=node_id, type=node_type, label=label,
                timestamp=time.time(), parent_id=parent_id,
                metadata=metadata or {},
            )
            self._nodes[node_id] = node
            if parent_id and parent_id in self._nodes:
                self._nodes[parent_id].children.append(node_id)
                self._edges.append(GraphEdge(parent_id, node_id, "parent_child"))
            if len(self._nodes) > self._max_nodes:
                self._evict_old_nodes()
            return node

    def add_event_node(
        self, event_type: str, trace_id: str, propagation_depth: int,
        subscriber_id: str, parent_trace_id: str | None = None
    ):
        """Add an event node and its propagation chain."""
        with self._lock:
            self._event_propagation.append((trace_id, propagation_depth))
            node = GraphNode(
                node_id=f"{trace_id}:{propagation_depth}",
                type=NodeType.EVENT, label=event_type,
                timestamp=time.time(), status="emitted",
                metadata={"subscriber": subscriber_id, "depth": propagation_depth},
            )
            if parent_trace_id:
                parent_node_id = f"{parent_trace_id}:{propagation_depth - 1}"
                if parent_node_id in self._nodes:
                    node.parent_id = parent_node_id
                    self._nodes[parent_node_id].children.append(node.node_id)
                    self._edges.append(GraphEdge(parent_node_id, node.node_id, "event_propagation"))
            self._nodes[node.node_id] = node

    def update_status(self, node_id: str, status: str, duration_ms: float | None = None):
        """Update a node's status (e.g., completed, failed)."""
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].status = status
                if duration_ms is not None:
                    self._nodes[node_id].duration_ms = duration_ms

    def link_trace(self, trace_id: str, root_node_id: str):
        """Link a trace ID to its root graph node."""
        with self._lock:
            self._trace_id_to_root[trace_id] = root_node_id

    def _evict_old_nodes(self):
        """Evict oldest completed nodes when limit is reached."""
        completed = [
            (nid, n.timestamp) for nid, n in self._nodes.items()
            if n.status in ("completed", "failed", "cancelled") and not n.children
        ]
        completed.sort(key=lambda x: x[1])
        for nid, _ in completed[:10]:
            self._nodes.pop(nid, None)

    def get_snapshot(self) -> GraphSnapshot:
        """Get a snapshot of the current graph state."""
        with self._lock:
            active = sum(1 for n in self._nodes.values() if n.status == "running")
            completed = sum(1 for n in self._nodes.values() if n.status == "completed")
            failed = sum(1 for n in self._nodes.values() if n.status == "failed")
            max_depth = 0
            for n in self._nodes.values():
                depth = 0
                cur = n
                while cur.parent_id and cur.parent_id in self._nodes:
                    depth += 1
                    cur = self._nodes[cur.parent_id]
                max_depth = max(max_depth, depth)
            max_event_depth = max((d for _, d in self._event_propagation), default=0)
        return GraphSnapshot(
            timestamp=time.time(), node_count=len(self._nodes),
            edge_count=len(self._edges), active_nodes=active,
            completed_nodes=completed, failed_nodes=failed,
            max_depth=max_depth, event_propagation_depth=max_event_depth,
        )

    def get_active_graph(self) -> dict:
        """Get a serializable view of the active graph."""
        with self._lock:
            nodes = {
                nid: {
                    "type": n.type.name, "label": n.label,
                    "status": n.status, "duration_ms": n.duration_ms,
                    "parent": n.parent_id, "children": n.children,
                    "age_sec": round(time.time() - n.timestamp, 1),
                }
                for nid, n in self._nodes.items()
                if n.status == "running"
            }
            return nodes

    def get_event_tree(self, limit: int = 50) -> list[dict]:
        """Get the event propagation tree as a list."""
        with self._lock:
            events = list(self._event_propagation)[-limit:]
            result = []
            for trace_id, depth in events:
                node_id = f"{trace_id}:{depth}"
                if node_id in self._nodes:
                    n = self._nodes[node_id]
                    result.append({
                        "trace": trace_id, "depth": depth,
                        "label": n.label, "status": n.status,
                        "age_sec": round(time.time() - n.timestamp, 1),
                    })
            return result

    def stats(self) -> dict:
        snap = self.get_snapshot()
        with self._lock:
            by_type = {}
            for n in self._nodes.values():
                key = n.type.name
                by_type[key] = by_type.get(key, 0) + 1
        return {
            "nodes": snap.node_count,
            "edges": snap.edge_count,
            "active": snap.active_nodes,
            "completed": snap.completed_nodes,
            "failed": snap.failed_nodes,
            "max_depth": snap.max_depth,
            "event_max_depth": snap.event_propagation_depth,
            "by_type": by_type,
            "event_history": len(self._event_propagation),
        }


_global_inspector: RuntimeGraphInspector | None = None
_insp_lock = threading.Lock()


def get_inspector() -> RuntimeGraphInspector:
    global _global_inspector
    with _insp_lock:
        if _global_inspector is None:
            _global_inspector = RuntimeGraphInspector()
        return _global_inspector
