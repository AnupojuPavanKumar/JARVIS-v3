"""
core/engines/speech_dispatcher.py — Speech Dispatch Service
============================================================
Decouples TTS routing from JarvisBrain. Any component that needs to
produce speech should use this dispatcher rather than directly publishing
to the event bus or calling the speech engine.

Responsibilities:
  - Route text to TTS via the event bus (EventSpeechRequested)
  - Enforce priority queueing (critical alerts jump the queue)
  - Track the "speaking" state so the brain doesn't double-speak
  - Expose a stop_speaking() API for voice interruption
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

log = logging.getLogger("SpeechDispatcher")


class SpeechDispatcher:
    """
    Single-responsibility TTS dispatch gateway for JARVIS-v3.

    All speech requests from Brain, Scheduler, and SystemWatcher flow
    through here. Thread-safe.
    """

    def __init__(self):
        self._lock    = threading.Lock()
        self._speaking = False
        self._engine: Optional[object] = None   # SpeechEngine ref, set lazily

    # ── Core Dispatch ────────────────────────────────────────────────────────

    def speak(self, text: str, priority: str = "default", stream: bool = False):
        """
        Route text to TTS via the EventBus.

        Args:
            text:     The text to speak.
            priority: "critical" causes the speech engine to interrupt current speech.
            stream:   If True, publish to "response.text" (stream-to-audio pipeline).
                      If False, publish to EventSpeechRequested (legacy path).
        """
        if not text or not text.strip():
            return
        try:
            from core.system.event_bus import get_event_bus
            from core.system.events import EventSpeechRequested
            bus = get_event_bus()

            if stream:
                bus.publish("response.text", {
                    "topic": "response.text",
                    "text": text,
                    "stream": True,
                    "identity": "owner",
                    "timestamp": time.time(),
                })
            else:
                bus.publish(EventSpeechRequested(text=text, priority=priority))
        except Exception as exc:
            log.error(f"[SpeechDispatcher] speak() failed: {exc}")

    def speak_critical(self, text: str):
        """Interrupt any current speech and speak immediately."""
        self.stop_speaking()
        self.speak(text, priority="critical")

    # ── Interruption ─────────────────────────────────────────────────────────

    def set_engine(self, engine):
        """Wire the actual SpeechEngine for direct stop_speaking() calls."""
        self._engine = engine

    def stop_speaking(self):
        """Stop any currently playing TTS audio."""
        if self._engine is None:
            return
        try:
            self._engine.stop_speaking()
        except Exception as exc:
            log.debug(f"[SpeechDispatcher] stop_speaking: {exc}")

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def set_speaking(self, value: bool):
        with self._lock:
            self._speaking = value

    # ── NTFY Push convenience ─────────────────────────────────────────────────

    def push_notification(self, title: str, message: str, priority: str = "default"):
        """Publish a push notification via the event bus."""
        try:
            from core.system.event_bus import get_event_bus
            from core.system.events import EventNtfyPush
            get_event_bus().publish(EventNtfyPush(title=title, message=message, priority=priority))
        except Exception as exc:
            log.error(f"[SpeechDispatcher] push_notification failed: {exc}")


# ── Module singleton ─────────────────────────────────────────────────────────

_instance: Optional[SpeechDispatcher] = None
_init_lock = threading.Lock()


def get_speech_dispatcher() -> SpeechDispatcher:
    global _instance
    if _instance is None:
        with _init_lock:
            if _instance is None:
                _instance = SpeechDispatcher()
    return _instance
