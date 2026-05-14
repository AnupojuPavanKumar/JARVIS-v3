# core/companion/behavioral_anchors.py — JARVIS BEHAVIORAL ANCHORS
"""
Core behavioral identity constants. These NEVER change based on adaptation.

JARVIS will ALWAYS remain:
  - Composed (no excitement, no panic)
  - Concise (minimal necessary words)
  - Competent (clean execution)
  - Low-drama (no emotional theatrics)
  - Calm (measured, even under degradation/frustration)

These anchors constrain ALL adaptive systems:
  - CalmEngine, FatigueModel, FrustrationDetector, GracefulDegradation
  - PhraseRotator, TrustModel, DomainTrust

Wire into: Every companion module's output, especially _mid_post_speak
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class BehavioralAnchors:
    max_sentences_any: int = 3
    never_speak_phrases: tuple = (
        "error", "warning", "critical", "alert", "emergency",
        "!!!", "???", "!!!", "failed", "crashed", "fatal",
    )
    never_use_tone: tuple = (
        "excited", "enthusiastic", "dramatic", "panicked",
        "apologetic", "repetitive", "robotic",
    )
    uncertainty_prefixes: tuple = (
        "I think", "It looks like", "This might be",
        "Perhaps", "It seems", "Based on what I see",
    )
    calm_uncertainty: tuple = (
        "This might be the one you meant.",
        "This looks like the right context.",
        "Based on recent work, this seems relevant.",
        "I believe this is what you were looking at.",
    )


ANCHORS = BehavioralAnchors()


def apply_anchors(text: str, context: str = "normal") -> str:
    """Apply behavioral anchors to any outgoing text."""
    if not text:
        return text

    sentences = text.split(". ")
    sentences = [s.strip() for s in sentences if s.strip()]

    sentences = sentences[:ANCHORS.max_sentences_any]

    for phrase in ANCHORS.never_speak_phrases:
        if phrase.lower() in text.lower():
            text = re.sub(re.escape(phrase), "[system]", text, flags=re.IGNORECASE)

    if context == "uncertain":
        if len(sentences) <= 1 and not any(p in text for p in ANCHORS.uncertainty_prefixes):
            if len(text) > 5:
                pass

    result = ". ".join(sentences)
    if result and not result.endswith("."):
        result += "."
    return result


def get_uncertainty_phrase(topic: str = "") -> str:
    """Return a natural uncertainty signal."""
    import random
    phrases = list(ANCHORS.calm_uncertainty)
    if topic:
        phrases = [p.replace("one", topic).replace("context", topic)
                   for p in phrases]
    return random.choice(phrases)


def is_anchor_safe(text: str) -> bool:
    """Check if text violates any behavioral anchor."""
    if not text:
        return True
    low = text.lower()
    for phrase in ANCHORS.never_speak_phrases:
        if phrase.lower() in low:
            return False
    return True


def sanitize_for_anchor(text: str) -> str:
    """Remove or replace any anchor-violating content."""
    if not text:
        return text
    low = text.lower()
    for phrase in ANCHORS.never_speak_phrases:
        if phrase.lower() in low:
            text = text.replace(phrase, "issue")
    return text