# workers/vision_worker.py — JARVIS VISION WORKER
# ──────────────────────────────────────────────────────────────────────────────
# Subscribes to frame capture requests and publishes structured vision metadata
# to the input.vision topic on the JARVIS internal PubSub bus.
#
# Dual-source analysis:
#   "screen"  → User Focus  : what is on-screen (IDE, browser, terminal)
#   "camera"  → Environment : what is in the physical room (people, objects)
#
# Backend selection (VRAM-aware, RTX 4050 6 GB):
#   1. Gemini Vision API (cloud, high quality)   — set GEMINI_API_KEY env var
#   2. Ollama Moondream2 (1.5 GB, offline)       — ollama pull moondream
#   3. Caption-only fallback (PIL + pytesseract) — zero VRAM, text-only
#
# Output: VisionMetadata JSON published to input.vision every POLL_INTERVAL_S.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import time
from typing import Any, Optional

import requests
from pydantic import BaseModel, Field

log = logging.getLogger("VisionWorker")

# ── Configuration ─────────────────────────────────────────────────────────────
OLLAMA_URL       = "http://localhost:11434"
GENERATE_URL     = f"{OLLAMA_URL}/api/generate"
TAGS_URL         = f"{OLLAMA_URL}/api/tags"
VRAM_SAFE_PCT    = 78.0        # % — skip VLM above this threshold
POLL_INTERVAL_S  = 3.0         # seconds between passive screen scans
FRAME_PATH       = os.path.join("memory", "vlm_frame.jpg")
FRAME_MAX_W      = 1280        # downscale wide captures for speed
GEMINI_MODEL     = "gemini-2.0-flash"
OLLAMA_VLM_PREF  = ["moondream", "llava:7b", "llava", "llava-phi3"]

# ── VLM options: all layers to CUDA, quantized inference ──────────────────────
VLM_OPTIONS = {
    "num_gpu":     99,          # all layers to RTX 4050 CUDA
    "temperature": 0.1,
    "num_predict": 350,
    "num_ctx":     2048,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class ActiveApplication(BaseModel):
    """Information about the foreground window when source=screen."""
    window_title: Optional[str] = None
    app_name:     Optional[str] = None
    file_path:    Optional[str] = None   # e.g. open file in IDE


class EnvironmentContext(BaseModel):
    """Physical environment metadata when source=camera."""
    people_count:   int = 0
    ambient_notes:  str = ""


class VisionMetadata(BaseModel):
    """
    Structured vision output published to input.vision on the event bus.
    Consumed by AutonomousBrain._stage_perceive() for multi-modal fusion.
    """
    source:       str              # "screen" | "camera"
    description:  str              # natural-language scene description
    text_content: str = ""         # OCR / visible text (screen only)
    ui_anomalies: list[str] = Field(default_factory=list)  # layout issues
    active_app:   Optional[ActiveApplication] = None       # screen only
    environment:  Optional[EnvironmentContext] = None      # camera only
    backend_used: str = "unknown"  # "gemini" | "moondream" | "caption"
    confidence:   float = 1.0
    vram_pct:     float = 0.0
    timestamp:    float = Field(default_factory=time.time)
    frame_path:   Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _vram_pct() -> float:
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        m = pynvml.nvmlDeviceGetMemoryInfo(h)
        return round(100.0 * m.used / m.total, 1)
    except Exception:
        return 0.0


def _encode_image(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        log.warning(f"[Vision] Encode error: {e}")
        return None


def _grab_screen(out_path: str = FRAME_PATH) -> Optional[str]:
    """Capture primary monitor. Returns path on success, None on failure."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    try:
        import mss, cv2, numpy as np
        with mss.mss() as sct:
            mon   = sct.monitors[1]
            img   = sct.grab(mon)
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_BGRA2BGR)
        h, w = frame.shape[:2]
        if w > FRAME_MAX_W:
            frame = cv2.resize(frame, (FRAME_MAX_W, int(h * FRAME_MAX_W / w)))
        cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return out_path
    except ImportError:
        pass
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        img.save(out_path, "JPEG", quality=85)
        return out_path
    except Exception as e:
        log.error(f"[Vision] Screenshot failed: {e}")
        return None


def _grab_camera(out_path: str = FRAME_PATH) -> Optional[str]:
    """Grab one webcam frame. Returns path on success, None on failure."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    try:
        from core.api.camera_manager import CameraManager
        import cv2
        frame = CameraManager.get_instance().get_frame()
        if frame is None:
            return None
        cv2.imwrite(out_path, frame)
        return out_path
    except Exception:
        pass
    # OpenCV direct fallback
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        ret, frame = cap.read()
        cap.release()
        if ret:
            cv2.imwrite(out_path, frame)
            return out_path
    except Exception as e:
        log.error(f"[Vision] Camera grab failed: {e}")
    return None


def _active_window_info() -> Optional[ActiveApplication]:
    """Return foreground window title (Windows only, graceful fallback)."""
    try:
        import ctypes
        hwnd  = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf   = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        return ActiveApplication(window_title=title or None)
    except Exception:
        return None


def _best_ollama_vlm() -> Optional[str]:
    """Return the first available Ollama VLM model name."""
    try:
        r = requests.get(TAGS_URL, timeout=3)
        available = {m["name"] for m in r.json().get("models", [])}
        for candidate in OLLAMA_VLM_PREF:
            for name in available:
                if name.startswith(candidate.split(":")[0]):
                    return name
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _analyse_gemini(image_path: str, prompt: str) -> tuple[str, str]:
    """
    Call Gemini Vision API.
    Returns (description, backend_name).
    Requires GEMINI_API_KEY environment variable.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    import google.generativeai as genai  # type: ignore
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    from PIL import Image
    img     = Image.open(image_path)
    response = model.generate_content([prompt, img])
    return response.text.strip(), "gemini"


def _analyse_ollama(image_path: str, prompt: str,
                    model: Optional[str] = None) -> tuple[str, str]:
    """
    Call Ollama multimodal /api/generate.
    Returns (description, backend_name).
    """
    if model is None:
        model = _best_ollama_vlm()
    if model is None:
        raise RuntimeError("No Ollama VLM model installed")

    encoded = _encode_image(image_path)
    if not encoded:
        raise RuntimeError("Failed to encode image")

    r = requests.post(
        GENERATE_URL,
        json={
            "model":   model,
            "prompt":  prompt,
            "images":  [encoded],
            "stream":  False,
            "options": VLM_OPTIONS,
        },
        timeout=90,
    )
    r.raise_for_status()
    description = r.json().get("response", "").strip()
    return description or "No response from model.", f"ollama/{model}"


def _analyse_caption_fallback(image_path: str, source: str) -> tuple[str, str]:
    """
    Zero-VRAM text extraction fallback using pytesseract OCR.
    """
    try:
        import pytesseract
        from PIL import Image
        img  = Image.open(image_path)
        text = pytesseract.image_to_string(img).strip()
        desc = f"[OCR] Visible text on {source}: {text[:500]}" if text else f"[OCR] No text detected on {source}."
        return desc, "caption"
    except Exception as e:
        log.warning(f"[Vision] Caption fallback failed: {e}")
        return f"Visual capture from {source} — analysis unavailable.", "none"


# ═══════════════════════════════════════════════════════════════════════════════
#  VISION WORKER
# ═══════════════════════════════════════════════════════════════════════════════

class VisionWorker:
    """
    Autonomous vision worker. Operates in one of two modes:
      - passive: polls screen every POLL_INTERVAL_S and publishes to bus
      - reactive: triggered on-demand by calling analyse(source)

    Published payload: VisionMetadata serialised via model_dump().
    """

    TOPIC = "input.vision"

    def __init__(self):
        self._bus          = None
        self._running      = False
        self._ollama_model : Optional[str] = None
        self._loop_task    : Optional[asyncio.Task] = None  # type: ignore

        # Probe Ollama VLM in background
        import threading
        threading.Thread(
            target=self._probe_ollama_vlm,
            daemon=True,
            name="VisionWorker-Probe",
        ).start()

        log.info("[VisionWorker] Initialised.")

    def _get_bus(self):
        if self._bus is None:
            from core.system.event_bus import get_event_bus
            self._bus = get_event_bus()
        return self._bus

    def _probe_ollama_vlm(self):
        # Wait 2s for Ollama to finish booting before querying its model list.
        # Use thread_manager shutdown event so this exits cleanly on app quit.
        try:
            from core.system.thread_manager import wait_for_shutdown
            wait_for_shutdown(timeout=2.0)   # returns early if shutdown fires
        except Exception:
            import time as _t; _t.sleep(2)
        self._ollama_model = _best_ollama_vlm()
        if self._ollama_model:
            log.info(f"[VisionWorker] Ollama VLM ready: {self._ollama_model}")
        else:
            log.warning("[VisionWorker] No Ollama VLM — using caption fallback.")

    # ── Public API ─────────────────────────────────────────────────────────────

    def start_passive_scan(self, interval: float = POLL_INTERVAL_S):
        """Start background polling loop (screen scan only)."""
        self._running = True
        asyncio.get_event_loop().create_task(
            self._passive_loop(interval), name="VisionWorker-Passive"
        )
        log.info(f"[VisionWorker] Passive scan started (interval={interval}s)")

    def stop(self):
        """Stop passive scanning."""
        self._running = False
        log.info("[VisionWorker] Stopped.")

    def analyse(self, source: str = "screen") -> VisionMetadata:
        """
        Synchronous single-shot analysis.
        source: "screen" | "camera"
        """
        return self._analyse_frame(source)

    async def analyse_async(self, source: str = "screen") -> VisionMetadata:
        """Async wrapper — runs blocking analysis in a thread."""
        return await asyncio.to_thread(self._analyse_frame, source)

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _passive_loop(self, interval: float):
        """Background coroutine: scan screen, publish metadata."""
        while self._running:
            try:
                meta = await self.analyse_async(source="screen")
                self._publish(meta)
            except Exception as e:
                log.error(f"[VisionWorker] Passive scan error: {e}")
            await asyncio.sleep(interval)

    def _publish(self, meta: VisionMetadata):
        """Publish VisionMetadata to the internal bus."""
        try:
            payload = meta.model_dump()
            self._get_bus().publish(self.TOPIC, payload)
            log.debug(f"[VisionWorker] Published ({meta.source}, "
                      f"backend={meta.backend_used}, "
                      f"vram={meta.vram_pct}%)")
        except Exception as e:
            log.error(f"[VisionWorker] Publish error: {e}")

    def _analyse_frame(self, source: str) -> VisionMetadata:
        """
        Capture a frame and run VLM analysis.
        Differentiates User Focus (screen) vs. Environment (camera).
        Selects backend in priority order: Gemini → Ollama → Caption.
        """
        vram = _vram_pct()

        # Capture frame
        if source == "camera":
            frame_path = _grab_camera()
        else:
            frame_path = _grab_screen()
            source = "screen"

        if not frame_path:
            return VisionMetadata(
                source=source,
                description=f"Frame capture failed for {source}.",
                backend_used="none",
                vram_pct=vram,
            )

        # Build source-appropriate prompt
        if source == "screen":
            prompt = (
                "You are JARVIS, analysing a developer's screen. "
                "Describe: (1) the active application, (2) what the user is working on, "
                "(3) any visible code, errors, or UI issues. "
                "Be concise and technical. Max 4 sentences."
            )
        else:
            prompt = (
                "You are JARVIS, analysing a webcam feed of the user's environment. "
                "Describe: (1) how many people are visible, (2) the general environment, "
                "(3) anything noteworthy or unusual. Max 3 sentences."
            )

        # Backend selection
        description  = ""
        backend_used = "none"

        # Priority 1: Gemini (cloud)
        if os.environ.get("GEMINI_API_KEY") and vram < VRAM_SAFE_PCT:
            try:
                description, backend_used = _analyse_gemini(frame_path, prompt)
            except Exception as e:
                log.warning(f"[VisionWorker] Gemini failed: {e}")

        # Priority 2: Ollama VLM (local, VRAM-gated)
        if not description and vram < VRAM_SAFE_PCT and self._ollama_model:
            try:
                description, backend_used = _analyse_ollama(
                    frame_path, prompt, self._ollama_model
                )
            except Exception as e:
                log.warning(f"[VisionWorker] Ollama VLM failed: {e}")

        # Priority 3: Caption / OCR fallback (zero VRAM)
        if not description:
            description, backend_used = _analyse_caption_fallback(frame_path, source)

        # Build structured metadata
        meta = VisionMetadata(
            source=source,
            description=description,
            backend_used=backend_used,
            vram_pct=vram,
            frame_path=frame_path,
        )

        # Screen-specific enrichment
        if source == "screen":
            meta.active_app = _active_window_info()
            # Extract visible text if Ollama gave a rich response
            if "error" in description.lower() or "exception" in description.lower():
                meta.ui_anomalies.append("Possible error/exception detected on screen.")

        # Camera-specific enrichment
        elif source == "camera":
            # Attempt to count people from description
            import re
            match = re.search(r"(\d+)\s+(?:person|people|individual)", description, re.I)
            count = int(match.group(1)) if match else (1 if "person" in description.lower() else 0)
            meta.environment = EnvironmentContext(
                people_count=count,
                ambient_notes=description[:200],
            )

        return meta


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[VisionWorker] = None


def get_vision_worker() -> VisionWorker:
    global _instance
    if _instance is None:
        _instance = VisionWorker()
    return _instance
