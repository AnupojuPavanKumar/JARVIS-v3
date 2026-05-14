# core/audit/topology.py
"""
Event topology and orchestration depth analysis — P1, P3.
Event dependency graph, propagation depth heatmaps, circular event detection,
orchestration depth metrics, branching factor, recovery recursion depth.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional

log = logging.getLogger("EventTopology")


@dataclass
class OrchestrationMetrics:
    """Metrics for an orchestration chain."""
    command: str
    chain_length: int
    max_depth: int
    branching_factor: float
    event_count: int
    policy_count: int
    rollback_depth: int
    total_duration_ms: float


class EventNode:
    __slots__ = ("event_type", "subscribers", "emitted_count", "last_emitted", "propagations")

    def __init__(self, event_type: str):
        self.event_type: str = event_type
        self.subscribers: List[str] = []
        self.emitted_count: int = 0
        self.last_emitted: float = 0.0
        self.propagations: int = 0


class EventTopology:
    """
    Event dependency graph and propagation analysis.
    Detects circular events, propagation depth heatmaps, fan-out metrics,
    redundant propagation paths, dead propagation chains.
    """

    def __init__(self):
        self._nodes: Dict[str, EventNode] = {}
        self._edges: List[tuple] = []  # (source, target, propagation_depth)
        self._lock = threading.RLock()
        self._circular_chains: List[List[str]] = []
        self._propagation_history: deque = deque(maxlen=500)
        self._fan_out: Dict[str, int] = defaultdict(int)
        self._redundant_paths: List[tuple] = []
        self._dead_events: List[str] = []

    def record_emission(self, event_type: str, subscriber: str, depth: int = 0):
        """Record an event emission and its subscriber."""
        with self._lock:
            if event_type not in self._nodes:
                self._nodes[event_type] = EventNode(event_type)
            node = self._nodes[event_type]
            node.emitted_count += 1
            node.last_emitted = time.time()
            node.propagations += 1
            if subscriber not in node.subscribers:
                node.subscribers.append(subscriber)
            self._propagation_history.append((event_type, subscriber, depth, time.time()))

    def record_chain(self, events: List[str]):
        """Record an event propagation chain."""
        with self._lock:
            for i, event in enumerate(events):
                if event not in self._nodes:
                    self._nodes[event] = EventNode(event)
                self._nodes[event].emitted_count += 1
                if i > 0:
                    prev = events[i - 1]
                    self._edges.append((prev, event, i))
                    self._fan_out[prev] += 1

    def detect_circular_events(self) -> List[List[str]]:
        """Detect circular event propagation chains."""
        with self._lock:
            edges = list(self._edges)
        cycles = []
        for event in self._nodes:
            visited = set()
            path = []
            cycle = self._dfs_cycle(event, event, visited, path, set(edges))
            if cycle:
                cycles.append(cycle)
        self._circular_chains = cycles
        return cycles

    def _dfs_cycle(self, start: str, current: str, visited: Set, path: List, edges: Set) -> List[str] | None:
        if current in visited:
            if current == start and len(path) > 2:
                return path[:]
            return None
        visited.add(current)
        path.append(current)
        outgoing = [(f, t) for f, t, d in self._edges if f == current]
        for source, target in outgoing:
            result = self._dfs_cycle(start, target, visited, path[:], edges)
            if result:
                return result
        return None

    def compute_propagation_depth_map(self) -> Dict[str, List[int]]:
        """Compute depth histogram per event type."""
        with self._lock:
            depth_map: Dict[str, List[int]] = defaultdict(list)
            for event, sub, depth, _ in self._propagation_history:
                depth_map[event].append(depth)
        return {k: sorted(set(v)) for k, v in depth_map.items()}

    def get_topology_score(self) -> tuple[float, List[str]]:
        """Compute event topology score (0=chaos, 1=perfect) and warnings."""
        with self._lock:
            total_nodes = len(self._nodes)
            if total_nodes == 0:
                return 1.0, []
        score = 1.0
        warnings = []
        with self._lock:
            circular_count = len(self._detect_circular_events_fast())
            if circular_count > 0:
                score -= min(circular_count * 0.1, 0.3)
                warnings.append(f"Circular propagation chains: {circular_count}")
            dead = self._detect_dead_events_fast()
            if dead:
                score -= min(len(dead) * 0.05, 0.2)
                warnings.append(f"Dead events: {len(dead)}")
            avg_fanout = sum(self._fan_out.values()) / max(len(self._fan_out), 1)
            if avg_fanout > 5:
                score -= 0.1
                warnings.append(f"High average fan-out: {avg_fanout:.1f}")
        return round(score, 3), warnings

    def _detect_circular_events_fast(self) -> List[str]:
        cycles = []
        for event in self._nodes:
            for source, target, _ in self._edges:
                if source == event:
                    found_reverse = any(s == target and t == event for s, t, _ in self._edges)
                    if found_reverse:
                        cycles.append(f"{event} <-> {target}")
        return cycles

    def _detect_dead_events_fast(self) -> List[str]:
        dead = []
        now = time.time()
        for event, node in self._nodes.items():
            if node.emitted_count > 0 and now - node.last_emitted > 300:
                dead.append(event)
        return dead

    def get_coupling_metrics(self) -> dict:
        """Get event coupling metrics (fan-out, fan-in, betweenness proxy)."""
        with self._lock:
            fan_out = dict(self._fan_out)
            fan_in: Dict[str, int] = defaultdict(int)
            for _, target, _ in self._edges:
                fan_in[target] += 1
        return {
            "total_events": len(self._nodes),
            "total_edges": len(self._edges),
            "avg_fan_out": round(sum(fan_out.values()) / max(len(fan_out), 1), 2),
            "max_fan_out": max(fan_out.values()) if fan_out else 0,
            "avg_fan_in": round(sum(fan_in.values()) / max(len(fan_in), 1), 2),
            "max_fan_in": max(fan_in.values()) if fan_in else 0,
            "circular_chains": len(self._circular_chains),
            "dead_events": len(self._dead_events),
        }

    def stats(self) -> dict:
        score, warnings = self.get_topology_score()
        coupling = self.get_coupling_metrics()
        return {
            "topology_score": score,
            "warnings": warnings,
            **coupling,
            "total_propagations": len(self._propagation_history),
        }


class OrchestrationDepth:
    """
    Tracks total orchestration depth per command.
    User Command → decomposition → events → policies → executors → rollbacks → recovery → completion.
    """

    def __init__(self):
        self._max_chain_depth: int = 15
        self._max_recovery_depth: int = 5
        self._max_policy_cascades: int = 5
        self._lock = threading.Lock()
        self._active_chains: Dict[str, List[str]] = {}
        self._chain_metrics: deque = deque(maxlen=200)

    def begin_chain(self, chain_id: str):
        with self._lock:
            self._active_chains[chain_id] = []

    def record_step(self, chain_id: str, step: str):
        with self._lock:
            if chain_id in self._active_chains:
                self._active_chains[chain_id].append(step)

    def end_chain(self, chain_id: str) -> OrchestrationMetrics:
        with self._lock:
            steps = self._active_chains.pop(chain_id, [])
        depth = len(steps)
        event_count = sum(1 for s in steps if s.startswith("event:"))
        policy_count = sum(1 for s in steps if s.startswith("policy:"))
        rollback_depth = sum(1 for s in steps if s.startswith("rollback:"))
        branching = 1.0
        metrics = OrchestrationMetrics(
            command="", chain_length=depth, max_depth=depth,
            branching_factor=branching, event_count=event_count,
            policy_count=policy_count, rollback_depth=rollback_depth,
            total_duration_ms=0.0,
        )
        with self._lock:
            self._chain_metrics.append(metrics)
        return metrics

    def check_depth_limit(self, current_depth: int) -> bool:
        return current_depth < self._max_chain_depth

    def check_recovery_limit(self, recovery_depth: int) -> bool:
        return recovery_depth < self._max_recovery_depth

    def check_policy_cascade_limit(self, cascades: int) -> bool:
        return cascades < self._max_policy_cascades

    def get_depth_stats(self) -> dict:
        with self._lock:
            metrics = list(self._chain_metrics)
        if not metrics:
            return {"avg_depth": 0, "max_depth": 0, "avg_event_count": 0, "avg_rollback_depth": 0}
        return {
            "avg_depth": round(sum(m.chain_length for m in metrics) / len(metrics), 1),
            "max_depth": max(m.chain_length for m in metrics),
            "avg_event_count": round(sum(m.event_count for m in metrics) / len(metrics), 1),
            "avg_rollback_depth": round(sum(m.rollback_depth for m in metrics) / len(metrics), 1),
            "total_chains": len(metrics),
        }


_global_topology: EventTopology | None = None
_t_lock = threading.Lock()


def get_topology() -> EventTopology:
    global _global_topology
    with _t_lock:
        if _global_topology is None:
            _global_topology = EventTopology()
        return _global_topology
