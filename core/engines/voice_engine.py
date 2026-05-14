# core/engines/voice_engine.py — JARVIS VOICE ENGINE (STT + Mic)
from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger("VoiceEngine")

# Vosk model path (already downloaded to vosk-model-small-en-us-0.15/)
_MODEL_DIR = os.path.join("vosk-model-small-en-us-0.15")
_MODEL_CONF = os.path.join(_MODEL_DIR, "conf")

# Audio stream parameters
_CHUNK_SIZE  = 4096   # samples per read
_SAMPLE_RATE = 16000  # Vosk expects 16kHz mono


class VoiceEngine:
    """
    Real-time speech-to-text using Vosk (offline, no API key needed).

    Vosk model is lightweight (~45MB) and runs entirely on CPU.
    Recognised phrases are submitted to the command orchestrator.
    """

    def __init__(self, poll_interval: float = 0.1):
        self.poll_interval  = poll_interval
        self._recogniser    = None
        self._stream        = None
        self._ready         = False
        self._init_lock     = threading.Lock()
        self._transcript_lock = threading.Lock()  # FIX: thread-safe transcript access
        self._last_transcript = ""
        self._running       = False
        self._thread        = threading.Thread(target=self._init_and_listen,
                                               daemon=True, name="VoskListener")
        self._thread.start()

    # ── Lazy init (runs on background thread) ─────────────────────────────

    def _init_and_listen(self):
        with self._init_lock:
            try:
                import sounddevice as sd
                import numpy as np
                import vosk

                if not os.path.exists(_MODEL_DIR):
                    log.warning("[VoiceEngine] Vosk model not found — voice disabled.")
                    return

                model_path = _MODEL_DIR
                if not os.path.isdir(model_path):
                    log.warning("[VoiceEngine] Invalid Vosk model path — voice disabled.")
                    return

                log.info(f"[VoiceEngine] Loading Vosk model from {model_path}...")
                model = vosk.Model(model_path)
                self._recogniser = vosk.KaldiRecognizer(model, _SAMPLE_RATE)
                log.info("[VoiceEngine] Vosk model loaded.")

                self._stream = sd.InputStream(
                    samplerate=_SAMPLE_RATE,
                    channels=1,
                    blocksize=_CHUNK_SIZE,
                    dtype="int16",
                    callback=self._audio_callback,
                )
                self._stream.start()
                self._ready   = True
                self._running = True
                log.info("[VoiceEngine] Microphone stream open.")

            except ImportError:
                log.warning("[VoiceEngine] sounddevice/vosk not installed — voice disabled.")
                log.warning("[VoiceEngine]   Install with: pip install sounddevice vosk")
            except Exception as e:
                log.error(f"[VoiceEngine] Init error: {e}")

        # Keep thread alive while running
        while self._running:
            time.sleep(0.5)

    # ── Audio callback (called from sounddevice thread) ──────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            log.debug(f"[VoiceEngine] Audio status: {status}")
        if not self._ready or self._recogniser is None:
            return

        audio_bytes = bytes(indata)
        if self._recogniser.AcceptWaveform(audio_bytes):
            result = self._recogniser.Result()
            try:
                import json as _json
                text = _json.loads(result).get("text", "").strip()
                if text:
                    log.info(f"[VoiceEngine] Heard: {text}")
                    self._on_transcript(text)
            except Exception as e:
                log.debug(f"[VoiceEngine] Parse error: {e}")

    # ── Override in orchestrator ───────────────────────────────────────────

    def _on_transcript(self, text: str):
        """Fired when Vosk produces a final transcript."""
        with self._transcript_lock:
            self._last_transcript = text

    def listen(self) -> str:
        """Blocking read — returns transcript produced by _audio_callback."""
        if not self._ready:
            time.sleep(self.poll_interval)
            return ""

        # Poll for new transcript every poll_interval seconds
        with self._transcript_lock:
            last = self._last_transcript
        for _ in range(int(5.0 / self.poll_interval)):
            time.sleep(self.poll_interval)
            with self._transcript_lock:
                curr = self._last_transcript
            if curr and curr != last:
                with self._transcript_lock:
                    self._last_transcript = ""   # consume
                return curr
        return ""

    def stop(self):
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass