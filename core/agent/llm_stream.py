# core/llm_stream.py — JARVIS STREAMING LLM ENGINE
from __future__ import annotations

import json
import logging
import re
import threading
from typing import Callable, Iterator, Optional

import requests
from core.providers.ollama_manager import get_ollama_manager
from core.system.vram_orchestrator import get_vram_orchestrator

log = logging.getLogger("LLMStream")

# Sentence boundary pattern — split after . ! ? followed by space or end
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')

# Minimum chars before we fire a speak callback (avoids speaking "Hi" alone)
MIN_CHUNK_CHARS = 40

# Models optimised for conversational streaming (fast first-token latency)
# NOTE: verified against `ollama list` — only gemma2:2b and llama3.2:3b are installed
STREAM_CHAT_MODEL    = "gemma2:2b"     # Fast conversational model (confirmed installed)
STREAM_CHAT_FALLBACK = "llama3.2:3b"  # Reliable fallback (confirmed installed)


# ═══════════════════════════════════════════════════════════════════════════════
#  CORE STREAMING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _iter_chat_tokens(
    messages: list[dict],
    model:    str,
    options:  dict,
    timeout:  int = 120,
) -> Iterator[str]:
    """
    Yields tokens one-by-one from Ollama /api/chat streaming endpoint.
    """
    ollama = get_ollama_manager()
    return ollama.chat(model=model, messages=messages, stream=True, options=options, timeout=timeout)


def _iter_generate_tokens(
    prompt:  str,
    model:   str,
    options: dict,
    timeout: int = 120,
) -> Iterator[str]:
    """
    Yields tokens from Ollama /api/generate streaming endpoint.
    """
    ollama = get_ollama_manager()
    return ollama.generate(model=model, prompt=prompt, stream=True, options=options, timeout=timeout)


def _split_into_sentences(text: str) -> tuple[list[str], str]:
    """
    Split buffered text into speakable sentences + leftover partial sentence.
    Returns (sentences_ready, remainder).
    """
    parts     = _SENTENCE_END.split(text)
    if len(parts) <= 1:
        return [], text  # No complete sentence yet

    # Last part is the in-progress sentence (no terminal punctuation yet)
    remainder = parts[-1]
    sentences = [s.strip() for s in parts[:-1] if s.strip()]
    return sentences, remainder


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def stream_chat(
    messages:    list[dict],
    speak_cb:    Optional[Callable[[str], None]] = None,
    model:       str  = STREAM_CHAT_MODEL,
    temperature: float = 0.7,
    max_tokens:  int   = 1024,
    timeout:     int   = 120,
) -> str:
    """
    Stream a chat response from Ollama.
    Wraps the HTTP call in inference_context() so VRAMOrchestrator knows
    the GPU is busy and can defer any pending model prefetch safely.
    """
    options = {
        "temperature": temperature,
        "num_predict": max_tokens,
        "top_p":       0.9,
    }
    vram = get_vram_orchestrator()

    # Try streaming with primary model, then fallback
    for attempt_model in (model, STREAM_CHAT_FALLBACK):
        try:
            buffer   = ""
            full_txt = ""
            # Ghost B: acquire inference lock so prefetch is deferred
            with vram.inference_context():
                token_gen = _iter_chat_tokens(messages, attempt_model, options, timeout)
                for token in token_gen:
                    buffer   += token
                    full_txt += token
                    sentences, buffer = _split_into_sentences(buffer)
                    for sentence in sentences:
                        if sentence and len(sentence) >= MIN_CHUNK_CHARS and speak_cb:
                            speak_cb(sentence)

            # Speak any remaining buffer outside the lock (non-GPU work)
            if buffer.strip() and speak_cb:
                speak_cb(buffer.strip())

            log.info(f"[Stream] Done — {len(full_txt)} chars via {attempt_model}")
            return full_txt

        except Exception as e:
            log.warning(f"[Stream] Error ({attempt_model}): {e}")
            continue

    return ""


def stream_generate(
    prompt:      str,
    speak_cb:    Optional[Callable[[str], None]] = None,
    model:       str   = "gemma2:2b",
    temperature: float = 0.1,
    max_tokens:  int   = 600,
    timeout:     int   = 90,
) -> str:
    """
    Stream a /api/generate response (for research summaries, one-shot prompts).
    Wraps the HTTP call in inference_context() for Ghost B VRAM safety.
    """
    options = {
        "temperature": temperature,
        "num_predict": max_tokens,
    }
    vram = get_vram_orchestrator()
    try:
        buffer   = ""
        full_txt = ""
        with vram.inference_context():
            for token in _iter_generate_tokens(prompt, model, options, timeout):
                buffer   += token
                full_txt += token
                sentences, buffer = _split_into_sentences(buffer)
                for sentence in sentences:
                    if sentence and len(sentence) >= MIN_CHUNK_CHARS and speak_cb:
                        speak_cb(sentence)

        if buffer.strip() and speak_cb:
            speak_cb(buffer.strip())

        return full_txt

    except Exception as e:
        log.warning(f"[Stream] generate error ({model}): {e}")
        return ""


def stream_reply(
    user_input:  str,
    speak_cb:    Optional[Callable[[str], None]] = None,
    system_prompt: str = "You are JARVIS, a highly intelligent AI assistant. Be concise and address the user as 'sir'.",
    model:       str   = STREAM_CHAT_MODEL,
    history:     Optional[list[dict]] = None,
) -> str:
    """
    Convenience wrapper: takes a plain user string, builds messages, streams reply.
    """
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-6:])  # last 3 turns for context
    messages.append({"role": "user", "content": user_input})
    return stream_chat(messages, speak_cb=speak_cb, model=model)


def stream_reply_async(
    user_input:  str,
    speak_cb:    Optional[Callable[[str], None]] = None,
    done_cb:     Optional[Callable[[str], None]] = None,
    model:       str = STREAM_CHAT_MODEL,
    history:     Optional[list[dict]] = None,
) -> threading.Thread:
    """
    Non-blocking version — runs stream_reply in a daemon thread.
    """
    def _run():
        result = stream_reply(user_input, speak_cb=speak_cb, model=model, history=history)
        if done_cb:
            done_cb(result)

    t = threading.Thread(target=_run, daemon=True, name="LLMStream-Reply")
    t.start()
    return t


def get_stream_engine():
    """Returns this module (stateless — no instance needed)."""
    import core.agent.llm_stream as _self
    return _self
