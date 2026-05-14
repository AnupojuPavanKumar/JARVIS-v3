from __future__ import annotations

from core.api.skill_registry import SkillRegistry


class CommandEngine:
    """Legacy command facade kept for diagnostics and older callers."""

    def __init__(self, identity: str = "owner", ui=None):
        self.identity = identity
        self.ui = ui
        self.skill_registry = SkillRegistry()
        try:
            from core.api.app_scanner import AppScanner
            self.app_scanner = AppScanner()
        except Exception:
            self.app_scanner = None

    def execute(self, command: str) -> str:
        cmd = (command or "").strip()
        lowered = cmd.lower()
        if not cmd:
            return ""
        if "who are you" in lowered:
            return "I am JARVIS, your local assistant runtime."

        result = self.skill_registry.execute_fast(
            cmd,
            {"identity": self.identity, "user_name": "Sir"},
        )
        if result:
            return result
        return "Command acknowledged, sir."
