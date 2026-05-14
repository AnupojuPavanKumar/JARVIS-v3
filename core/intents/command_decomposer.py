# core/intents/command_decomposer.py — JARVIS Multi-Action Decomposition
"""
Decomposes compound commands into individual actions.

Example:
  "open vscode and explain this bug"
    → Action 1: OPEN_APP("vscode")       [deterministic]
    → Action 2: AI_REASONING("debug")    [LLM]

Handles: "and", "then", "also", "plus", sequential patterns.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("Decomposer")

# ── Separator patterns ────────────────────────────────────────────────────────
SEPARATORS = [
    r"\s+and\s+",
    r"\s+also\s+",
    r"\s+plus\s+",
    r"\s+then\s+",
    r",\s+",
    r";\s+",
]

# Commands requiring AI reasoning (after a separator)
AI_INDICATORS = [
    "explain", "why", "how", "what", "debug", "fix", "analyze", "analyse",
    "help me", "teach me", "show me", "tell me", "write code", "code",
    "find bug", "review", "refactor", "improve", "optimize", "plan",
    "design", "architecture", "suggest", "recommend", "compare",
]

# Commands that are always deterministic (before a separator)
DETERMINISTIC_INDICATORS = [
    "open", "close", "launch", "start", "run", "volume", "mute",
    "play", "pause", "stop", "next", "lock", "restart", "shutdown",
    "search for", "search the web", "google", "minimize", "maximize",
]


@dataclass
class DecomposedAction:
    command: str
    is_deterministic: bool
    is_ai_required: bool
    is_complete: bool = True


@dataclass
class DecompositionResult:
    actions: list[DecomposedAction]
    is_compound: bool
    decomposition_type: str  # "sequential", "parallel", "mixed"


class CommandDecomposer:
    """
    Parses compound commands into individual sub-commands.

    Rules:
      1. Split on separators (and, also, then, comma)
      2. Each segment is a separate action
      3. If any segment contains AI_INDICATORS → that segment is AI
      4. If the first segment is deterministic → execute first, then AI
      5. Compound commands always route to execution queue with ordered actions
    """

    def decompose(self, command: str) -> DecompositionResult:
        """
        Split a compound command into sub-actions.
        Returns DecompositionResult with list of actions.
        """
        original = command
        normalized = command.lower().strip()

        # ── Check if compound ─────────────────────────────────────────────────
        is_compound = any(re.search(sep, normalized) for sep in SEPARATORS)

        if not is_compound:
            is_det, is_ai = self._classify_single(normalized)
            return DecompositionResult(
                actions=[DecomposedAction(
                    command=original,
                    is_deterministic=is_det,
                    is_ai_required=is_ai,
                )],
                is_compound=False,
                decomposition_type="single",
            )

        # ── Split into segments ───────────────────────────────────────────────
        segments = self._split(normalized, original)

        if len(segments) <= 1:
            return DecompositionResult(
                actions=[DecomposedAction(command=original,
                                         is_deterministic=True,
                                         is_ai_required=False)],
                is_compound=False,
                decomposition_type="single",
            )

        # ── Classify each segment ────────────────────────────────────────────
        actions: list[DecomposedAction] = []
        for i, (seg_lower, seg_original) in enumerate(segments):
            is_det = any(ind in seg_lower for ind in DETERMINISTIC_INDICATORS)
            is_ai = any(ind in seg_lower for ind in AI_INDICATORS)

            # First segment: prefer deterministic unless explicitly AI
            if i == 0 and not is_ai:
                is_det = True
                is_ai = False

            # Middle/last segments: be more permissive with AI
            if is_ai and not is_det:
                is_ai = True
                is_det = False

            actions.append(DecomposedAction(
                command=seg_original.strip(),
                is_deterministic=is_det,
                is_ai_required=is_ai,
            ))

        # Determine decomposition type
        det_count = sum(1 for a in actions if a.is_deterministic)
        ai_count = sum(1 for a in actions if a.is_ai_required)

        if det_count > 0 and ai_count > 0:
            decomp_type = "mixed"
        elif all(a.is_deterministic for a in actions):
            decomp_type = "parallel"
        else:
            decomp_type = "sequential"

        log.info(f"[Decomposer] Split '{original[:50]}' -> {len(actions)} actions ({decomp_type})")

        return DecompositionResult(
            actions=actions,
            is_compound=True,
            decomposition_type=decomp_type,
        )

    def _split(self, lowered: str, original: str) -> list[tuple[str, str]]:
        """Split on separators, preserving original casing."""
        pattern = "|".join(SEPARATORS)
        parts = re.split(pattern, lowered, maxsplit=3)

        # Map back to original
        result: list[tuple[str, str]] = []
        remaining_original = original
        for part in parts:
            part_lower = part.strip()
            if not part_lower:
                continue

            # Find the original text for this segment
            idx = remaining_original.lower().find(part_lower)
            if idx >= 0:
                result.append((part_lower, remaining_original[:idx + len(part_lower)]))
                remaining_original = remaining_original[idx + len(part_lower):].lstrip(",; ")
            else:
                result.append((part_lower, part_lower))

        return result

    def _classify_single(self, lowered: str) -> tuple[bool, bool]:
        """Classify a single command (non-compound)."""
        is_det = any(ind in lowered for ind in DETERMINISTIC_INDICATORS)
        is_ai = any(ind in lowered for ind in AI_INDICATORS)
        return is_det, is_ai

    def should_decompose(self, command: str) -> bool:
        """Quick check if a command needs decomposition."""
        lowered = command.lower()
        return any(re.search(sep, lowered) for sep in SEPARATORS)


def get_decomposer() -> CommandDecomposer:
    return CommandDecomposer()