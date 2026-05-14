# workers/voice_output_worker.py — JARVIS VOICE OUTPUT WORKER (Stream-to-Audio)
# ──────────────────────────────────────────────────────────────────────────────
# Subscribes to the response.text topic on the JARVIS internal PubSub bus.
# Implements "Stream-to-Audio": begins speaking as soon as the first complete
# phrase is available — no waiting for the full response.
#
# Stream-to-Audio Pipeline:
#   1. Token accumulator: collects incoming tokens into a rolling buffer.
#   2. Phrase detector: fires as soon as a speakable phrase boundary is found
#      (sentence-end punctuation, or MIN_CHARS threshold on long fragments).
#   3. TTS dispatcher: routes the phrase to the best available TTS engine:
#        Engine 0: Kokoro-ONNX  (82M, British male, 100% offline, ~100ms)
#        Engine 1: pyttsx3/SAPI5 (instant, offline fallback)
#        Engine 2: edge-tts      (Azure Neural, online-only fallback)
#   4. Audio playback: pygame mixer plays audio from an in-memory buffer.
#      Sentences are queued so playback starts while the next is synthesising.
#
# Interruption:
#   Receiving a new input.voice event while speaking will call stop_speaking()
#   and discard queued phrases, maintaining JARVIS's conversational feel.
#
# RTX 4050 Note:
#   Kokoro-ONNX runs on CPU (ONNX Runtime). Zero VRAM used for TTS.
#   This allows the GPU to stay fully dedicated to the LLM during speech.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import io
import logging
import os
import queue
import re
import threading
import time
from typing import Callable, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("VoiceOutputWorker")

# ── Phrase detection config ────────────────────────────────────────────────────
# Sentence boundaries: fire speech after . ! ? (followed by space or end)
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')

# Minimum accumulated characters before firing a non-sentence chunk
# (handles responses that never use terminal punctuation)
MIN_PHRASE_CHARS = 45

# Maximum characters before we force-flush even without punctuation
MAX_PHRASE_CHARS = 180

# Engine constants
_KOKORO_DIR    = os.path.join("memory", "kokoro")
_KOKORO_MODEL  = os.path.join(_KOKORO_DIR, "kokoro-v1.0.onnx")
_KOKORO_VOICES = os.path.join(_KOKORO_DIR, "voices-v1.0.bin")
_KOKORO_VOICE  = "bm_george"   # British male
_KOKORO_LANG   = "en-gb"

_FORCE_OFFLINE = os.environ.get("JARVIS_OFFLINE_TTS", "0") == "1"


# ═══════════════════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class ResponseTextEvent(BaseModel):
    """Payload received from the response.text bus topic."""
    topic:     str   = "response.text"
    text:      str
    stream:    bool  = True    # if True, treat text as a streaming chunk
    identity:  str   = "owner"
    timestamp: float = Field(default_factory=time.time)


class PhraseJob(BaseModel):
    """A single phrase queued for TTS synthesis and playback."""
    text:       str
    sequence:   int   = 0    # ordering within a response
    timestamp:  float = Field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════════════════════════
#  TTS ENGINE ADAPTERS
# ═══════════════════════════════════════════════════════════════════════════════

class _KokoroEngine:
    """Kokoro-ONNX neural TTS (offline, British male, ~100ms latency)."""

    def __init__(self):
        self._kokoro    : Optional[object] = None
        self._ready     : Optional[bool]   = None  # None=loading, True=ok, False=failed
        self._load_lock = threading.Lock()
        # Load in background so __init__ returns immediately
        threading.Thread(target=self._load, daemon=True, name="KokoroLoad").start()

    def _load(self):
        with self._load_lock:
            if not (os.path.exists(_KOKORO_MODEL) and os.path.exists(_KOKORO_VOICES)):
                log.info("[Kokoro] Model files not found — engine disabled.")
                self._ready = False
                return
            try:
                from kokoro_onnx import Kokoro  # type: ignore
                self._kokoro = Kokoro(_KOKORO_MODEL, _KOKORO_VOICES)
                self._ready  = True
                log.info("[Kokoro] Neural engine ready (bm_george).")
            except Exception as e:
                log.warning(f"[Kokoro] Load failed: {e}")
                self._ready = False

    def wait_ready(self, timeout: float = 8.0) -> bool:
        """Block until loading finishes or timeout."""
        deadline = time.time() + timeout
        while self._ready is None and time.time() < deadline:
            time.sleep(0.1)
        return bool(self._ready)

    def synthesise(self, text: str, speed: float = 1.05) -> Optional[bytes]:
        """
        Synthesise text to WAV bytes in memory.
        Returns None on failure so the caller can fall back.
        """
        if not self.wait_ready(timeout=0.5):
            return None
        if not self._kokoro:
            return None
        try:
            import soundfile as sf
            import numpy as np

            samples, sr = self._kokoro.create(
                text, voice=_KOKORO_VOICE, speed=speed, lang=_KOKORO_LANG
            )
            # Apply JARVIS voice DSP if available
            try:
                from core.ui.voice_fx import apply_jarvis_fx
                samples = apply_jarvis_fx(samples, sr)
            except Exception:
                pass

            buf = io.BytesIO()
            sf.write(buf, samples, sr, format="WAV")
            buf.seek(0)
            return buf.read()
        except Exception as e:
            log.warning(f"[Kokoro] Synthesis failed: {e}")
            return None


class _Pyttsx3Engine:
    """pyttsx3 / SAPI5 — instant offline fallback (Windows)."""

    def __init__(self):
        self._engine = None
        self._init_lock = threading.Lock()

    def _get_engine(self):
        with self._init_lock:
            if self._engine is None:
                try:
                    import pyttsx3
                    try:
                        import pythoncom
                        pythoncom.CoInitialize()
                    except Exception:
                        pass
                    eng = pyttsx3.init("sapi5")
                    eng.setProperty("rate",   175)
                    eng.setProperty("volume", 0.95)
                    voices = eng.getProperty("voices")
                    for v in voices:
                        if "david" in v.name.lower() or "mark" in v.name.lower():
                            eng.setProperty("voice", v.id)
                            break
                    self._engine = eng
                except Exception as e:
                    log.warning(f"[pyttsx3] Init failed: {e}")
        return self._engine

    def speak_blocking(self, text: str) -> bool:
        """Synthesise and play synchronously. Returns True on success."""
        eng = self._get_engine()
        if eng is None:
            return False
        try:
            eng.say(text)
            eng.runAndWait()
            return True
        except Exception as e:
            log.warning(f"[pyttsx3] Speak error: {e}")
            return False


class _EdgeTTSEngine:
    """edge-tts Azure Neural TTS — network fallback."""

    def synthesise(self, text: str) -> Optional[bytes]:
        if _FORCE_OFFLINE:
            return None
        try:
            import edge_tts  # type: ignore
            import asyncio
            import tempfile

            async def _gen() -> bytes:
                comm = edge_tts.Communicate(
                    text=text, voice="en-GB-ThomasNeural",
                    rate="+0%", pitch="-2Hz"
                )
                buf = io.BytesIO()
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        buf.write(chunk["data"])
                buf.seek(0)
                return buf.read()

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_gen())
            finally:
                loop.close()
        except Exception as e:
            log.warning(f"[EdgeTTS] Synthesis failed: {e}")
            return None


# ═══════════════════════════════════════════════════════════════════════════════
#  AUDIO PLAYBACK
# ═══════════════════════════════════════════════════════════════════════════════

class _AudioPlayer:
    """pygame-based audio player (shared mixer instance)."""

    _init_lock = threading.Lock()
    _initialised = False

    @classmethod
    def _ensure_init(cls, sample_rate: int = 24000):
        with cls._init_lock:
            if not cls._initialised:
                try:
                    import pygame
                    pygame.mixer.init(frequency=sample_rate, channels=1)
                    cls._initialised = True
                except Exception as e:
                    log.warning(f"[Audio] pygame mixer init failed: {e}")

    def play_wav_bytes(self, wav_bytes: bytes, stop_flag: threading.Event) -> bool:
        """Play WAV bytes via pygame. Returns True when playback finishes."""
        self._ensure_init()
        try:
            import pygame
            if not pygame.mixer.get_init():
                return False
            buf = io.BytesIO(wav_bytes)
            pygame.mixer.music.load(buf)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if stop_flag.is_set():
                    pygame.mixer.music.stop()
                    return False
                pygame.time.wait(10)
            pygame.mixer.music.unload()
            return True
        except Exception as e:
            log.warning(f"[Audio] Playback error: {e}")
            return False

    def stop(self):
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  VOICE OUTPUT WORKER
# ═══════════════════════════════════════════════════════════════════════════════

class VoiceOutputWorker:
    """
    Stream-to-Audio TTS worker.

    Subscribes to response.text on the internal PubSub bus.
    Begins speaking the moment the first phrase boundary is detected —
    without waiting for the full LLM response.

    Thread model:
      - Main thread: receives bus events, accumulates token buffer
      - Synthesis thread: pops PhraseJobs, synthesises to WAV bytes
      - Playback thread: plays WAV bytes sequentially through pygame

    This two-stage pipeline ensures synthesis of phrase N+1 overlaps with
    playback of phrase N, minimising audible gaps between sentences.
    """

    TOPIC_RESPONSE = "response.text"
    TOPIC_VOICE_IN = "input.voice"   # for interruption detection

    def __init__(self):
        self._bus       = None
        self._kokoro    = _KokoroEngine()
        self._pyttsx3   = _Pyttsx3Engine()
        self._edge      = _EdgeTTSEngine()
        self._player    = _AudioPlayer()

        # Token accumulation
        self._buffer    : str             = ""
        self._seq_ctr   : int             = 0
        self._response_active: bool       = False

        # Phrase → synthesis → playback pipeline
        self._phrase_queue : queue.Queue[Optional[PhraseJob]] = queue.Queue(maxsize=32)
        self._audio_queue  : queue.Queue[Optional[bytes]]     = queue.Queue(maxsize=8)

        # Stop flag: set to interrupt all in-flight speech
        self._stop_flag = threading.Event()

        # Synthesis worker thread
        self._synth_thread = threading.Thread(
            target=self._synthesis_worker,
            daemon=True,
            name="VoiceOut-Synth",
        )
        # Playback worker thread
        self._play_thread = threading.Thread(
            target=self._playback_worker,
            daemon=True,
            name="VoiceOut-Play",
        )

        self._synth_thread.start()
        self._play_thread.start()
        log.info("[VoiceOutputWorker] Initialised (Stream-to-Audio pipeline active).")

    # ── PubSub wiring ──────────────────────────────────────────────────────────

    def _get_bus(self):
        if self._bus is None:
            from core.system.event_bus import get_event_bus
            self._bus = get_event_bus()
        return self._bus

    def start(self):
        """Subscribe to bus topics. Call after the asyncio loop is running."""
        bus = self._get_bus()
        bus.subscribe(self.TOPIC_RESPONSE, self._on_response_event)
        bus.subscribe(self.TOPIC_VOICE_IN, self._on_voice_interrupt)
        log.info(f"[VoiceOutputWorker] Subscribed → "
                 f"{self.TOPIC_RESPONSE}, {self.TOPIC_VOICE_IN}")

    # ── Bus event handlers ─────────────────────────────────────────────────────

    def _on_voice_interrupt(self, payload: dict):
        """
        A new voice command arrived → interrupt ongoing speech immediately.
        This is the key UX feature: JARVIS goes silent the instant the user speaks.
        """
        self.stop_speaking()
        log.debug("[VoiceOutputWorker] Speech interrupted by new voice input.")

    def _on_response_event(self, payload: dict):
        """
        Receive a response.text event from the bus.

        Two modes:
          stream=True  → accumulate token(s) and fire phrases as they form
          stream=False → treat entire text as one response; split into phrases
        """
        try:
            event = ResponseTextEvent(**payload)
        except Exception as e:
            log.error(f"[VoiceOutputWorker] Payload validation error: {e}")
            return

        if not event.text.strip():
            return

        if event.stream:
            # Streaming mode: accumulate and fire phrases progressively
            self._buffer += event.text
            self._flush_buffer(force=False)
        else:
            # Non-streaming: split the complete response into phrases and queue all
            self.speak_text(event.text)

    # ── Public API ─────────────────────────────────────────────────────────────

    def speak_text(self, text: str):
        """
        Queue a complete text for speech.
        Splits into phrases and enqueues each as a PhraseJob.
        """
        if not text.strip():
            return
        clean  = self._strip_markdown(text)
        phrases = self._split_phrases(clean)
        for phrase in phrases:
            if phrase.strip():
                self._enqueue_phrase(phrase.strip())

    def stop_speaking(self):
        """
        Interrupt all in-flight and queued speech.
        Safe to call from any thread.
        """
        self._stop_flag.set()
        self._buffer = ""

        # Drain phrase and audio queues
        for q in (self._phrase_queue, self._audio_queue):
            while not q.empty():
                try:
                    q.get_nowait()
                    q.task_done()
                except queue.Empty:
                    break

        self._player.stop()
        self._stop_flag.clear()   # ready for next utterance
        log.debug("[VoiceOutputWorker] Speech stopped and queues cleared.")

    # ── Buffer management (stream-to-audio core logic) ─────────────────────────

    def _flush_buffer(self, force: bool = False):
        """
        Inspect the accumulated token buffer and fire PhraseJobs for any
        complete phrase boundaries found.

        Phrase boundary rules (in priority order):
          1. Sentence-ending punctuation (. ! ?)
          2. Buffer length >= MAX_PHRASE_CHARS (force-flush long sentences)
          3. force=True → flush everything remaining
        """
        while True:
            # Try sentence split
            parts = _SENTENCE_RE.split(self._buffer, maxsplit=1)
            if len(parts) >= 2:
                # parts[0] is the complete sentence; parts[1] is the remainder
                phrase         = parts[0].strip()
                self._buffer   = parts[1]
                if len(phrase) >= MIN_PHRASE_CHARS:
                    self._enqueue_phrase(phrase)
                    continue  # check remainder for more complete sentences
                else:
                    # Too short — prepend back and try next boundary
                    self._buffer = phrase + " " + self._buffer
                    break

            # Force-flush on max length
            if len(self._buffer) >= MAX_PHRASE_CHARS:
                phrase       = self._buffer.strip()
                self._buffer = ""
                if phrase:
                    self._enqueue_phrase(phrase)
                continue

            # Force-flush remaining buffer at end-of-response
            if force and self._buffer.strip():
                phrase       = self._buffer.strip()
                self._buffer = ""
                self._enqueue_phrase(phrase)

            break

    def flush(self):
        """
        Signal end-of-stream: flush any remaining buffer.
        Call this after the LLM has finished generating tokens.
        """
        self._flush_buffer(force=True)
        log.debug("[VoiceOutputWorker] End-of-stream flush complete.")

    # ── Phrase pipeline ────────────────────────────────────────────────────────

    def _enqueue_phrase(self, phrase: str):
        """Put a phrase into the synthesis queue."""
        self._seq_ctr += 1
        job = PhraseJob(text=phrase, sequence=self._seq_ctr)
        try:
            self._phrase_queue.put_nowait(job)
            log.debug(f"[VoiceOutputWorker] Enqueued phrase #{job.sequence}: "
                      f"'{phrase[:60]}...' " if len(phrase) > 60 else
                      f"[VoiceOutputWorker] Enqueued phrase #{job.sequence}: '{phrase}'")
        except queue.Full:
            log.warning("[VoiceOutputWorker] Phrase queue full — dropping phrase.")

    def _synthesis_worker(self):
        """
        Background thread: pops PhraseJobs, synthesises to WAV bytes,
        pushes bytes to the audio queue.

        Runs synthesise-while-playing so the next phrase is ready the moment
        the previous one finishes.
        """
        while True:
            try:
                job = self._phrase_queue.get()
                if job is None:   # sentinel
                    self._audio_queue.put(None)
                    break

                if self._stop_flag.is_set():
                    self._phrase_queue.task_done()
                    continue

                wav_bytes = self._synthesise(job.text)
                self._phrase_queue.task_done()

                if wav_bytes and not self._stop_flag.is_set():
                    try:
                        self._audio_queue.put(wav_bytes, timeout=5)
                    except queue.Full:
                        log.warning("[VoiceOutputWorker] Audio queue full.")
                elif not wav_bytes:
                    log.warning(f"[VoiceOutputWorker] Synthesis produced no audio for: '{job.text[:60]}'")

            except Exception as e:
                log.error(f"[VoiceOutputWorker] Synthesis worker error: {e}")

    def _playback_worker(self):
        """
        Background thread: pops WAV bytes from the audio queue and plays them.
        Sequential playback ensures correct ordering even if synthesis is faster.
        """
        while True:
            try:
                wav_bytes = self._audio_queue.get()
                if wav_bytes is None:   # sentinel
                    break

                if self._stop_flag.is_set():
                    self._audio_queue.task_done()
                    continue

                self._player.play_wav_bytes(wav_bytes, self._stop_flag)
                self._audio_queue.task_done()

            except Exception as e:
                log.error(f"[VoiceOutputWorker] Playback worker error: {e}")

    # ── TTS engine waterfall ───────────────────────────────────────────────────

    def _synthesise(self, text: str) -> Optional[bytes]:
        """
        Try TTS engines in priority order.
        Returns WAV bytes on success, or falls back to pyttsx3 (direct play).
        """
        # Engine 0: Kokoro-ONNX (best quality, zero VRAM)
        wav = self._kokoro.synthesise(text)
        if wav:
            return wav

        # Engine 1: edge-tts (Azure Neural, network)
        if not _FORCE_OFFLINE:
            wav = self._edge.synthesise(text)
            if wav:
                return wav

        # Engine 2: pyttsx3 SAPI5 — speaks directly (no WAV bytes returned)
        # We synthesise to a temp file, read it back as bytes
        wav = self._pyttsx3_to_bytes(text)
        if wav:
            return wav

        # Last resort: pyttsx3 blocking speak (no pipeline overlap)
        self._pyttsx3.speak_blocking(text)
        return None

    def _pyttsx3_to_bytes(self, text: str) -> Optional[bytes]:
        """
        Use pyttsx3 to write a temp WAV file, then read it back as bytes.
        Allows pyttsx3 to participate in the synthesis pipeline.
        """
        import pyttsx3
        import tempfile
        import pythoncom

        com_initialized = False
        tmp = None
        try:
            try:
                pythoncom.CoInitialize()
                com_initialized = True
            except Exception:
                pass
            eng  = pyttsx3.init("sapi5")
            eng.setProperty("rate", 175)
            # FIX: Use NamedTemporaryFile instead of mktemp for security
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp = tmp_file.name
            eng.save_to_file(text, tmp)
            eng.runAndWait()
            if not os.path.exists(tmp):
                return None
            with open(tmp, "rb") as f:
                data = f.read()
            return data if data else None
        except Exception as e:
            log.debug(f"[VoiceOutputWorker] pyttsx3_to_bytes failed: {e}")
            return None
        finally:
            # FIX: Clean up temp file and COM
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            if com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    # ── Markdown stripper ──────────────────────────────────────────────────────

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove markdown formatting that should not be spoken aloud."""
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n+", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _split_phrases(text: str) -> list[str]:
        """Split text into speakable phrases on sentence boundaries."""
        parts = _SENTENCE_RE.split(text)
        return [p.strip() for p in parts if p.strip()]

    # ── Shutdown ───────────────────────────────────────────────────────────────

    def stop(self):
        """Full shutdown — send sentinels to worker threads."""
        self.stop_speaking()
        try:
            self._phrase_queue.put(None)
        except Exception:
            pass
        log.info("[VoiceOutputWorker] Shutdown complete.")


# ── Singleton ──────────────────────────────────────────────────────────────────
_worker_instance: Optional[VoiceOutputWorker] = None


def get_voice_output_worker() -> VoiceOutputWorker:
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = VoiceOutputWorker()
    return _worker_instance
