# core/companion/recovery.py — JARVIS GRACEFUL RECOVERY ENGINE
"""
Handles failures gracefully — no chaotic crashes or awkward dead silence.
Covers:
  - Ollama unavailable (local fallback chain)
  - provider timeout (retry + degrade)
  - audio device lost (silent recovery)
  - model load failure (swap model)
  - subsystem crash (restart + log)

Every failure produces a calm, understandable response.
No panic. No "ERROR ERROR ERROR". No confusing stack traces.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

log = logging.getLogger("Recovery")

class FailureLevel(Enum):
    MINOR    = auto()   # silent retry, no user notification
    MODERATE = auto()   # log + graceful fallback
    MAJOR    = auto()   # log + inform user calmly
    CRITICAL = auto()   # log + critical alert + degraded mode


@dataclass
class RecoveryResult:
    success: bool
    level: FailureLevel
    message: str          # human-readable calm explanation
    recovered: bool       # True if recovered via fallback
    fallback_used: str | None  # what fallback was used


class RecoveryEngine:
    """
    Centralised failure handling.
    Call handle_failure() with context → returns RecoveryResult.
    Callers use result.message for TTS output.
    """

    def __init__(self):
        self._lock       = threading.RLock()
        self._failures   = 0
        self._recoveries = 0
        self._degraded   = False
        self._degraded_since: float = 0.0
        self._last_failure_time: float = 0.0

        # Fallback chains
        self._ollama_fallback_chain = [
            ("gemma2:2b",     "local chat model"),
            ("phi3:mini",      "lightweight model"),
            ("llama3.2:3b",   "conversational model"),
            ("local_chat",     "minimal local inference"),
        ]

        self._tts_fallback_chain = [
            ("kokoro",        "neural TTS"),
            ("pyttsx3",       "system TTS"),
            ("edge_tts",       "cloud TTS"),
            ("silent",         "text-only mode"),
        ]

        self._stt_fallback_chain = [
            ("vosk",          "offline speech recognition"),
            ("vad_clap",      "sound-activated listening"),
            ("text_only",      "keyboard input only"),
        ]

    @property
    def is_degraded(self) -> bool:
        with self._lock:
            return self._degraded

    @property
    def health_stats(self) -> dict:
        with self._lock:
            return {
                "failures":        self._failures,
                "recoveries":      self._recoveries,
                "is_degraded":     self._degraded,
                "degraded_duration": time.time() - self._degraded_since if self._degraded else 0,
            }

    def handle_ollama_failure(
        self,
        operation: str,
        error: str,
        tried: list[str] | None = None,
    ) -> RecoveryResult:
        """Handle Ollama/provider failures with graceful degradation."""
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()

        tried = tried or []
        remaining = [f for f in self._ollama_fallback_chain if f[0] not in tried]

        if remaining:
            level = FailureLevel.MODERATE
            fallback_name, fallback_desc = remaining[0]
            message = self._build_message(operation, fallback_name, fallback_desc, error)
            recovered = True
        else:
            level = FailureLevel.MAJOR
            message = self._final_ollama_failure(operation)
            recovered = False
            self._set_degraded()

        with self._lock:
            if recovered:
                self._recoveries += 1

        return RecoveryResult(
            success=recovered,
            level=level,
            message=message,
            recovered=recovered,
            fallback_used=remaining[0][0] if remaining else None,
        )

    def handle_tts_failure(self, text: str, error: str) -> RecoveryResult:
        """Handle TTS failures."""
        with self._lock:
            self._failures += 1

        message = f"Voice temporarily unavailable. {text}."  # Fallback to text display
        return RecoveryResult(
            success=True,
            level=FailureLevel.MODERATE,
            message=message,
            recovered=True,
            fallback_used="text_only",
        )

    def handle_timeout(self, operation: str, timeout_s: float) -> RecoveryResult:
        """Handle operation timeouts — slow but not broken."""
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()

        message = f"{operation} timed out. Please try again."
        return RecoveryResult(
            success=False,
            level=FailureLevel.MODERATE,
            message=message,
            recovered=False,
            fallback_used=None,
        )

    def handle_subsystem_crash(self, subsystem: str) -> RecoveryResult:
        """Handle a subsystem crash — major but recoverable."""
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()

        subsystem_map = {
            "ollama":    "AI inference subsystem",
            "stt":       "speech recognition",
            "wake_word": "wake-word detector",
            "tts":       "voice output",
            "workspace": "workspace observer",
        }
        name = subsystem_map.get(subsystem, subsystem)
        message = f"The {name} encountered an issue. Switching to degraded mode for now."
        self._set_degraded()

        return RecoveryResult(
            success=False,
            level=FailureLevel.MAJOR,
            message=message,
            recovered=False,
            fallback_used=None,
        )

    def record_recovery(self):
        """Call when a failure resolves."""
        with self._lock:
            self._recoveries += 1
            if self._degraded:
                self._degraded = False

    def _set_degraded(self):
        with self._lock:
            if not self._degraded:
                self._degraded = True
                self._degraded_since = time.time()

    def _build_message(
        self, operation: str, fallback_name: str, fallback_desc: str, error: str
    ) -> str:
        """Construct a calm, human-readable recovery message."""
        fallback_map = {
            "gemma2:2b":    "Switching to a lighter model.",
            "phi3:mini":    "Switching to the lightweight model.",
            "llama3.2:3b":  "Falling back to the conversational model.",
            "local_chat":  "Using minimal inference mode.",
            "silent":       "Showing result as text instead.",
        }
        suffix = fallback_map.get(fallback_name, f"Switching to {fallback_desc}.")
        return f"{operation}. {suffix}"

    def _final_ollama_failure(self, operation: str) -> str:
        """Final message when all fallbacks exhausted."""
        return (
            f"{operation}. "
            "The AI models are unavailable right now. "
            "Please check Ollama and try again, sir."
        )

    def get_health_summary(self) -> str:
        """One-line health summary for the UI."""
        with self._lock:
            if self._degraded:
                dur = time.time() - self._degraded_since
                return f"Degraded {dur/60:.0f}m — {self._failures} failures"
            if self._failures == 0:
                return "All systems nominal"
            ratio = self._recoveries / max(1, self._failures)
            return f"Healthy — {self._recoveries}/{self._failures} failures recovered"


_instance: Optional[RecoveryEngine] = None
_lock = threading.Lock()

def get_recovery_engine() -> RecoveryEngine:
    global _instance
    with _lock:
        if _instance is None:
            _instance = RecoveryEngine()
        return _instance