# core/orchestration/limits.py
"""
Hard orchestration limits — P12.
Max concurrent actions, max event propagation depth, max rollback chain length,
max retries, max queue occupancy, max inference concurrency.
Prevents runaway loops, recursive orchestration, self-triggering event storms.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("OrchestrationLimits")


@dataclass
class OrchestrationLimits:
    """Hard limits that prevent runaway orchestration."""
    max_concurrent_actions: int = 20
    max_event_propagation_depth: int = 10
    max_rollback_chain_length: int = 10
    max_retries_per_action: int = 3
    max_queue_occupancy: int = 100
    max_inference_concurrency: int = 2
    max_event_chain_length: int = 50
    max_subscriber_count_per_event: int = 100
    max_simulation_iterations: int = 1000
    max_policy_recursion: int = 5
    event_storm_threshold: int = 50
    slow_action_threshold_ms: float = 8000.0
    max_starvation_age_sec: float = 60.0

    def enforce_action_limit(self, current: int) -> bool:
        """Check if a new action can be started."""
        if current >= self.max_concurrent_actions:
            log.warning(f"[Limits] Action limit reached: {current}/{self.max_concurrent_actions}")
            return False
        return True

    def enforce_queue_limit(self, depth: int) -> bool:
        """Check if a new action can be queued."""
        if depth >= self.max_queue_occupancy:
            log.warning(f"[Limits] Queue limit reached: {depth}/{self.max_queue_occupancy}")
            return False
        return True

    def enforce_propagation_depth(self, depth: int) -> bool:
        """Check if an event can propagate further."""
        if depth >= self.max_event_propagation_depth:
            log.warning(f"[Limits] Event propagation depth limit: {depth}/{self.max_event_propagation_depth}")
            return False
        return True

    def enforce_inference_limit(self, active: int) -> bool:
        """Check if a new inference can start."""
        if active >= self.max_inference_concurrency:
            log.warning(f"[Limits] Inference concurrency limit: {active}/{self.max_inference_concurrency}")
            return False
        return True


_global_limits: OrchestrationLimits | None = None
_limits_lock = threading.Lock()


def get_limits() -> OrchestrationLimits:
    global _global_limits
    with _limits_lock:
        if _global_limits is None:
            _global_limits = OrchestrationLimits()
        return _global_limits
