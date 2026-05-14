import logging
from typing import Tuple

log = logging.getLogger("IntentEngine")

class IntentEngine:
    """
    Classifies user commands into broad intent categories.
    Used for routing and dispatching.
    """

    # Intent categories - order matters! More specific intents should come first
    INTENTS = {
        "DEPLOY":         ["push to production", "vercel", "github pages", "deploy to"],
        "AGENT_TASK":     ["write and deploy", "build a", "create a", "make a", "develop", "generate", "build", "create", "make"],
        "WEB_RESEARCH":   ["what is", "tell me about", "research", "analyze", "summarize", "look up"],
        "SEARCH_WEB":     ["search for", "google", "find"],
        "FILE_OPS":       ["create file", "delete", "remove", "move", "rename", "copy"],
        "SYSTEM_CONTROL": ["shutdown", "restart", "sleep", "lock", "volume", "mute", "brightness"],
        "RECALL":         ["what were we talking about", "recall", "previous topic", "last context"],
        "COMMUNICATION":  ["email", "message", "text", "notify"],
        "FUN":            ["joke", "fact", "game"]
    }

    def __init__(self):
        # We'll use a simple keyword-based approach for the base class
        # A more advanced version might use the IntentClassifier (LLM)
        pass

    def detect_intent(self, command: str) -> str:
        """Returns the detected intent string."""
        intent, confidence = self.detect_with_confidence(command)
        return intent

    def detect_with_confidence(self, command: str) -> Tuple[str, float]:
        """Returns (intent, confidence_score)."""
        lowered = command.lower().strip()

        # 1. First check for multi-word phrases (more specific)
        best_intent = "CHAT"
        best_score = 0.1

        # Sort keywords by length (longer = more specific = higher priority)
        for intent, keywords in self.INTENTS.items():
            sorted_keywords = sorted(keywords, key=len, reverse=True)
            for kw in sorted_keywords:
                if kw in lowered:
                    # Score based on keyword length (more specific = higher score)
                    # Also factor in position (earlier = more likely the main intent)
                    base_score = min(0.9, 0.5 + (len(kw) * 0.05))
                    pos = lowered.find(kw)
                    position_bonus = 0.1 if pos < len(lowered) * 0.3 else 0.0
                    score = base_score + position_bonus
                    if score > best_score:
                        best_score = score
                        best_intent = intent

        # Special logic for AGENT_TASK with project indicators
        project_words = ["website", "portfolio", "app", "todo", "script", "project", "game", "tool"]
        action_words = ["build", "create", "make", "develop", "generate"]
        if any(word in lowered for word in project_words) and \
           any(word in lowered for word in action_words):
            return "AGENT_TASK", 0.95

        # Fallback to general CHAT
        return best_intent, best_score
