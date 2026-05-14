import logging
import threading
from typing import Any, Callable, Dict, List, Type, TypeVar
from core.system.events import Event

T = TypeVar("T", bound=Event)

class EventBus:
    """
    Thread-safe Pub/Sub Event Bus for JARVIS-v3.
    Subscribers are called on a dedicated daemon thread to avoid blocking the publisher.
    """
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(EventBus, cls).__new__(cls)
                cls._instance._subscribers: Dict = {}
                cls._instance._logger = logging.getLogger("EventBus")
                if not cls._instance._logger.handlers:
                    handler = logging.StreamHandler()
                    formatter = logging.Formatter('[%(name)s] %(levelname)s: %(message)s')
                    handler.setFormatter(formatter)
                    cls._instance._logger.addHandler(handler)
                    cls._instance._logger.setLevel(logging.INFO)
        return cls._instance

    def subscribe(self, event_type: Type[T] | str, callback: Callable[[Any], None]):
        """Subscribe a callback to a specific event type."""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            if callback not in self._subscribers[event_type]:
                self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: Type[T] | str, callback: Callable[[Any], None]):
        """Unsubscribe a callback from a specific event type."""
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(callback)
                except ValueError:
                    pass

    def publish(self, event: Event | str, payload: Any = None):
        """
        Publish an event to all subscribers of its type.
        Each subscriber is called on a short-lived daemon thread so slow/hung
        subscribers cannot block the publisher or each other.
        """
        if isinstance(event, str):
            event_type = event
            delivered = payload
        else:
            event_type = type(event)
            delivered = event

        # Snapshot under lock so subscriber mutations during delivery are safe
        with self._lock:
            subscribers = list(self._subscribers.get(event_type, []))

        if not subscribers:
            return

        for callback in subscribers:
            def _call(cb=callback, data=delivered):
                try:
                    cb(data)
                except Exception as e:
                    event_name = event_type if isinstance(event_type, str) else event_type.__name__
                    self._logger.error(
                        f"Error in subscriber {cb} for {event_name}: {e}", exc_info=True
                    )
            threading.Thread(target=_call, daemon=True, name="EventBus-Dispatch").start()


# Singleton Accessor
def get_event_bus() -> EventBus:
    return EventBus()
