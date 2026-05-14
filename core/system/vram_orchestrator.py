"""
core/system/vram_orchestrator.py — VRAM Orchestrator (v2)
=========================================================
Ghost B fix: adds a hardware-aware inference lock.

PROBLEM:
  Prefetching a new model while another model is actively doing inference can
  race the GPU driver on 6-8 GB cards — causing OOM, driver resets, or freezes.

SOLUTION:
  A `_inference_lock` context manager that callers acquire for the duration of
  any Ollama inference call. `prefetch_model()` checks this lock before
  scheduling work:
    - If inference is active → prefetch is DEFERRED until the lock is released.
    - If inference is idle   → prefetch fires immediately in the background.

USAGE (in any engine that calls Ollama directly):

    from core.system.vram_orchestrator import get_vram_orchestrator
    with get_vram_orchestrator().inference_context():
        response = ollama.generate(...)   # GPU is exclusively ours

NOTE: This is a cooperative lock — it only works if all inference paths
honour it. stream_chat and llm_fallback are the two primary paths.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Optional

import requests
from core.system.thread_manager import get_thread_manager

log = logging.getLogger("VRAMOrchestrator")

# How long (seconds) to wait before retrying a deferred prefetch after
# inference finishes. Short enough to be responsive, long enough to
# avoid hammering the GPU right as it finishes work.
_PREFETCH_RETRY_DELAY_S: float = 1.5


class VRAMOrchestrator:
    """
    Manages proactive model loading in Ollama with a hardware-aware inference lock.
    """
    _instance: Optional["VRAMOrchestrator"] = None
    _class_lock = threading.Lock()

    def __new__(cls):
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._current_model: Optional[str] = None
                cls._instance._pinned_model: Optional[str] = None
                cls._instance._threads = get_thread_manager()
                # ── Inference lock (Ghost B) ──────────────────────────────────
                # Use an RLock so the same thread can acquire it re-entrantly
                cls._instance._inference_lock = threading.RLock()
                cls._instance._inference_active = False
                cls._instance._pending_prefetch: Optional[str] = None
                cls._instance._priority_queue: list[str] = []
        return cls._instance

    # ── Model Pinning ────────────────────────────────────────────────────────

    def pin_model(self, model_name: str):
        """
        Keep a specific model in VRAM persistently. 
        It will be protected from automatic eviction.
        """
        log.info(f"[VRAM] Pinning model: {model_name}")
        self._pinned_model = model_name
        self.prefetch_model(model_name)

    def unpin(self):
        """Remove model pinning."""
        log.info(f"[VRAM] Unpinning model: {self._pinned_model}")
        self._pinned_model = None

    # ── Inference context manager (Ghost B) ──────────────────────────────────

    @contextmanager
    def inference_context(self):
        """
        Context manager that callers MUST wrap around any Ollama inference call.

        On entry: acquires the inference lock, blocking any prefetch that tries
                  to start while inference is in progress.
        On exit:  releases the lock, then fires any pending prefetch that was
                  deferred while inference was running.
        """
        with self._inference_lock:
            self._inference_active = True
            try:
                yield
            finally:
                self._inference_active = False
                # Fire any deferred prefetch now that the GPU is free
                pending = self._pending_prefetch
                self._pending_prefetch = None

        if pending:
            log.info(f"[VRAM] Inference finished — firing deferred prefetch for {pending}.")
            self._schedule_prefetch(pending)

    # ── Prefetch ──────────────────────────────────────────────────────────────

    def prefetch_model(self, model_name: str):
        """
        Background load a model into VRAM with safety checks.

        If inference is currently active, the prefetch is DEFERRED until
        the inference_context() exits. Only one deferred prefetch is kept
        at a time (the most recent one wins).
        """
        if model_name == self._current_model:
            log.debug(f"[VRAM] {model_name} already loaded — skipping prefetch.")
            return

        if self._inference_active:
            log.info(f"[VRAM] Inference active — deferring prefetch of {model_name}.")
            self._pending_prefetch = model_name
            return

        self._schedule_prefetch(model_name)

    def _schedule_prefetch(self, model_name: str):
        """Internal: submit the actual prefetch job to the thread pool."""
        def _load():
            # Acquire the inference lock in the background thread
            with self._inference_lock:
                try:
                    from core.providers.ollama_manager import get_ollama_manager
                    om = get_ollama_manager()

                    # Safety Check: If VRAM > threshold, evict other models first
                    usage = om.get_vram_usage_pct()
                    from core.system.vram_config import get_vram_config
                    threshold = get_vram_config().eviction_threshold_pct
                    if usage and usage > threshold:
                        log.warning(
                            f"[VRAM] High usage ({usage:.1f}%). "
                            f"Evicting non-pinned models before prefetching {model_name}."
                        )
                        # Keep pinned model if it's not the one we are loading
                        keep = [self._pinned_model] if self._pinned_model else None
                        om.evict_models(keep=keep)

                    log.info(f"[VRAM] Proactively loading {model_name}...")
                    payload = {
                        "model":      model_name,
                        "prompt":     "",
                        "stream":     False,
                        "keep_alive": "15m" if model_name == self._pinned_model else "10m",
                    }
                    requests.post(
                        "http://localhost:11434/api/generate",
                        json=payload,
                        timeout=60,
                    )
                    self._current_model = model_name
                    log.info(f"[VRAM] {model_name} is now hot and ready.")
                except Exception as exc:
                    log.warning(f"[VRAM] Prefetch failed for {model_name}: {exc}")

        self._threads.run_in_background(_load, name=f"VRAM-Prefetch-{model_name}")

    # ── Eviction ─────────────────────────────────────────────────────────────

    def evict_all(self):
        """Release all models from VRAM (Ollama keep_alive=0 convention)."""
        def _evict():
            try:
                from core.providers.ollama_manager import get_ollama_manager
                get_ollama_manager().evict_models()
                self._current_model = None
            except Exception as exc:
                log.warning(f"[VRAM] evict_all failed: {exc}")

        self._threads.run_in_background(_evict, name="VRAM-Evict")

    # ── Status ────────────────────────────────────────────────────────────────

    def get_active_model(self) -> Optional[str]:
        """Return the name of the model currently loaded in VRAM."""
        return self._current_model

    @property
    def is_inference_active(self) -> bool:
        """True when an inference call is currently holding the GPU."""
        return self._inference_active


def get_vram_orchestrator() -> VRAMOrchestrator:
    return VRAMOrchestrator()
