import logging

log = logging.getLogger("IntentClassifier")

class IntentClassifier:
    """
    Determines the user's intent from natural language.

    Uses IntentRouter (keyword-first, fast) as the primary classifier.
    Falls back to registry triggers only for exact skill keyword matches.
    """
    def __init__(self, skill_registry):
        self.skill_registry = skill_registry

    def classify(self, command: str) -> str | None:
        cmd_lower = command.lower()

        # Tier 1: Fast registry trigger match (exact keyword only)
        for trigger, mod in self.skill_registry.triggers.items():
            if trigger in cmd_lower:
                return mod.SKILL_NAME

        # Tier 2: IntentRouter for semantic classification
        try:
            from core.engines.intent_router import get_intent_router
            router = get_intent_router()
            intent, _ = router.route(command)

            # Map intent to skill name if it matches a known skill
            if intent == "SKILL_EXEC":
                # Re-try registry triggers with more lenient matching
                for trigger, mod in self.skill_registry.triggers.items():
                    if trigger in cmd_lower:
                        return mod.SKILL_NAME
            elif intent == "WEB_RESEARCH":
                from core.agent.web_research import get_web_agent
                return "WebResearch"
        except Exception as e:
            log.debug(f"[IntentClassifier] Router fallback: {e}")

        return None