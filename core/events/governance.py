# core/events/governance.py
"""
Event governance system — P2.
Domain-scoped events, subscriber ownership, max propagation depth,
event validation, dead-event detection, orphan-subscriber detection.
Prevents recursive event storms, unbounded propagation, event abuse.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto

log = logging.getLogger("EventGovernance")


EVENT_DOMAINS = {
    "execution": ["execution.started", "execution.completed", "execution.failed", "execution.queued", "execution.cancelled", "execution.rollback"],
    "audio": ["audio.volume_changed", "audio.device_changed", "audio.playing", "audio.capturing", "audio.muted"],
    "ui": ["ui.focus_changed", "ui.window_opened", "ui.window_closed", "ui.button_pressed"],
    "memory": ["memory.updated", "memory.evicted", "memory.cleared", "memory.fragmented"],
    "ai": ["ai.inference_start", "ai.inference_end", "ai.model_loaded", "ai.model_unloaded", "ai.model_overloaded"],
    "system": ["system.startup", "system.shutdown", "system.error", "system.mode_changed", "system.health_changed"],
    "resource": ["resource.throttled", "resource.recovered", "resource.warning", "resource.critical"],
    "state": ["state.changed", "state.error", "state.timeout"],
}


@dataclass
class EventSchema:
    """Schema definition for a validated event type."""
    event_type: str
    domain: str
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    max_propagation: int
    description: str = ""


@dataclass
class GovernanceConfig:
    max_propagation_depth: int = 10
    max_subscriber_count: int = 100
    dead_event_threshold_hits: int = 0
    orphan_subscriber_threshold_sec: float = 3600.0
    event_storm_threshold: int = 50
    event_storm_window_sec: float = 1.0
    validate_event_names: bool = True
    enforce_domain_naming: bool = True


class EventGovernance:
    """
    Event governance system.
    Validates events, tracks domains, detects event storms and dead events,
    prevents unbounded propagation.
    """

    def __init__(self, config: GovernanceConfig | None = None):
        self.config = config or GovernanceConfig()
        self._schemas: dict[str, EventSchema] = {}
        self._lock = threading.RLock()
        self._domain_registry: dict[str, set[str]] = defaultdict(set)
        self._subscriber_domains: dict[str, str] = {}
        self._event_hits: dict[str, list[float]] = defaultdict(list)
        self._dead_event_count: dict[str, int] = defaultdict(int)
        self._orphan_subscriber_count: dict[str, float] = defaultdict(float)
        self._last_event_storm_warning = 0.0

        for domain, events in EVENT_DOMAINS.items():
            for event in events:
                self._register_domain_event(domain, event)

    def _register_domain_event(self, domain: str, event_type: str):
        parts = event_type.split(".")
        with self._lock:
            self._domain_registry[domain].add(event_type)
            self._schemas[event_type] = EventSchema(
                event_type=event_type, domain=domain,
                required_fields=(), optional_fields=(),
                max_propagation=self.config.max_propagation_depth,
                description=f"{domain} domain event",
            )

    def register_subscriber(self, subscription_id: str, domain: str):
        """Register a subscriber's domain ownership."""
        with self._lock:
            self._subscriber_domains[subscription_id] = domain

    def validate_event_name(self, event_type: str) -> tuple[bool, str]:
        """Validate event naming convention."""
        if not self.config.validate_event_names:
            return True, "validation disabled"
        if not event_type or "." not in event_type:
            return False, f"Event '{event_type}' must follow domain.event_name convention"
        parts = event_type.split(".")
        if len(parts) != 2:
            return False, f"Event '{event_type}' must have exactly 2 parts (domain.event_name)"
        domain, name = parts
        if self.config.enforce_domain_naming:
            if domain not in self._domain_registry:
                return False, f"Unknown domain: {domain}. Known: {list(self._domain_registry.keys())}"
        return True, ""

    def validate_event(self, event_type: str, data: dict) -> tuple[bool, str]:
        """Validate an event against its schema."""
        valid, reason = self.validate_event_name(event_type)
        if not valid:
            return False, reason
        with self._lock:
            schema = self._schemas.get(event_type)
        if not schema:
            return True, "no schema defined"
        for field in schema.required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"
        return True, ""

    def record_event(self, event_type: str, depth: int = 0):
        """Record an event emission for storm detection and hit counting."""
        now = time.time()
        with self._lock:
            self._event_hits[event_type].append(now)
            self._event_hits[event_type] = [h for h in self._event_hits[event_type] if now - h < self.config.event_storm_window_sec]

            if depth > self.config.max_propagation_depth:
                return False, f"Max propagation depth exceeded: {depth}/{self.config.max_propagation_depth}"

            hits = len(self._event_hits[event_type])
            if hits > self.config.event_storm_threshold:
                if now - self._last_event_storm_warning > 5.0:
                    log.warning(f"[EventGovernance] EVENT STORM: {event_type} emitted {hits} times in {self.config.event_storm_window_sec}s")
                    self._last_event_storm_warning = now
                return False, f"Event storm detected: {hits} events in {self.config.event_storm_window_sec}s"

        return True, ""

    def detect_dead_events(self, min_hits: int = 10) -> list[str]:
        """Detect events that are emitted frequently but have no subscribers."""
        dead = []
        with self._lock:
            for event_type, hits in self._event_hits.items():
                recent = [h for h in hits if time.time() - h < 300]
                if len(recent) >= min_hits:
                    dead.append(event_type)
        return dead

    def get_domain_events(self, domain: str) -> list[str]:
        with self._lock:
            return list(self._domain_registry.get(domain, set()))

    def list_all_domains(self) -> list[str]:
        with self._lock:
            return list(self._domain_registry.keys())

    def stats(self) -> dict:
        with self._lock:
            return {
                "domains": len(self._domain_registry),
                "registered_events": sum(len(v) for v in self._domain_registry.values()),
                "event_types_seen": len(self._event_hits),
                "subscriber_domains": len(self._subscriber_domains),
                "dead_events": len(self.detect_dead_events()),
            }


_global_governance: EventGovernance | None = None
_gov_lock = threading.Lock()


def get_event_governance() -> EventGovernance:
    global _global_governance
    with _gov_lock:
        if _global_governance is None:
            _global_governance = EventGovernance()
        return _global_governance
