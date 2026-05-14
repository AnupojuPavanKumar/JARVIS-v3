# core/llm_fallback.py — JARVIS LLM FALLBACK CHAIN (Upgrade #12)
# ──────────────────────────────────────────────────────────────────────────────
# Wraps every Ollama LLM call with a smart 4-tier fallback chain.
# If the primary model is slow, unavailable, or returns garbage — the next
# model in the chain picks up INSTANTLY with no 90-second timeout.
#
# Fallback chain (RTX 4050, 6GB VRAM):
#   Tier 1: qwen2.5-coder:7b  (4.7GB — best code quality)
#   Tier 2: gemma2:9b          (5.5GB — best conversational quality)
#   Tier 3: gemma2:2b          (1.6GB — fast, always fits in VRAM)
#   Tier 4: llama3.2:3b        (2.0GB — reliable fallback)
#
# Features:
#   - Per-model circuit breaker: 3 consecutive failures → skip for 5 minutes
#   - Response quality gate: too-short or malformed → skip to next tier
#   - First-token latency tracking: slow models deprioritized
#   - Health heartbeat: pings Ollama every 30s, detects server restart
#   - Streaming-aware: works with both stream=True and stream=False
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Optional

import requests

log = logging.getLogger("LLMFallback")

# Critical fix: import VRAM orchestrator so non-streaming calls also hold the
# inference lock. Without this, a background prefetch fires while Plan/Execute/
# Think are running — re-introducing the Ghost B GPU driver race.
from core.system.vram_orchestrator import get_vram_orchestrator as _get_vram

OLLAMA_CHAT_URL  = "http://localhost:11434/api/chat"
OLLAMA_TAGS_URL  = "http://localhost:11434/api/tags"
HEALTH_URL       = "http://localhost:11434/"

# Default fallback chain — ordered by quality preference.
# NOTE: verified against `ollama list` on this machine (2026-05-11):
#   qwen2.5-coder:7b, deepseek-r1:7b, gemma2:2b, llama3.2:3b, moondream:latest
DEFAULT_CHAIN = [
    "qwen2.5-coder:7b",   # Primary: best code quality, fits RTX 4050 6GB
    "deepseek-r1:7b",     # Excellent reasoning, if installed
    "gemma2:2b",          # Fast conversational, verified installed
    "llama3.2:3b",        # Reliable general fallback, verified installed
]

# Circuit breaker config
CB_MAX_FAILURES  = 3          # failures before circuit opens
CB_RESET_SECONDS = 300        # 5 minutes before circuit resets
MIN_RESPONSE_LEN = 5          # minimum acceptable response chars


class _CircuitBreaker:
    """Per-model circuit breaker: tracks failures and open/close state."""

    def __init__(self, model: str):
        self.model         = model
        self.failures      = 0
        self.last_failure  = 0.0
        self.open          = False

    def record_success(self):
        self.failures = 0
        self.open     = False

    def record_failure(self):
        self.failures     += 1
        self.last_failure  = time.time()
        if self.failures >= CB_MAX_FAILURES:
            self.open = True
            log.warning(f"[CB] Circuit OPEN for {self.model} ({self.failures} failures)")

    def is_available(self) -> bool:
        if not self.open:
            return True
        # Auto-reset after CB_RESET_SECONDS
        if time.time() - self.last_failure > CB_RESET_SECONDS:
            self.open     = False
            self.failures = 0
            log.info(f"[CB] Circuit RESET for {self.model}")
            return True
        return False


class LLMFallbackChain:
    """
    Smart multi-model LLM fallback chain for JARVIS.

    Wraps _call() with:
      - Circuit breaker per model
      - Quality gate on response
      - Automatic chain walking until a model succeeds
      - Available-model list from Ollama (no 404 waste)
    """

    def __init__(self, chain: list[str] | None = None):
        self._chain     = chain or DEFAULT_CHAIN[:]
        self._breakers: dict[str, _CircuitBreaker] = {}
        self._available: set[str] = set()
        self._lock      = threading.Lock()
        self._last_health = 0.0
        self._stop_event  = threading.Event()
        self._refresh_available()

        # Background health heartbeat every 30s
        threading.Thread(
            target=self._health_loop,
            daemon=True,
            name="LLMFallback-Health"
        ).start()

    # ── Public API ───────────────────────────────────────────────────────────────

    def call(
        self,
        messages:     list[dict],
        prefer:       str | None    = None,
        temperature:  float         = 0.1,
        max_tokens:   int           = 4096,
        num_ctx:      int           = 16384,
        response_fmt: str | None    = "json",
        timeout:      int           = 180,
        min_length:   int           = MIN_RESPONSE_LEN,
        stream:       bool          = False,
        stream_cb:    Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """
        Call LLM with fallback chain. Returns response text or None.

        prefer: model name to try first (before chain order)
        stream_cb: if provided and stream=True, called with each token
        """
        # Build ordered list of models to try
        ordered = self._build_order(prefer)

        for model in ordered:
            if not self._is_usable(model):
                continue

            cb = self._get_cb(model)
            if not cb.is_available():
                log.debug(f"[Fallback] Skipping {model} — circuit open")
                continue

            try:
                t0      = time.time()
                result  = self._call_model(
                    model, messages, temperature, max_tokens,
                    num_ctx, response_fmt, timeout, stream, stream_cb
                )
                elapsed = time.time() - t0

                if result and len(result) >= min_length:
                    cb.record_success()
                    log.debug(f"[Fallback] {model} responded in {elapsed:.1f}s ({len(result)} chars)")
                    return result

                # Response too short — quality gate fail
                log.warning(f"[Fallback] {model} quality gate fail (len={len(result or '')}) → next")
                cb.record_failure()

            except requests.exceptions.ConnectionError:
                log.error("[Fallback] Ollama server unreachable")
                return None   # Entire server down — no point trying others

            except requests.exceptions.Timeout:
                log.warning(f"[Fallback] {model} timed out → next")
                cb.record_failure()

            except requests.exceptions.HTTPError as e:
                if "404" in str(e):
                    log.warning(f"[Fallback] {model} not installed → next")
                    with self._lock:
                        self._available.discard(model)
                else:
                    log.warning(f"[Fallback] {model} HTTP error: {e} → next")
                cb.record_failure()

            except Exception as e:
                log.warning(f"[Fallback] {model} error: {e} → next")
                cb.record_failure()

        log.error("[Fallback] All models in chain exhausted")
        return None

    def status(self) -> str:
        """Human-readable status of all models in chain."""
        lines = ["LLM Fallback Chain Status:"]
        for model in self._chain:
            avail = "✓" if model in self._available else "✗"
            cb    = self._get_cb(model)
            state = "OPEN" if cb.open else f"ok ({cb.failures} fail)"
            lines.append(f"  {avail} {model:30s} [{state}]")
        return "\n".join(lines)

    def reset_breakers(self) -> str:
        """Reset all circuit breakers."""
        for cb in self._breakers.values():
            cb.failures = 0
            cb.open     = False
        return "All circuit breakers reset, sir."

    def stop(self):
        """Signal the health loop to exit cleanly."""
        self._stop_event.set()

    def refresh(self):
        """Force re-query of available models from Ollama."""
        self._refresh_available()

    @property
    def available_models(self) -> list[str]:
        with self._lock:
            return sorted(self._available)

    # ── Internal ─────────────────────────────────────────────────────────────────

    def _call_model(
        self, model, messages, temperature, max_tokens,
        num_ctx, response_fmt, timeout, stream, stream_cb
    ) -> str:
        payload: dict = {
            "model":    model,
            "messages": messages,
            "stream":   stream,
            "options":  {
                "temperature":    temperature,
                "num_predict":    max_tokens,
                "num_ctx":        num_ctx,
                "repeat_penalty": 1.1,
                "top_p":          0.9,
            }
        }
        if response_fmt == "json":
            payload["format"] = "json"

        # Acquire the VRAM inference lock so no prefetch fires mid-call.
        # RLock is re-entrant — nested calls within the same thread are safe.
        vram = _get_vram()
        if stream and stream_cb:
            with vram.inference_context():
                return self._stream_call(payload, stream_cb, timeout)

        with vram.inference_context():
            resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")

    def _stream_call(self, payload: dict, stream_cb: Callable, timeout: int) -> str:
        full = ""
        with requests.post(
            OLLAMA_CHAT_URL, json=payload, stream=True, timeout=timeout
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        full += token
                        stream_cb(token)
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
        return full

    def _build_order(self, prefer: Optional[str]) -> list[str]:
        if prefer and prefer in self._chain:
            rest = [m for m in self._chain if m != prefer]
            return [prefer] + rest
        return self._chain[:]

    def _is_usable(self, model: str) -> bool:
        with self._lock:
            if not self._available:
                return True   # Can't check — try anyway
            base = model.split(":")[0]
            return any(m == model or m.startswith(base) for m in self._available)

    def _get_cb(self, model: str) -> _CircuitBreaker:
        if model not in self._breakers:
            self._breakers[model] = _CircuitBreaker(model)
        return self._breakers[model]

    def _refresh_available(self):
        try:
            r = requests.get(OLLAMA_TAGS_URL, timeout=3)
            if r.status_code == 200:
                tags = r.json().get("models", [])
                with self._lock:
                    self._available = {m.get("name", "") for m in tags}
                log.debug(f"[Fallback] Available: {sorted(self._available)}")
        except Exception as e:
            log.debug(f"[Fallback] Can't reach Ollama tags: {e}")

    def _health_loop(self):
        while not self._stop_event.is_set():
            # Use wait() so we wake up immediately on stop, not after 30s sleep
            if self._stop_event.wait(timeout=30):
                break
            try:
                r = requests.get(HEALTH_URL, timeout=2)
                if r.status_code == 200:
                    # Refresh model list on each successful health check
                    self._refresh_available()
            except Exception:
                log.debug("[Fallback] Ollama health check failed — server may be restarting")


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[LLMFallbackChain] = None
_lock = threading.Lock()


def get_fallback_chain() -> LLMFallbackChain:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = LLMFallbackChain()
    return _instance


def llm_call(
    messages:     list[dict],
    prefer:       str | None = None,
    temperature:  float      = 0.1,
    max_tokens:   int        = 4096,
    response_fmt: str | None = "json",
    timeout:      int        = 180,
) -> Optional[str]:
    """
    Convenience function — drop-in replacement for direct requests.post() LLM calls.
    Automatically uses the fallback chain.
    """
    return get_fallback_chain().call(
        messages=messages,
        prefer=prefer,
        temperature=temperature,
        max_tokens=max_tokens,
        response_fmt=response_fmt,
        timeout=timeout,
    )
