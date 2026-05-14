# core/intents/trigger_scoring.py — JARVIS Tokenized Trigger Scoring System
"""
Replaces giant keyword arrays with a weighted token scoring system.

Benefits:
  - No ambiguity from large flat arrays
  - Priority weighting (verb > object > modifier)
  - Partial matching support
  - Alias normalization
  - Configurable intent definitions
  - Extensible grammar
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("TriggerScoring")

# Token weight categories
WEIGHT_VERB      = 3.0   # Primary action word
WEIGHT_NOUN     = 2.0   # Target/object word
WEIGHT_MODIFIER  = 1.0   # Adjectives/adverbs
WEIGHT_CONTEXT   = 0.5  # Ambient/context words

# ── Token definitions (configurable) ───────────────────────────────────────────

@dataclass
class IntentToken:
    tokens: list[str]   # lowercase token forms
    weight: float       # scoring weight
    priority: int      # 1=highest precedence


@dataclass
class IntentDefinition:
    name: str
    tokens: list[IntentToken]
    min_score: float = 0.5
    requires_target: bool = False
    allow_ambiguous: bool = False


class IntentDefinitions:
    """
    Intent token grammar — single source of truth.
    Each intent has weighted tokens, priority order, and scoring rules.
    """

    @staticmethod
    def all() -> list[IntentDefinition]:
        return [
            IntentDefinition(
                name="OPEN_APP",
                requires_target=True,
                tokens=[
                    IntentToken(
                        ["open", "launch", "start", "run", "execute", "begin",
                         "fire up", "boot up", "start up", "load", "activate",
                         "show", "display", "go to", "navigate to", "switch to",
                         "bring up", "start"],
                        WEIGHT_VERB,
                        priority=1,
                    ),
                    IntentToken(
                        ["vscode", "code", "chrome", "firefox", "edge", "notepad",
                         "notepad++", "calculator", "calc", "cmd", "command prompt",
                         "powershell", "ps", "explorer", "file explorer", "spotify",
                         "discord", "slack", "teams", "zoom", "word", "excel",
                         "powerpoint", "outlook", "onenote", "sublime", "pycharm",
                         "webstorm", "intellij", "jupyter", "terminal", "git bash",
                         "obsidian", "postman", "docker", "virtualbox", "task manager",
                         "regedit", "device manager", "control panel", "snip",
                         "snipping tool", "settings", "photos", "camera",
                         "terminal", "photos", "word", "excel", "powerpoint",
                         "teams", "outlook", "onenote", "anaconda", "docker",
                         "postman", "virtualbox", "vlc", "spotify"],
                        WEIGHT_NOUN,
                        priority=2,
                    ),
                ],
            ),
            IntentDefinition(
                name="CLOSE_APP",
                requires_target=True,
                tokens=[
                    IntentToken(
                        ["close", "quit", "exit", "kill", "terminate",
                         "shut down", "stop application", "end"],
                        WEIGHT_VERB,
                        priority=1,
                    ),
                ],
            ),
            IntentDefinition(
                name="VOLUME_CONTROL",
                tokens=[
                    IntentToken(
                        ["volume", "mute", "unmute", "audio", "sound"],
                        WEIGHT_VERB,
                        priority=1,
                    ),
                    IntentToken(
                        ["up", "louder", "raise", "increase", "max", "higher"],
                        WEIGHT_MODIFIER,
                        priority=2,
                    ),
                    IntentToken(
                        ["down", "quieter", "lower", "decrease", "min", "reduce"],
                        WEIGHT_MODIFIER,
                        priority=2,
                    ),
                    IntentToken(
                        ["mute", "unmute", "silence", "silenced"],
                        WEIGHT_VERB,
                        priority=1,
                    ),
                ],
            ),
            IntentDefinition(
                name="MEDIA_CONTROL",
                tokens=[
                    IntentToken(
                        ["play", "pause", "resume", "stop", "next", "previous",
                         "skip", "forward", "back", "track"],
                        WEIGHT_VERB,
                        priority=1,
                    ),
                    IntentToken(
                        ["music", "song", "track", "playback", "media"],
                        WEIGHT_CONTEXT,
                        priority=3,
                    ),
                ],
            ),
            IntentDefinition(
                name="SYSTEM_CONTROL",
                tokens=[
                    IntentToken(
                        ["lock", "sleep", "hibernate", "restart", "reboot",
                         "shutdown", "shut down", "log off", "sign out", "log out",
                         "sign off", "reboot system"],
                        WEIGHT_VERB,
                        priority=1,
                    ),
                ],
            ),
            IntentDefinition(
                name="WINDOW_CONTROL",
                tokens=[
                    IntentToken(
                        ["minimize", "minimise", "maximize", "maximise", "restore",
                         "close window", "new tab", "switch window", "next window",
                         "previous window", "snap window", "close tab"],
                        WEIGHT_VERB,
                        priority=1,
                    ),
                ],
            ),
            IntentDefinition(
                name="WEB_SEARCH",
                requires_target=True,
                tokens=[
                    IntentToken(
                        ["search", "google", "bing", "duckduckgo", "look up",
                         "find on web", "browse", "web search", "search the web",
                         "search online", "search for"],
                        WEIGHT_VERB,
                        priority=1,
                    ),
                    IntentToken(
                        ["wikipedia", "wiki"],
                        WEIGHT_NOUN,
                        priority=2,
                    ),
                ],
            ),
            IntentDefinition(
                name="FILE_OPEN",
                requires_target=True,
                tokens=[
                    IntentToken(
                        ["open file", "open document", "open pdf", "open folder",
                         "open directory", "browse to", "navigate to file",
                         "show file", "find file", "locate file", "read file",
                         "view file", "access file"],
                        WEIGHT_VERB,
                        priority=1,
                    ),
                ],
            ),
        ]


@dataclass
class ScoredIntent:
    intent_name: str
    score: float
    matched_tokens: list[str]
    confidence: float
    target: Optional[str] = None
    details: dict = field(default_factory=dict)


class TriggerScorer:
    """
    Tokenized scoring engine for intent classification.
    Replaces flat keyword arrays with weighted grammar scoring.
    """

    def __init__(self):
        self._intents = {d.name: d for d in IntentDefinitions.all()}

    def score(self, command: str) -> list[ScoredIntent]:
        """
        Score all intents against a command.
        Returns sorted list of (score, intent) descending.
        """
        tokens = self._tokenize(command)
        token_set = set(tokens)
        results: list[ScoredIntent] = []

        for intent_name, intent_def in self._intents.items():
            score, matched = self._score_intent(intent_def, tokens, token_set)

            if score > 0:
                # Confidence = normalized score (max possible = sum of all weights)
                max_score = sum(t.weight * 1.5 for t in intent_def.tokens)
                confidence = min(1.0, score / max_score) if max_score > 0 else 0

                # Extract target
                target = self._extract_target(command, intent_def, tokens)

                results.append(ScoredIntent(
                    intent_name=intent_name,
                    score=score,
                    matched_tokens=matched,
                    confidence=confidence,
                    target=target,
                ))

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def _tokenize(self, command: str) -> list[str]:
        """Normalize and tokenize a command string."""
        # Lowercase
        lowered = command.lower().strip()
        # Remove punctuation but keep spaces
        cleaned = re.sub(r"[^\w\s]", " ", lowered)
        # Split into tokens
        tokens = cleaned.split()
        # Remove very short noise tokens
        tokens = [t for t in tokens if len(t) >= 2]
        return tokens

    def _score_intent(
        self,
        intent_def: IntentDefinition,
        tokens: list[str],
        token_set: set[str],
    ) -> tuple[float, list[str]]:
        """Score a single intent against token list."""
        total_score = 0.0
        matched: list[str] = []

        for intent_token in intent_def.tokens:
            for t in intent_token.tokens:
                if t in token_set:
                    # Weight × priority bonus
                    priority_bonus = 1.0 + (0.1 * (1 / max(intent_token.priority, 1)))
                    score = intent_token.weight * priority_bonus
                    total_score += score
                    matched.append(t)
                    break  # Only count each token group once

        # Bonus: consecutive tokens (phrases)
        text = " ".join(tokens)
        for intent_token in intent_def.tokens:
            for t in intent_token.tokens:
                if " " in t and t in text:
                    total_score += intent_token.weight * 1.5
                    matched.append(t)

        return total_score, matched

    def _extract_target(
        self,
        command: str,
        intent_def: IntentDefinition,
        tokens: list[str],
    ) -> Optional[str]:
        """Extract the target argument from a command."""
        lowered = command.lower()

        # Get the primary verb tokens for this intent
        verb_tokens = []
        for it in intent_def.tokens:
            if it.priority == 1:
                verb_tokens.extend(it.tokens)

        for vt in verb_tokens:
            idx = lowered.find(vt)
            if idx != -1:
                after = lowered[idx + len(vt):].strip()
                # Remove common leading words
                for prefix in ["the ", "a ", "an ", " "]:
                    if after.startswith(prefix):
                        after = after[len(prefix):]
                after = after.strip('."\'-')
                if after and len(after) >= 2:
                    return after

        # Fallback: return full command minus common prepositions
        for prep in ["to ", "for ", "with ", "on "]:
            for token in tokens:
                if token.startswith(prep):
                    return token[len(prep):]

        return None

    def best_intent(self, command: str) -> Optional[ScoredIntent]:
        """Return the highest-scoring intent, or None if below threshold."""
        scores = self.score(command)
        if not scores:
            return None

        top = scores[0]
        intent_def = self._intents.get(top.intent_name)

        # Apply minimum threshold
        if intent_def and top.score < intent_def.min_score:
            return None

        # Disallow ambiguous results
        if len(scores) >= 2 and intent_def:
            if not intent_def.allow_ambiguous:
                gap = scores[0].score - scores[1].score
                if gap < 0.3:
                    # Too close — return UNKNOWN
                    return None

        # Require target
        if intent_def and intent_def.requires_target:
            if not top.target:
                return None

        return top


def get_trigger_scorer() -> TriggerScorer:
    return TriggerScorer()