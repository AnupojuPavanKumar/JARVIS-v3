# core/voice_interruption.py — JARVIS Full-Duplex Voice Interruption (Upgrade #5)
# ──────────────────────────────────────────────────────────────────────────────
# Enables JARVIS to be interrupted MID-SPEECH using a wake phrase or silence VAD.
#
# Architecture:
#   A lightweight VAD (Voice Activity Detection) listener runs in a daemon
#   thread DURING TTS playback. When the user speaks (energy above threshold),
#   it immediately:
#     1. Kills current TTS audio (pygame.mixer.music.stop())
#     2. Drains the speech queue
#     3. Transcribes the user's interruption phrase (Vosk, fast, offline)
#     4. Passes the new command to the brain via the registered callback
#
# This is how Alexa/Siri work — full-duplex listening even while speaking.
#
# Interrupt modes:
#   WAKE_WORD   — only interrupt on specific words ("JARVIS", "stop", "wait")
#   VAD         — interrupt on ANY voice activity above threshold (more responsive)
#   HYBRID      — VAD triggers capture, then checks for wake word (recommended)
#
# Usage:
#   from core.ui.voice_interruption import get_voice_interruption
#   vi = get_voice_interruption()
#   vi.set_speech_engine(speech_engine)
#   vi.set_command_callback(brain.process)
#   vi.start()   # begin background listening
#   vi.stop()    # clean shutdown
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("VoiceInterruption")

# ── Constants ──────────────────────────────────────────────────────────────────
SAMPLE_RATE     = 16000
CHANNELS        = 1
CHUNK           = 1024              # samples per chunk (~64ms at 16kHz)
ENERGY_THRESH   = 300               # RMS energy threshold for VAD trigger
VAD_HOLD_MS     = 400               # ms of silence before VAD ends a phrase
MAX_PHRASE_S    = 8                 # max seconds to capture after VAD trigger
COOLDOWN_S      = 1.0               # seconds to wait after handling an interrupt
MIC_RECOVERY_DELAY_S = 5.0          # seconds to wait before retrying a locked mic

# Interrupt wake words — any of these spoken during TTS will trigger interruption
INTERRUPT_WORDS = {
    "jarvis", "stop", "wait", "hold on", "pause", "enough",
    "skip", "cancel", "quiet", "silence", "shut up", "ok jarvis"
}

# Vosk model path (already used by the main whisper/vosk voice engine)
_VOSK_PATHS = [
    "vosk-model-small-en-us-0.15",
    "vosk-model",
]


# ═══════════════════════════════════════════════════════════════════════════════
#  VAD HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def _rms(data: bytes) -> float:
    """Compute RMS energy of a PCM int16 audio chunk."""
    import struct
    count  = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"<{count}h", data[:count * 2])
    rms    = (sum(s ** 2 for s in shorts) / count) ** 0.5
    return rms


def _find_vosk_model() -> Optional[str]:
    """Return path to the best available Vosk model."""
    for path in _VOSK_PATHS:
        if os.path.isdir(path):
            return path
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  VOICE INTERRUPTION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class VoiceInterruption:
    """
    Full-duplex voice interruption engine.

    Runs a VAD listener in a background thread while JARVIS speaks.
    When the user's voice is detected mid-speech, it:
      1. Stops TTS immediately
      2. Transcribes the spoken command
      3. Routes it to the brain callback

    Modes: "hybrid" (default) | "vad" | "wake_word"
    """

    def __init__(self, mode: str = "hybrid"):
        self._mode:       str                    = mode
        self._running:    bool                   = False
        self._speech_eng                         = None   # SpeechEngine ref
        self._cmd_cb:     Optional[Callable]     = None   # brain.process ref
        self._speak_cb:   Optional[Callable]     = None   # speak reply back
        self._thread:     Optional[threading.Thread] = None
        self._vosk_model                         = None
        self._vosk_ok:    bool                   = False
        self._last_interrupt: float              = 0.0    # cooldown tracker
        self._enabled:    bool                   = True   # can be toggled
        self._vosk_ready: threading.Event        = threading.Event()
        self._mic_dead:   bool                   = False  # True when mic locked by another app

        # Load Vosk in background — avoids 392ms cold-start on main thread
        threading.Thread(
            target=self._init_vosk_bg,
            daemon=True,
            name="VoiceInterrupt-VoskLoad"
        ).start()

    # ── Setup ─────────────────────────────────────────────────────────────────

    def set_speech_engine(self, engine):
        """Register the SpeechEngine so we can stop it on interrupt."""
        self._speech_eng = engine

    def set_command_callback(self, cb: Callable[[str], str]):
        """Register brain.process — called with the transcribed interruption."""
        self._cmd_cb = cb

    def set_speak_callback(self, cb: Callable[[str], None]):
        """Register a function to speak JARVIS's reply (e.g. brain._speak_via_ui)."""
        self._speak_cb = cb

    def _init_vosk_bg(self):
        """Load Vosk recogniser in a background thread (avoids 392ms cold-start)."""
        try:
            from vosk import Model, KaldiRecognizer  # type: ignore[import]
            model_path = _find_vosk_model()
            if model_path:
                self._vosk_model = Model(model_path)
                self._vosk_ok    = True
                log.info(f"[VoiceInterruption] Vosk loaded: {model_path}")
            else:
                log.warning("[VoiceInterruption] Vosk model not found — transcription disabled.")
        except ImportError:
            log.warning("[VoiceInterruption] Vosk not installed — transcription disabled.")
        except Exception as e:
            log.warning(f"[VoiceInterruption] Vosk init error: {e}")
        finally:
            self._vosk_ready.set()  # signal that Vosk init is complete (success or fail)

    def _init_vosk(self):
        """Legacy alias — kept for compatibility."""
        pass

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        """Start the background VAD listener. Waits up to 5s for Vosk to be ready."""
        if self._running:
            return
        # Wait for Vosk background thread to finish (up to 5s)
        if not self._vosk_ready.wait(timeout=5.0):
            log.warning("[VoiceInterruption] Vosk not ready after 5s — starting without transcription.")
        self._running = True
        self._thread  = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="VoiceInterruption-VAD"
        )
        self._thread.start()
        log.info(f"[VoiceInterruption] Started in '{self._mode}' mode.")

    def stop(self):
        """Stop the VAD listener cleanly."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        log.info("[VoiceInterruption] Stopped.")

    def enable(self):
        self._enabled = True

    def disable(self):
        """Temporarily disable — useful when processing a command."""
        self._enabled = False

    @property
    def is_running(self) -> bool:
        return self._running

    # ── VAD listener loop ────────────────────────────────────────────────────

    def _listen_loop(self):
        """
        Outer recovery wrapper around _listen_once.
        If the microphone stream fails (e.g. another app locks it),
        we wait MIC_RECOVERY_DELAY_S and retry automatically.
        """
        import pyaudio as _pa_check  # noqa — validate import once before loop

        consecutive_failures = 0
        MAX_CONSECUTIVE = 5   # give up after 5 back-to-back crashes (hardware dead)

        while self._running:
            try:
                self._mic_dead = False
                self._listen_once()
                consecutive_failures = 0
            except ImportError:
                log.error("[VoiceInterruption] pyaudio not installed — interruption disabled.")
                return   # non-recoverable
            except (OSError, IOError) as e:
                consecutive_failures += 1
                self._mic_dead = True
                if consecutive_failures >= MAX_CONSECUTIVE:
                    log.error(
                        f"[VoiceInterruption] Mic failed {consecutive_failures} times in a row. "
                        f"Giving up. Last error: {e}"
                    )
                    return
                log.warning(
                    f"[VoiceInterruption] Mic stream lost (attempt {consecutive_failures}/{MAX_CONSECUTIVE}): "
                    f"{e}. Retrying in {MIC_RECOVERY_DELAY_S:.0f}s..."
                )
                # Countdown so we can bail out quickly if stop() is called
                for _ in range(int(MIC_RECOVERY_DELAY_S * 10)):
                    if not self._running:
                        return
                    time.sleep(0.1)
            except Exception as e:
                # Unexpected error — log and continue so we don't silently die
                log.error(f"[VoiceInterruption] Unexpected listen error: {e}")
                time.sleep(1.0)

    def _listen_once(self):
        """
        Open mic, listen until self._running is False or an OSError occurs.
        OSError is propagated to _listen_loop for recovery handling.
        """
        try:
            import pyaudio
        except ImportError:
            raise

        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(
                rate=SAMPLE_RATE,
                channels=CHANNELS,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=CHUNK,
            )
        except (OSError, IOError) as e:
            pa.terminate()
            raise  # bubble up to recovery loop
        except Exception as e:
            log.error(f"[VoiceInterruption] Could not open mic stream: {e}")
            pa.terminate()
            return

        log.info("[VoiceInterruption] Microphone stream open. Listening for interruptions...")

        try:
            while self._running:
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                except (OSError, IOError):
                    # Mic was grabbed by another process mid-stream — raise for recovery
                    raise
                except Exception:
                    time.sleep(0.05)
                    continue

                if not self._enabled:
                    time.sleep(0.05)
                    continue

                # VAD trigger
                if _rms(data) > ENERGY_THRESH:
                    phrase_data = self._capture_phrase(stream, data)
                    if phrase_data:
                        text = self._transcribe(phrase_data)
                        if text:
                            self._handle(text)

        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            log.info("[VoiceInterruption] Microphone stream closed.")

    def _capture_phrase(self, stream, initial_data: bytes) -> Optional[bytes]:
        """
        Continue capturing until silence.
        Returns the full phrase audio bytes.
        """
        try:
            import pyaudio
            frames       = [initial_data]
            silence_ms   = 0
            max_frames   = int(SAMPLE_RATE / CHUNK * MAX_PHRASE_S)
            silence_limit= int(VAD_HOLD_MS / (CHUNK / SAMPLE_RATE * 1000))

            for _ in range(max_frames):
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                except Exception:
                    break
                frames.append(data)
                if _rms(data) < ENERGY_THRESH * 0.6:
                    silence_ms += 1
                    if silence_ms >= silence_limit:
                        break
                else:
                    silence_ms = 0

            return b"".join(frames)
        except Exception as e:
            log.warning(f"[VoiceInterruption] Capture error: {e}")
            return None

    def _transcribe(self, audio_data: bytes) -> Optional[str]:
        """
        Transcribe captured audio using Vosk (offline, fast).
        Returns the transcript text or None.
        """
        if not self._vosk_ok or not self._vosk_model:
            # No Vosk — just return a generic interrupt signal
            return "jarvis"

        try:
            from vosk import KaldiRecognizer  # type: ignore[import]
            rec = KaldiRecognizer(self._vosk_model, SAMPLE_RATE)
            rec.AcceptWaveform(audio_data)
            result = json.loads(rec.FinalResult())
            text   = result.get("text", "").strip().lower()
            return text if text else None
        except Exception as e:
            log.warning(f"[VoiceInterruption] Transcribe error: {e}")
            return None

    def _handle(self, text: str):
        """
        Handle a detected interruption.
        Always stops TTS. Optionally routes the command to the brain.
        """
        now = time.time()
        if now - self._last_interrupt < COOLDOWN_S:
            return   # Still in cooldown — ignore
        self._last_interrupt = now

        is_interrupt = self._is_interrupt_phrase(text)

        # In wake_word mode, only act on interrupt words
        if self._mode == "wake_word" and not is_interrupt:
            return

        # In hybrid mode, only act if interrupt word OR meaningful phrase
        if self._mode == "hybrid":
            if not is_interrupt and len(text.split()) < 2:
                return

        log.info(f"[VoiceInterruption] Interrupt detected: '{text}'")

        # 1. Kill TTS immediately
        self._stop_tts()

        # 2. Skip pure "stop/wait/quiet" — don't send to brain
        stop_only = {"stop", "wait", "quiet", "silence", "shut up",
                     "pause", "enough", "hold on", "cancel"}
        if text.strip().lower() in stop_only:
            if self._speak_cb:
                self._speak_cb("Understood, sir.")
            return

        # 3. Route the full phrase to the brain
        if self._cmd_cb and text:
            # Strip leading "jarvis" so "jarvis skip to the code" → "skip to the code"
            clean = text.strip()
            for prefix in ("jarvis ", "hey jarvis "):
                if clean.startswith(prefix):
                    clean = clean[len(prefix):]
                    break

            if clean and len(clean) > 1:
                log.info(f"[VoiceInterruption] Routing to brain: '{clean}'")
                # Run in thread so we don't block the VAD loop
                threading.Thread(
                    target=self._route_command,
                    args=(clean,),
                    daemon=True,
                    name="VoiceInterruption-Route"
                ).start()

    def _route_command(self, text: str):
        """Route command to brain — non-blocking, fire-and-forget.
        Schedules process_async on the main qasync loop and speaks reply
        via a future done-callback. Never blocks this thread."""
        self.disable()   # prevent re-triggering while processing

        # If a process_async coroutine is directly available, use it
        # to avoid the deadlock from future.result() blocking in a thread
        # that the qasync loop depends on.
        if hasattr(self._cmd_cb, '__self__') and hasattr(self._cmd_cb.__self__, '_get_main_loop'):
            brain = self._cmd_cb.__self__
            main_loop = brain._get_main_loop()
            if main_loop and main_loop.is_running():
                async def _async_process():
                    try:
                        reply = await brain.process_async(text)
                        if reply and self._speak_cb:
                            self._speak_cb(reply)
                    except Exception as e:
                        log.error(f"[VoiceInterruption] Async route error: {e}")
                    finally:
                        import asyncio as _aio
                        await _aio.sleep(0.5)
                        self.enable()
                asyncio.run_coroutine_threadsafe(_async_process(), main_loop)
                return  # Non-blocking exit

        # Fallback: synchronous path (may block, but won't deadlock on qasync loop)
        _re_enable_evt = threading.Event()
        try:
            if self._cmd_cb:
                reply = self._cmd_cb(text)
                if reply and self._speak_cb:
                    self._speak_cb(reply)
        except Exception as e:
            log.error(f"[VoiceInterruption] Route error: {e}")
        finally:
            _re_enable_evt.wait(timeout=0.5)  # interruptible 500ms cooldown
            self.enable()


    def _stop_tts(self):
        """Stop the speech engine immediately."""
        # Stop pygame mixer (Kokoro / F5-TTS / edge-tts all use it)
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

        # Stop via SpeechEngine API
        if self._speech_eng:
            try:
                self._speech_eng.stop_speaking()
            except Exception:
                pass

        log.info("[VoiceInterruption] TTS stopped.")

    def _is_interrupt_phrase(self, text: str) -> bool:
        """Check if the text contains a known interrupt word."""
        text_lower = text.lower()
        return any(w in text_lower for w in INTERRUPT_WORDS)

    def status(self) -> str:
        """Return a human-readable status."""
        model_status = "Vosk OK" if self._vosk_ok else "Vosk unavailable"
        mic_status   = "MIC LOCKED (recovery pending)" if self._mic_dead else "mic OK"
        return (
            f"Voice Interruption: {'ACTIVE' if self._running else 'stopped'} | "
            f"Mode: {self._mode} | {model_status} | {mic_status} | "
            f"Enabled: {self._enabled}"
        )


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[VoiceInterruption] = None
_instance_lock = threading.Lock()


def get_voice_interruption(mode: str = "hybrid") -> VoiceInterruption:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = VoiceInterruption(mode=mode)
    return _instance
