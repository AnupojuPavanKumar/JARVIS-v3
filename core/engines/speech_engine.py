from __future__ import annotations

import logging
import threading
from typing import Optional

log = logging.getLogger("SpeechEngine")


class SpeechEngine:
    """Small offline-first TTS facade for legacy callers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._engine: Optional[object] = None
        self._com_initialized = False

    def _ensure_com(self):
        """Initialize COM once, not on every call."""
        if self._com_initialized:
            return
        try:
            import pythoncom
            pythoncom.CoInitialize()
            self._com_initialized = True
        except Exception:
            pass

    def _get_engine(self):
        with self._lock:
            if self._engine is not None:
                return self._engine
            self._ensure_com()
            try:
                import pyttsx3
                engine = pyttsx3.init("sapi5")
                engine.setProperty("rate", 175)
                engine.setProperty("volume", 0.95)
                self._engine = engine
            except Exception as exc:
                log.debug("[SpeechEngine] pyttsx3 unavailable: %s", exc)
                self._engine = False
            return self._engine

    def speak(self, text: str) -> None:
        if not text:
            return
        engine = self._get_engine()
        if not engine:
            print(f"[Speech] {text}")
            return
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            log.debug("[SpeechEngine] speak failed: %s", exc)
            print(f"[Speech] {text}")

    def stop_speaking(self) -> None:
        engine = self._get_engine()
        if engine:
            try:
                engine.stop()
            except Exception:
                pass

    stop = stop_speaking


_instance: Optional[SpeechEngine] = None


def get_speech_engine() -> SpeechEngine:
    global _instance
    if _instance is None:
        _instance = SpeechEngine()
    return _instance
