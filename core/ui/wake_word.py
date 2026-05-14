# core/wake_word.py — JARVIS WAKE-WORD DAEMON
# ──────────────────────────────────────────────────────────────────────────────
# Always-on "Hey JARVIS" detection using pvporcupine (offline, ~2% CPU).
# Runs in a daemon thread. When the wake-word fires, calls on_wake_callback().
#
# SETUP (one-time):
#   pip install pvporcupine sounddevice
#   Get a free API key at: https://console.picovoice.ai/
#   Set env var: PORCUPINE_KEY=your_key_here
#   Or drop your key in memory/porcupine.key
#
# FALLBACK (no pvporcupine):
#   Uses energy-threshold VAD on sounddevice — not a true wake-word,
#   but allows hands-free activation by sustained loud sound (clap/snap).
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import threading
import time
import logging
from typing import Callable

log = logging.getLogger("wake_word")

# ── Key / model discovery ────────────────────────────────────────────────────
_KEY_ENV   = "PORCUPINE_KEY"
_KEY_FILE  = os.path.join("memory", "porcupine.key")
_SENSITIVITY = 0.65   # 0.0 (strict) – 1.0 (sensitive)


def _get_porcupine_key() -> str | None:
    """Check env var first, then memory/porcupine.key file."""
    key = os.environ.get(_KEY_ENV, "").strip()
    if key:
        return key
    if os.path.exists(_KEY_FILE):
        try:
            key = open(_KEY_FILE).read().strip()
            if key:
                return key
        except Exception:
            pass
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  VAD Fallback — energy-threshold "clap" wake trigger (no API key required)
# ══════════════════════════════════════════════════════════════════════════════

class _VadFallback:
    """
    Listens for 2 loud sounds within 1.5 seconds (double-clap) as a wake trigger.
    Zero dependencies beyond sounddevice.

    Bug fixes (v2):
      - POST_WAKE_COOLDOWN: 3s lock after each activation prevents re-triggering
        while JARVIS is speaking (microphone picks up its own TTS output)
      - _waking Event: prevents concurrent activations from stacking up threads
      - Fixed last_loud=0.0 reset bug: was immediately re-qualifying next loud sound
    """
    _THRESHOLD       = 2500   # RMS amplitude — increased to reduce false positives
    _DOUBLE_TAP_S    = 1.5    # seconds window for double-clap
    _POST_WAKE_COOLDOWN = 3.0 # seconds to ignore mic after wake fires (JARVIS is speaking)

    def __init__(self, callback: Callable):
        self._callback  = callback
        self._running   = False
        self._last_loud = 0.0
        self._last_wake = 0.0          # timestamp of last successful wake
        self._waking    = threading.Event()   # set while JARVIS is processing wake
        self._stop_evt  = threading.Event()   # set by stop() for clean exit
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True, name="VadWake")
        self._thread.start()
        log.info("[WakeWord] VAD fallback started (double-clap to activate JARVIS).")
        print("[WakeWord] No Porcupine key — using double-clap/sound VAD wake trigger.")
        print("[WakeWord]   Clap twice within 1.5 s to wake JARVIS.")

    def stop(self):
        self._running = False
        self._stop_evt.set()   # wake the sleep immediately

    def _fire_wake(self):
        """Run callback then release the waking lock after cooldown."""
        try:
            self._callback()
        except Exception as e:
            log.error(f"[WakeWord] Wake callback error: {e}")
        finally:
            # Hold the cooldown so mic input during JARVIS's TTS response is ignored
            time.sleep(self._POST_WAKE_COOLDOWN)
            self._waking.clear()
            self._last_wake = time.time()
            self._last_loud = 0.0   # safe to reset NOW (after cooldown)
            log.debug("[WakeWord] Wake cooldown released.")

    def _run(self):
        try:
            import sounddevice as sd  # type: ignore[import-untyped]  # optional dep
            import numpy as np

            CHUNK = 1024
            RATE  = 16000

            def _audio_cb(indata, frames, time_info, status):
                if not self._running:
                    return
                # Ignore all audio while in cooldown (JARVIS is speaking/processing)
                if self._waking.is_set():
                    return
                if time.time() - self._last_wake < self._POST_WAKE_COOLDOWN:
                    return

                rms = float(np.sqrt(np.mean(indata.astype("float32") ** 2)))
                if rms > self._THRESHOLD:
                    now = time.time()
                    gap = now - self._last_loud
                    if 0.1 < gap < self._DOUBLE_TAP_S:
                        # Valid double-tap: gap > 100ms (not same sound) and < 1.5s
                        if not self._waking.is_set():
                            self._waking.set()
                            log.info("[WakeWord] VAD double-tap detected — waking JARVIS.")
                            threading.Thread(
                                target=self._fire_wake, daemon=True, name="VadWakeFire"
                            ).start()
                        self._last_loud = 0.0   # prevent triple-tap from re-firing
                    else:
                        self._last_loud = now   # first tap — save timestamp

            with sd.InputStream(
                samplerate=RATE,
                channels=1,
                blocksize=CHUNK,
                dtype="int16",
                callback=_audio_cb
            ):
                while self._running:
                    self._stop_evt.wait(timeout=0.1)   # interruptible 100ms poll
                    self._stop_evt.clear()

        except ImportError:
            print("[WakeWord] sounddevice not installed — wake-word disabled.")
            print("[WakeWord]   Install with:  pip install sounddevice")
        except Exception as e:
            log.error(f"[WakeWord] VAD error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  Porcupine Engine — true keyword spotting, offline, ~2% CPU
# ══════════════════════════════════════════════════════════════════════════════

class _PorcupineEngine:
    """
    Wraps pvporcupine for "Hey JARVIS" keyword detection.
    Uses the built-in "jarvis" keyword model (no custom training needed).
    """

    def __init__(self, key: str, callback: Callable):
        self._key      = key
        self._callback = callback
        self._running  = False
        self._stop_evt = threading.Event()   # for interruptible waits
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._stop_evt.clear()
        self._thread  = threading.Thread(target=self._run, daemon=True, name="PorcupineWake")
        self._thread.start()
        print("[WakeWord] Porcupine engine started — say 'Hey JARVIS' to activate.")

    def stop(self):
        self._running = False
        self._stop_evt.set()   # wake any wait() calls immediately

    def _run(self):
        try:
            import pvporcupine  # type: ignore[import-untyped]  # optional dep
            import sounddevice as sd  # type: ignore[import-untyped]  # optional dep
            import numpy as np

            porcupine = pvporcupine.create(
                access_key=self._key,
                keywords=["jarvis"],
                sensitivities=[_SENSITIVITY],
            )
            FRAME = porcupine.frame_length   # typically 512 samples

            def _audio_cb(indata, frames, time_info, status):
                if not self._running:
                    return
                pcm = np.frombuffer(indata, dtype="int16").tolist()
                # Porcupine needs exactly frame_length samples
                if len(pcm) >= FRAME:
                    keyword_index = porcupine.process(pcm[:FRAME])
                    if keyword_index >= 0:
                        log.info("[WakeWord] 'Hey JARVIS' detected! Activating microphone.")
                        threading.Thread(target=self._callback, daemon=True).start()

            with sd.RawInputStream(
                samplerate=porcupine.sample_rate,
                blocksize=FRAME,
                dtype="int16",
                channels=1,
                callback=_audio_cb,
            ):
                while self._running:
                    self._stop_evt.wait(timeout=0.1)
                    self._stop_evt.clear()

            porcupine.delete()

        except ImportError:
            print("[WakeWord] pvporcupine not installed — falling back to VAD.")
            print("[WakeWord]   Install with:  pip install pvporcupine")
            # Graceful fallback
            _VadFallback(self._callback).start()
            while self._running:
                self._stop_evt.wait(timeout=1)
                self._stop_evt.clear()
        except Exception as e:
            log.error(f"[WakeWord] Porcupine error: {e}")
            # Graceful fallback
            _VadFallback(self._callback).start()
            while self._running:
                self._stop_evt.wait(timeout=1)
                self._stop_evt.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  Public WakeWordDaemon — auto-selects best available engine
# ══════════════════════════════════════════════════════════════════════════════

class WakeWordDaemon:
    """
    Public interface. Auto-selects:
      • Porcupine  — if PORCUPINE_KEY env var or memory/porcupine.key exists
      • VAD clap   — fallback requiring no API key

    Usage:
        from core.ui.wake_word import WakeWordDaemon
        daemon = WakeWordDaemon(on_wake=lambda: brain.process("_WAKE_WORD_"))
        daemon.start()
    """

    def __init__(self, on_wake: Callable):
        self._on_wake = on_wake
        self._engine  = None
        self._active  = False

    def start(self):
        if self._active:
            return
        key = _get_porcupine_key()
        if key:
            self._engine = _PorcupineEngine(key, self._on_wake)
        else:
            self._engine = _VadFallback(self._on_wake)
        self._engine.start()
        self._active = True

    def stop(self):
        if self._engine:
            self._engine.stop()
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active


# Module singleton
_daemon: WakeWordDaemon | None = None


def get_wake_daemon(on_wake: Callable | None = None) -> WakeWordDaemon:
    """Return or create the module-level singleton."""
    global _daemon
    if _daemon is None:
        if on_wake is None:
            raise ValueError("on_wake callback required for first call to get_wake_daemon()")
        _daemon = WakeWordDaemon(on_wake=on_wake)
    return _daemon
