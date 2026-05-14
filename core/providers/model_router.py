# core/model_router.py — MULTI-MODEL ROUTING BY TASK TYPE
# ──────────────────────────────────────────────────────────────────────────────
# Routes each LLM call to the optimal Ollama model based on task type.
# Avoids wasting qwen2.5:7b (code model) on simple chat and vice versa.
#
# Model → Task affinity:
#   qwen2.5:7b   → CODE   (best structured JSON + code generation)
#   llama3       → CHAT   (natural conversation, concise replies)
#   llava:7b     → VISION (multimodal — image understanding)
#   mistral:7b   → DOCS   (technical writing, documentation)
#   phi3:mini    → QUICK  (simple yes/no, fast 1-line responses, 2.3GB)
#
# Usage:
#   from core.providers.model_router import ModelRouter
#   router = ModelRouter()
#   model = router.route("write a python script to parse CSV")  → "qwen2.5:7b"
# ──────────────────────────────────────────────────────────────────────────────

import re
import requests
from typing import Optional


OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"

# ── Model pool ─────────────────────────────────────────────────────────────────
MODELS = {
    "code":     "qwen2.5-coder:7b",   # 4.7GB — coding-specific fine-tune, BEST for code
    "chat":     "llama3.2:3b",         # 2.0GB — fast, natural conversation, low VRAM
    "vision":   "llava:7b",             # 4.7GB — multimodal image understanding
    "docs":     "mistral:7b",           # 4.1GB — technical writing, long docs
    "quick":    "phi3:mini",            # 2.3GB — fast, minimal VRAM, 1-liners
    "reasoning":"deepseek-r1:7b",      # 4.7GB — chain-of-thought, analysis, planning
}

# Default fallback chain (ordered by capability vs size)
_FALLBACK_CHAIN = ["qwen2.5-coder:7b", "qwen2.5:7b", "llama3.2:3b", "llama3:latest", "mistral:7b", "phi3:mini"]

# ── Keyword classifiers ────────────────────────────────────────────────────────
_CODE_SIGNALS = [
    "write", "code", "script", "function", "class", "build", "create", "implement",
    "program", "debug", "fix", "refactor", "python", "javascript", "html", "css",
    "api", "endpoint", "database", "query", "sql", "json", "yaml", "dockerfile",
    "git", "deploy", "test", "unittest", "pytest", "algorithm", "data structure",
    "parse", "regex", "module", "package", "import", "compile", "run", "execute"
]
_VISION_SIGNALS = [
    "image", "photo", "picture", "screenshot", "camera", "see", "look", "detect",
    "identify", "recognize", "ocr", "read text", "scan", "visual", "what is in",
    "describe", "caption", "face", "object"
]
_DOCS_SIGNALS = [
    "document", "readme", "explain", "summarize", "report", "essay", "write about",
    "research", "analysis", "outline", "draft", "email", "letter", "proposal",
    "specification", "technical doc", "changelog", "release notes"
]
_QUICK_SIGNALS = [
    "yes or no", "true or false", "quick", "simple", "just tell me", "one word",
    "briefly", "short answer", "status", "is it", "are you", "do you"
]
_REASONING_SIGNALS = [
    "analyze", "plan", "architecture", "design", "strategy", "compare", "evaluate",
    "pros and cons", "what should i", "how should i", "best approach", "think through",
    "step by step", "reason", "why is", "trade-off", "decision"
]


class ModelRouter:
    """
    Selects the best available Ollama model for a given task.
    Falls back gracefully if the preferred model isn't installed.
    """

    def __init__(self):
        self._available : list[str] = []
        self._refresh_available()

    def _refresh_available(self):
        """Query Ollama for installed models (cached — call refresh() to update)."""
        try:
            r = requests.get(OLLAMA_TAGS_URL, timeout=3)
            if r.status_code == 200:
                tags = r.json().get("models", [])
                self._available = [m.get("name", "") for m in tags]
                print(f"[ModelRouter] Available models: {self._available}")
        except Exception:
            print("[ModelRouter] Could not reach Ollama — using defaults.")
            self._available = _FALLBACK_CHAIN[:]

    def _is_available(self, model: str) -> bool:
        """Check if a model name (exact or prefix match) is installed."""
        if not self._available:
            return True   # Can't check — optimistically try
        model_base = model.split(":")[0]
        for m in self._available:
            if model == m or m.startswith(model_base):
                return True
        return False

    def classify_task(self, prompt: str) -> str:
        """
        Returns task category: 'code' | 'vision' | 'docs' | 'quick' | 'chat'
        Uses keyword heuristics — fast, no LLM call needed.
        """
        lower = prompt.lower()

        # Score each category by keyword hits
        code_score  = sum(1 for kw in _CODE_SIGNALS      if kw in lower)
        vis_score   = sum(1 for kw in _VISION_SIGNALS    if kw in lower)
        docs_score  = sum(1 for kw in _DOCS_SIGNALS      if kw in lower)
        quick_score = sum(1 for kw in _QUICK_SIGNALS     if kw in lower)
        reason_score= sum(1 for kw in _REASONING_SIGNALS if kw in lower)

        # Command length heuristic: short commands lean toward "quick"
        word_count = len(prompt.split())
        if word_count <= 5 and quick_score == 0 and code_score == 0:
            quick_score += 1

        scores = {
            "code":      code_score,
            "vision":    vis_score,
            "docs":      docs_score,
            "quick":     quick_score,
            "reasoning": reason_score,
            "chat":      0,   # baseline
        }

        best = max(scores, key=scores.get)
        # If all zero, default to chat
        if scores[best] == 0:
            best = "chat"

        return best

    def route(self, prompt: str, prefer: Optional[str] = None) -> str:
        """
        Returns the model name to use for the given prompt.
        prefer: force a category ('code', 'chat', 'vision', 'docs', 'quick')
        """
        category = prefer or self.classify_task(prompt)
        preferred = MODELS.get(category, MODELS["chat"])

        if self._is_available(preferred):
            print(f"[ModelRouter] '{prompt[:40]}...' -> [{category}] {preferred}")
            return preferred

        # Fallback: try chain in order
        for fallback in _FALLBACK_CHAIN:
            if self._is_available(fallback):
                print(f"[ModelRouter] Fallback: {preferred} -> {fallback}")
                return fallback

        # Last resort: return preferred and let Ollama error handle it
        return preferred

    def route_with_meta(self, prompt: str) -> dict:
        """Returns {model, category, confidence} dict for agent metadata."""
        category = self.classify_task(prompt)
        model    = self.route(prompt)
        return {"model": model, "category": category}

    def refresh(self):
        """Re-query Ollama for installed models (call after pulling a new model)."""
        self._refresh_available()

    @property
    def available_models(self) -> list[str]:
        return self._available.copy()


# Module singleton
_router = ModelRouter()


def get_router() -> ModelRouter:
    return _router


def route_prompt(prompt: str, prefer: Optional[str] = None) -> str:
    """Convenience function — returns model name for a prompt."""
    return _router.route(prompt, prefer)
