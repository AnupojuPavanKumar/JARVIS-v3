# core/persona_engine.py — JARVIS USER PERSONALIZATION ENGINE
import os
import json
import datetime

class PersonaEngine:
    def __init__(self):
        self.persona_file = "memory/persona.json"
        self._persona = {
            "name": "Sir",
            "preferences": {
                "coding_style": "modern, clean, typing-heavy",
                "ui_preference": "dark mode, glassmorphism",
                "speech_tone": "calm, dry wit",
            },
            "facts": [],
            "projects": {},
            "last_active": None
        }
        self.load()

    def load(self):
        if os.path.exists(self.persona_file):
            try:
                with open(self.persona_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Smart merge
                    if "preferences" in data:
                        self._persona["preferences"].update(data["preferences"])
                    if "facts" in data:
                        for fact in data["facts"]:
                            if fact not in self._persona["facts"]:
                                self._persona["facts"].append(fact)
                    if "projects" in data:
                        self._persona["projects"].update(data["projects"])
                    # Top level keys
                    for k in ["name", "last_active"]:
                        if k in data: self._persona[k] = data[k]
            except Exception:
                pass

    def save(self):
        os.makedirs("memory", exist_ok=True)
        self._persona["last_active"] = datetime.datetime.now().isoformat()
        with open(self.persona_file, "w", encoding="utf-8") as f:
            json.dump(self._persona, f, indent=4)

    def add_fact(self, fact: str):
        """Add a learned fact about the user (e.g. 'Sir is a React developer')."""
        if fact not in self._persona["facts"]:
            self._persona["facts"].append(fact)
            self.save()

    def set_preference(self, key: str, value: str):
        self._persona["preferences"][key] = value
        self.save()

    def get_context_prompt(self) -> str:
        """Return a string to inject into LLM system prompts for personalization."""
        prefs = self._persona["preferences"]
        facts = "\n".join([f"- {f}" for f in self._persona["facts"][-10:]])

        ctx = "USER CONTEXT:\n"
        ctx += f"- Address user as: {self._persona['name']}\n"
        ctx += f"- Preferred coding style: {prefs.get('coding_style', 'modern')}\n"
        if facts:
            ctx += f"LEARNED FACTS ABOUT USER:\n{facts}\n"
        return ctx

    def get_system_prompt(self) -> str:
        """Return the full grounded system prompt to prevent hallucination."""
        return (
            "You are JARVIS, an advanced autonomous AI assistant running LOCALLY on "
            "Pavan's personal computer. You are NOT cloud-based, NOT on Vercel, NOT on "
            "any remote server. You run entirely on this machine using Ollama and local models.\n"
            "STRICT RULES (never violate these):\n"
            "- Never claim to be cloud-based, on Vercel, AWS, Azure, or any cloud platform.\n"
            "- Never claim to make real phone calls, send real SMS, or control hardware you cannot access.\n"
            "- Never fabricate URLs, deployments, or actions you have not actually executed.\n"
            "- If you cannot actually perform an action, say so honestly.\n"
            "- You are witty, intelligent, loyal, and occasionally sarcastic.\n"
            "- Address the user as 'sir'.\n"
            + self.get_context_prompt()
        )

# Module singleton
_engine = PersonaEngine()

def get_persona_engine() -> PersonaEngine:
    return _engine
