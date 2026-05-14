# core/agent/model_prewarmer.py — JARVIS MODEL PRE-WARMER
"""
Warms up chat model (gemma2:2b) at startup so the first conversation
response has near-zero latency.

Strategy: issue a minimal no-op generate call that forces Ollama to load
the model weights into memory. The VRAM orchestrator tracks this as
inference context, so no model-switching happens during the warmup.

Runs in a daemon thread after the asyncio event loop is confirmed alive.
"""

from __future__ import annotations

import threading
import logging
import time

log = logging.getLogger("ModelPrewarmer")

_WARM_MODEL   = "gemma2:2b"
_WARM_TIMEOUT = 30   # seconds before giving up on warmup


class ModelPrewarmer:
    """Singleton. Call start() once at startup."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._started = False
        return cls._instance

    def start(self):
        if self._started:
            return
        self._started = True
        t = threading.Thread(target=self._warm, daemon=True, name="ModelPrewarm")
        t.start()
        log.info("[Prewarmer] Warming gemma2:2b in background...")

    def _warm(self):
        t0 = time.time()
        try:
            from core.providers.ollama_manager import get_ollama_manager
            from core.system.vram_orchestrator import get_vram_orchestrator

            vram = get_vram_orchestrator()
            ollama = get_ollama_manager()

            with vram.inference_context():
                resp = ollama.generate(
                    model=_WARM_MODEL,
                    prompt="OK",
                    stream=False,
                    options={"num_predict": 2},
                    timeout=_WARM_TIMEOUT,
                )

            elapsed = time.time() - t0
            if resp:
                log.info(f"[Prewarmer] gemma2:2b ready in {elapsed:.1f}s")
            else:
                log.warning(f"[Prewarmer] Warmup returned empty — model may not be installed")

        except Exception as e:
            log.warning(f"[Prewarmer] Warmup error: {e}")


def get_prewarmer() -> ModelPrewarmer:
    return ModelPrewarmer()