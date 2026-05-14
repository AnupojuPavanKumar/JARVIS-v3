import logging
import threading
from typing import Tuple, Optional
from core.providers.model_router import get_router as get_model_router
from core.providers.ollama_manager import OllamaManager

log = logging.getLogger("IntentRouter")

class IntentRouter:
    """
    Unified Semantic Intent Router for JARVIS-v3.
    Uses LLM-based classification (Tier 1) with keyword fallbacks (Tier 2).
    """
    _instance = None

    INTENTS = {
        "AGENT_TASK": "Complex autonomous task requiring a multi-step plan, coding, or project building.",
        "SKILL_EXEC": "Direct command to execute a specific pre-defined skill (e.g. system volume, music, weather).",
        "WEB_RESEARCH": "A request for information that requires searching the internet and summarizing findings.",
        "CHAT": "Casual conversation, greetings, or simple questions not requiring tools.",
        "STATUS_QUERY": "Asking about the status of autonomous jobs or system health."
    }

    def __init__(self):
        self.ollama = OllamaManager()
        self.model_router = get_model_router()
        self.model = "llama3.2:3b"

    _CHAT_KEYWORDS = (
        "hi ", "hi,", "hello", "hey jarvis", "hey there",
        "good morning", "good afternoon", "good evening", "good night",
        "how are you", "what's up", "what can you do", "who are you",
        "thanks", "thank you", "ok jarvis", "okay jarvis",
    )

    _SKILL_KEYWORDS = (
        "how is the weather", "weather", "what time", "date", "play",
        "pause", "stop music", "next song", "previous song", "volume",
        "mute", "unmute", "brightness", "open ", "launch ", "start ",
        "close ", "notepad", "chrome", "vscode", "calculator", "camera",
        "screenshot", "sleep", "lock", "shutdown",
        "restart", "remind me", "remember this", "take a photo",
    )

    _WEB_RESEARCH_KEYWORDS = (
        "research", "look up", "find out", "search the web", "browse",
        "latest", "news on", "tell me about", "google", "find info",
    )

    _AGENT_TASK_KEYWORDS = (
        "build", "create", "develop", "make an app", "write a", "script",
        "automate", "debug", "fix", "refactor", "generate", "scaffold",
        "implement", "code", "program", "initialize", "setup",
    )

    def route(self, command: str) -> Tuple[str, float]:
        """
        Determine the intent of the command.
        Returns (intent_name, confidence).
        """
        lowered = command.lower().strip()

        # 0. Instant Chat Shortcuts — zero LLM overhead for greetings/small talk
        if any(w in lowered for w in self._CHAT_KEYWORDS):
            return "CHAT", 1.0
        
        # 1. Fast Keyword Heuristics (Tier 2)
        
        # AGENT_TASK has higher priority if specific coding keywords are present
        if ("write" in lowered and "script" in lowered) or \
           ("create" in lowered and "app" in lowered) or \
           ("build" in lowered and "app" in lowered):
            return "AGENT_TASK", 0.9

        if any(w in lowered for w in self._AGENT_TASK_KEYWORDS):
            # "fix" or "code" alone might be ambiguous, but in context they are likely agentic
            return "AGENT_TASK", 0.85

        if any(w in lowered for w in self._SKILL_KEYWORDS):
            return "SKILL_EXEC", 0.9
        
        if "autonomous" in lowered or "job status" in lowered or "tasks status" in lowered:
            return "STATUS_QUERY", 1.0

        if any(w in lowered for w in self._WEB_RESEARCH_KEYWORDS):
            return "WEB_RESEARCH", 0.85

        # Single-word or very short input (≤2 words) → treat as CHAT (unless caught above)
        if len(lowered.split()) <= 2:
            return "CHAT", 0.9

        # 2. Semantic Classification via LLM (only for ambiguous multi-word commands)
        intent, confidence = self._semantic_classify(command)
        
        # 3. Proactive VRAM Pre-fetching (Upgrade 2)
        from core.system.vram_orchestrator import get_vram_orchestrator
        from core.system.vram_config import get_vram_config
        vram = get_vram_orchestrator()
        vcfg = get_vram_config()
        prefetch_model = vcfg.model_for_intent(intent)
        if prefetch_model:
            vram.prefetch_model(prefetch_model)
        elif intent == "AGENT_TASK":
            vram.prefetch_model("qwen2.5-coder:7b")
        elif intent in ("CHAT", "SKILL_EXEC"):
            vram.prefetch_model("gemma2:2b")
            
        return intent, confidence

    def _semantic_classify(self, command: str) -> Tuple[str, float]:
        intents_str = "\n".join([f"- {k}: {v}" for k, v in self.INTENTS.items()])
        system_msg = (
            "You are an intent classification assistant for JARVIS. "
            "Classify user commands into exactly one of the following intents: "
            + intents_str
        )
        user_msg = f'User Command: "{command}"\n\nRespond ONLY with the intent name (e.g., CHAT, AGENT_TASK). Nothing else.'

        try:
            import requests
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 15}
            }
            response = requests.post(
                "http://localhost:11434/api/chat",
                json=payload,
                timeout=5
            )
            result = response.json().get("message", {}).get("content", "").strip().upper()

            for intent in self.INTENTS:
                if intent in result:
                    return intent, 0.8

            return "CHAT", 0.5
        except Exception as e:
            log.warning(f"Semantic classification failed: {e}")
            return "CHAT", 0.3

_intent_router_lock = threading.Lock()

def get_intent_router() -> IntentRouter:
    if IntentRouter._instance is None:
        with _intent_router_lock:
            if IntentRouter._instance is None:
                IntentRouter._instance = IntentRouter()
    return IntentRouter._instance
