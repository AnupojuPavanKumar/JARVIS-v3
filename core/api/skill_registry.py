# core/skill_registry.py - JARVIS Skill Registry
import os
import importlib.util
import sys

class SkillRegistry:
    """
    Scans the skills directory, loads valid skill modules,
    and routes commands to them based on their triggers.
    """
    def __init__(self, skills_dir="skills"):
        self.skills_dir = skills_dir
        self.skills = {} # name -> module
        self.triggers = {} # keyword -> module
        self.load_skills()

    def load_skills(self):
        """Discovers and loads all .py files in the skills directory."""
        self.skills.clear()
        self.triggers.clear()

        if not os.path.exists(self.skills_dir):
            os.makedirs(self.skills_dir, exist_ok=True)
            return

        for filename in os.listdir(self.skills_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                self._load_skill(filename)

    def _load_skill(self, filename):
        name = filename[:-3]
        path = os.path.join(self.skills_dir, filename)
        
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            try:
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                
                # Validation: must have SKILL_NAME, TRIGGERS list, and run()
                if hasattr(mod, "SKILL_NAME") and hasattr(mod, "TRIGGERS") and hasattr(mod, "run"):
                    self.skills[mod.SKILL_NAME] = mod
                    for trigger in mod.TRIGGERS:
                        self.triggers[trigger.lower()] = mod
                    print(f"[SkillRegistry] Loaded: {mod.SKILL_NAME}")
                else:
                    print(f"[SkillRegistry] Invalid skill format: {filename}")
            except Exception as e:
                print(f"[SkillRegistry] Error loading {filename}: {e}")

    def execute(self, command: str, context: dict) -> str | None:
        """
        Routes the command to the best matching skill using the IntentClassifier.
        Returns None if no skill matches.
        """
        from core.agent.intent_classifier import IntentClassifier
        classifier = IntentClassifier(self)
        
        skill_name = classifier.classify(command)
        
        if skill_name and skill_name in self.skills:
            mod = self.skills[skill_name]
            try:
                print(f"[SkillRegistry] Routing to: {mod.SKILL_NAME}")
                return mod.run(command, context)
            except Exception as e:
                print(f"[SkillRegistry] Skill {mod.SKILL_NAME} crashed: {e}")
                return f"Neural glitch detected in {mod.SKILL_NAME}. Error: {str(e)[:100]}"
                    
        return None # No matching skill

    def execute_fast(self, command: str, context: dict) -> str | None:
        """
        Zero-latency execution: only uses keyword triggers.
        """
        cmd = command.lower()
        for trigger, mod in self.triggers.items():
            if trigger in cmd:
                try:
                    print(f"[SkillRegistry-Fast] Routing to: {mod.SKILL_NAME}")
                    return mod.run(command, context)
                except Exception as e:
                    print(f"[SkillRegistry-Fast] Skill {mod.SKILL_NAME} crashed: {e}")
                    return None
        return None
