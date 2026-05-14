# core/system/degradation_persona.py — JARVIS DEGRADATION IDENTITY PRESERVATION
"""
Ensures JARVIS remains calm, coherent, and recognizable during degraded states.

Prevents:
  - Erratic silence (subsystem fail → JARVIS goes quiet with no explanation)
  - Robotic behavior shifts (terse/mechanical tone when degraded)
  - Personality collapse under pressure

Strategy:
  - Announce degraded state in natural voice language
  - Maintain consistent tone during limitation periods
  - Provide appropriate capability reduction messages
  - Prevent silent failures from appearing as ignorance
"""
from __future__ import annotations

import threading
import time
from enum import Enum, auto
from typing import Callable, Optional

import logging

log = logging.getLogger("DegradationPersona")


class DegradationSeverity(Enum):
    MINOR    = auto()   # one subsystem degraded — mention casually
    MODERATE = auto()   # multiple subsystems — explain limitations clearly
    MAJOR    = auto()   # core capabilities down — proactive announcement
    CRITICAL = auto()   # minimal function — full disclosure


# Natural language templates keyed by (subsystem_category, severity)
_TEMPLATES: dict[str, dict[DegradationSeverity, str]] = {
    "voice": {
        DegradationSeverity.MINOR:    "My voice recognition is a bit slow right now — I'm still listening.",
        DegradationSeverity.MODERATE: "I'm having some trouble with my voice pipeline. Text commands will work more reliably.",
        DegradationSeverity.MAJOR:    "My voice system is degraded. I'll do my best, but I may miss some commands.",
        DegradationSeverity.CRITICAL: "My audio systems are offline. I can still help through text.",
    },
    "ai": {
        DegradationSeverity.MINOR:    "My AI processing is slightly slower than usual — bear with me.",
        DegradationSeverity.MODERATE: "I'm running in a limited AI mode right now. Some complex tasks may take longer.",
        DegradationSeverity.MAJOR:    "My AI inference is degraded. I'll handle what I can, but complex requests may fail.",
        DegradationSeverity.CRITICAL: "My AI engine is offline. I'm operating on deterministic responses only.",
    },
    "memory": {
        DegradationSeverity.MINOR:    "My session memory is a bit unreliable — I may need reminders occasionally.",
        DegradationSeverity.MODERATE: "I'm experiencing some memory issues. I'll remember what I can, but continuity may be limited.",
        DegradationSeverity.MAJOR:    "My memory systems are degraded. This session may not be fully preserved.",
        DegradationSeverity.CRITICAL: "My memory is offline. Each request will be handled fresh.",
    },
    "automation": {
        DegradationSeverity.MINOR:    "Proactive suggestions are paused while I recalibrate.",
        DegradationSeverity.MODERATE: "I've reduced my automation for stability. I'll focus on direct requests.",
        DegradationSeverity.MAJOR:    "Automation systems are suspended. I'm in focused manual mode.",
        DegradationSeverity.CRITICAL: "Automation is offline. Manual commands only.",
    },
    "runtime": {
        DegradationSeverity.MINOR:    "I'm running at slightly reduced capacity — everything should still work.",
        DegradationSeverity.MODERATE: "I'm under some system pressure. Performance may be reduced temporarily.",
        DegradationSeverity.MAJOR:    "I'm managing significant resource constraints. I'll prioritize essential functions.",
        DegradationSeverity.CRITICAL: "System resources are critically constrained. I'm in survival mode.",
    },
}

_RECOVERY_MESSAGES = {
    "voice":      "My voice system is recovering — should be back shortly.",
    "ai":         "AI inference is coming back online.",
    "memory":     "Memory systems are stabilizing.",
    "automation": "Resuming proactive features.",
    "runtime":    "System pressure is easing.",
}

# Category → domain
_SUBSYSTEM_CATEGORY = {
    "voice_tts": "voice", "voice_stt": "voice", "wake_word": "voice",
    "voice_worker": "voice", "voice_interrupt": "voice",
    "ollama_manager": "ai", "model_prewarmer": "ai", "ollama_inference": "ai",
    "checkpoint_manager": "memory", "layered_memory": "memory",
    "session_continuity": "memory", "cognitive_continuity": "memory",
    "suggestion_engine": "automation", "workspace_observer": "automation",
    "telemetry": "automation",
    "watchdog": "runtime", "pressure_governor": "runtime",
    "hardware_sentinel": "runtime",
}


class DegradationPersona:

    _instance: Optional[DegradationPersona] = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._announced: dict[str, float] = {}   # category → last_announced_ts
        self._speak_cb:  Optional[Callable[[str], None]] = None
        self._min_announce_interval = 120.0      # don't repeat same category < 2 min

    def set_speak_callback(self, cb: Callable[[str], None]):
        self._speak_cb = cb

    def on_subsystem_degraded(self, subsystem: str, severity: DegradationSeverity):
        category = _SUBSYSTEM_CATEGORY.get(subsystem, "runtime")
        self._announce_degradation(category, severity)

    def on_subsystem_failed(self, subsystem: str):
        category = _SUBSYSTEM_CATEGORY.get(subsystem, "runtime")
        self._announce_degradation(category, DegradationSeverity.MAJOR)

    def on_subsystem_recovered(self, subsystem: str):
        category = _SUBSYSTEM_CATEGORY.get(subsystem, "runtime")
        msg = _RECOVERY_MESSAGES.get(category)
        if msg:
            self._speak(msg)
            # Clear announcement throttle so next degradation can announce
            with self._lock:
                self._announced.pop(category, None)

    def on_pressure_critical(self):
        self._announce_degradation("runtime", DegradationSeverity.CRITICAL)

    def _announce_degradation(self, category: str, severity: DegradationSeverity):
        now = time.time()
        with self._lock:
            last = self._announced.get(category, 0.0)
            if now - last < self._min_announce_interval:
                return
            self._announced[category] = now

        templates = _TEMPLATES.get(category, _TEMPLATES["runtime"])
        msg = templates.get(severity, templates[DegradationSeverity.MINOR])
        log.info(f"[DegradationPersona] Announcing: {msg}")
        self._speak(msg)

    def _speak(self, text: str):
        if self._speak_cb:
            try:
                self._speak_cb(text)
            except Exception as e:
                log.debug(f"[DegradationPersona] Speak error: {e}")

    def get_diagnostics(self) -> dict:
        with self._lock:
            return {
                "last_announcements": {
                    cat: time.strftime("%H:%M:%S", time.localtime(ts))
                    for cat, ts in self._announced.items()
                },
                "speak_cb_set": self._speak_cb is not None,
            }


_instance: Optional[DegradationPersona] = None
_dp_lock = threading.Lock()


def get_degradation_persona() -> DegradationPersona:
    global _instance
    with _dp_lock:
        if _instance is None:
            _instance = DegradationPersona()
        return _instance
