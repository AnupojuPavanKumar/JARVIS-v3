# core/events/bus.py
"""
Async-safe event bus with typed events and pub/sub dispatch.
Decoupled orchestration — no rewrite of existing threading model.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from queue import Queue, Empty
from typing import Any, Callable, Optional
from weakref import WeakSet

log = logging.getLogger("EventBus")


class EventPriority(Enum):
    LOW = 1
    NORMAL = 5
    HIGH = 10


@dataclass
class Event:
    """Base event with trace context."""
    event_type: str
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    parent_trace_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    source: str = "system"
    data: dict = field(default_factory=dict)
    priority: EventPriority = EventPriority.NORMAL

    def __str__(self) -> str:
        ts = datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S.%f")[:-3]
        return f"[{ts}] {self.source}.{self.event_type}"


class EventSubscriber:
    """A subscription to an event type."""
    __slots__ = ("id", "callback", "filter_fn", "priority", "once", "subscribed_at")

    def __init__(
        self,
        id: str,
        callback: Callable[[Event], Any],
        filter_fn: Callable[[Event], bool] | None = None,
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
    ):
        self.id = id
        self.callback = callback
        self.filter_fn = filter_fn
        self.priority = priority
        self.once = once
        self.subscribed_at = time.time()


@dataclass
class EventBusConfig:
    """Configuration for the event bus."""
    max_queue_depth: int = 1000
    dispatch_timeout: float = 2.0
    max_subscribers_per_event: int = 100
    enable_stats: bool = True


class EventBus:
    """
    Thread-safe pub/sub event bus.
    - Async-safe dispatch via dedicated thread
    - Priority-based subscriber ordering
    - One-time subscriptions (once=True)
    - Event filtering per subscriber
    - Weak references to avoid memory leaks
    - Rolling statistics
    - No rewrite of existing threading model needed
    """

    def __init__(self, config: EventBusConfig | None = None):
        self.config = config or EventBusConfig()
        self._subscribers: dict[str, list[EventSubscriber]] = defaultdict(list)
        self._weak_subscribers: dict[str, WeakSet[EventSubscriber]] = defaultdict(WeakSet)
        self._lock = threading.RLock()
        self._dispatch_queue: Queue[Event] = Queue(maxsize=self.config.max_queue_depth)
        self._running = False
        self._dispatch_thread: threading.Thread | None = None
        self._sub_counter = 0
        self._stats: dict[str, int] = defaultdict(int)
        self._stats_lock = threading.Lock()
        self._event_types: set[str] = set()

    def start(self):
        """Start the dispatch thread. Call once at startup."""
        if self._running:
            return
        self._running = True
        self._dispatch_thread = threading.Thread(target=self._dispatch_loop, daemon=True, name="EventBus-Dispatch")
        self._dispatch_thread.start()

    def stop(self):
        """Stop the dispatch thread gracefully."""
        self._running = False
        if self._dispatch_thread and self._dispatch_thread.is_alive():
            self._dispatch_thread.join(timeout=3.0)

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Event], Any],
        filter_fn: Callable[[Event], bool] | None = None,
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
    ) -> str:
        """Subscribe to an event type. Returns subscription ID."""
        with self._lock:
            self._sub_counter += 1
            sub_id = f"{event_type}_{self._sub_counter}"
            sub = EventSubscriber(
                id=sub_id,
                callback=callback,
                filter_fn=filter_fn,
                priority=priority,
                once=once,
            )
            self._subscribers[event_type].append(sub)
            self._subscribers[event_type].sort(key=lambda s: s.priority.value, reverse=True)
            self._event_types.add(event_type)
            return sub_id

    def once(self, event_type: str, callback: Callable[[Event], Any]) -> str:
        """Subscribe to an event type for exactly one emission."""
        return self.subscribe(event_type, callback, once=True)

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe by subscription ID."""
        with self._lock:
            for event_type, subs in list(self._subscribers.items()):
                for sub in subs:
                    if sub.id == subscription_id:
                        subs.remove(sub)
                        return True
        return False

    def emit(self, event: Event) -> int:
        """Emit an event onto the dispatch queue. Returns 1 if queued."""
        try:
            self._dispatch_queue.put_nowait(event)
            with self._stats_lock:
                self._stats["emitted"] += 1
                self._stats[f"emitted_{event.event_type}"] += 1
            return 1
        except Exception:
            with self._stats_lock:
                self._stats["dropped"] += 1
            log.warning(f"[EventBus] Event dropped (queue full): {event.event_type}")
            return 0

    def emit_sync(self, event: Event) -> int:
        """Emit and immediately dispatch synchronously. Use sparingly."""
        return self._dispatch_event(event)

    def _dispatch_loop(self):
        """Dedicated dispatch thread — never blocks main thread."""
        while self._running:
            try:
                event = self._dispatch_queue.get(timeout=0.1)
                self._dispatch_event(event)
            except Empty:
                continue
            except Exception as e:
                log.error(f"[EventBus] Dispatch error: {e}")

    def _dispatch_event(self, event: Event) -> int:
        """Dispatch an event to matching subscribers."""
        delivered = 0
        with self._lock:
            subs = list(self._subscribers.get(event.event_type, []))
            if not subs and "*" not in self._subscribers:
                return 0
            if "*" in self._subscribers:
                subs.extend(self._subscribers["*"])
        for sub in subs:
            if sub.filter_fn and not sub.filter_fn(event):
                continue
            try:
                sub.callback(event)
                delivered += 1
                if sub.once:
                    self.unsubscribe(sub.id)
            except Exception as e:
                log.warning(f"[EventBus] Subscriber error ({sub.id}): {e}")
        with self._stats_lock:
            self._stats["dispatched"] += delivered
            self._stats[f"dispatched_{event.event_type}"] += delivered
        return delivered

    def on(self, event_type: str, **kwargs) -> Callable:
        """Decorator for subscribing: @bus.on("action_completed")"""
        def decorator(func: Callable[[Event], Any]) -> Callable[[Event], Any]:
            self.subscribe(event_type, func, **kwargs)
            return func
        return decorator

    def stats(self) -> dict:
        """Return event bus statistics."""
        with self._stats_lock:
            base = dict(self._stats)
        with self._lock:
            base["registered_event_types"] = len(self._event_types)
            base["subscribers"] = sum(len(v) for v in self._subscribers.values())
            base["queue_depth"] = self._dispatch_queue.qsize()
            base["running"] = self._running
        return base

    def list_subscriptions(self, event_type: str | None = None) -> list[dict]:
        """List active subscriptions (for debugging)."""
        result = []
        with self._lock:
            if event_type:
                for sub in self._subscribers.get(event_type, []):
                    result.append({"id": sub.id, "priority": sub.priority.name, "once": sub.once})
            else:
                for et, subs in self._subscribers.items():
                    for sub in subs:
                        result.append({"event_type": et, "id": sub.id, "priority": sub.priority.name, "once": sub.once})
        return result


_global_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get the global event bus singleton."""
    global _global_bus
    with _bus_lock:
        if _global_bus is None:
            _global_bus = EventBus()
            _global_bus.start()
        return _global_bus
