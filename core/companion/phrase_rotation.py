# core/companion/phrase_rotation.py — JARVIS PHRASE ROTATION
"""
Prevents repetitive assistant phrasing over long-term usage.
Rotates through equivalent acknowledgment/response phrases so JARVIS never
sounds like a broken record.

Phrase sets by category:
  - acknowledgments: "Understood.", "Noted.", "Acknowledged.", "Certainly.", "Right away."
  - completions:    "Done.", "Finished.", "Complete.", "All set.", "Handled."
  - confirmations:   "Confirmed.", "Agreed.", "Proceeding.", "As you wish.", "Executing."
  - errors:          "Encountered an issue.", "Something went wrong.", "Failed to complete.",
                      "That's beyond my current reach.", "Unable to process that."
  - errors_critical: "Critical error detected.", "Major failure — taking action."
  - greetings:        "Good day, sir.", "Hello.", "At your service.", "JARVIS online.", "Standing by."
  - idle_acks:       "Yes?", "I'm here.", "Sir?", "Ready.", "Listening."
"""
from __future__ import annotations

import random
import threading
import time
from typing import Optional


class PhraseRotator:
    """
    Returns a rotated phrase from each category, cycling evenly.
    Thread-safe. Ensures no phrase repeats consecutively.
    """

    PHRASES = {
        "acknowledgment": [
            "Understood.", "Acknowledged.", "Certainly.", "Right away, sir.",
            "Noted.", "Copy that.", "As you say.", "Proceeding.",
        ],
        "completion": [
            "Done, sir.", "Finished.", "All set.", "Handled.",
            "Complete.", "Ready.", "That's done.", "Affirmative.",
        ],
        "confirmation": [
            "Confirmed.", "Agreed.", "Proceeding.", "As you wish.",
            "Acknowledged.", "Understood.", "Executing.", "On it.",
        ],
        "error": [
            "Encountered an issue.", "Something went wrong.",
            "That's beyond my current reach.", "Unable to process that.",
            "Operation failed.", "That didn't work.",
        ],
        "error_critical": [
            "Critical error detected, sir.",
            "Major failure — taking corrective action.",
            "Operational failure. Switching to degraded mode.",
        ],
        "greeting": [
            "Good day, sir.", "Hello.", "At your service.",
            "JARVIS online.", "Standing by, sir.",
        ],
        "idle_ack": [
            "Yes, sir?", "I'm here.", "Sir?", "Ready.", "Listening.",
            "Yes?", "JARVIS online.",
        ],
        "mode_change": [
            "Mode updated.", "Switching modes.", "Adjusted.", "Done.",
        ],
        "thinking": [
            "Processing.", "Calculating.", "One moment.", "Analysing.",
            "Working on it.", "Hold on.", "In progress.",
        ],
        "success_hint": [
            "Operation successful.", "Completed without issue.",
            "Executed cleanly.", "All systems nominal.",
        ],
        "info": [
            "Information.", "FYI.", "Noted.", "Here you are.",
            "Here's what I found.", "Here's the result.",
        ],
    }

    def __init__(self):
        self._lock       = threading.RLock()
        self._indexes: dict[str, int] = {cat: 0 for cat in self.PHRASES}
        self._last: dict[str, str]     = {}   # category → last returned

    def get(self, category: str = "acknowledgment") -> str:
        """Return next phrase from category, avoiding immediate repeats."""
        with self._lock:
            phrases = self.PHRASES.get(category, ["Done."])
            idx = self._indexes.get(category, 0)

            # Try to avoid repeating the last phrase
            attempts = 0
            while attempts < len(phrases):
                phrase = phrases[idx % len(phrases)]
                idx = (idx + 1) % len(phrases)
                attempts += 1
                if phrase != self._last.get(category) or attempts == len(phrases):
                    self._indexes[category] = idx
                    self._last[category] = phrase
                    return phrase

            # Fallback: just return current
            phrase = phrases[self._indexes.get(category, 0) % len(phrases)]
            return phrase

    def vary_response(self, template: str, category: str = "acknowledgment") -> str:
        """
        For responses like "Opening {app}." — occasionally substitute with a phrase
        that matches the intent, creating variety without changing meaning.
        """
        if random.random() > 0.3:  # 30% chance of variation
            return template
        return self.get(category)


# Singleton
_rotator: Optional[PhraseRotator] = None
_rotator_lock = threading.Lock()

def get_rotator() -> PhraseRotator:
    global _rotator
    with _rotator_lock:
        if _rotator is None:
            _rotator = PhraseRotator()
        return _rotator