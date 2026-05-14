# skills/vision_skill.py — JARVIS VISION & OCR SKILL
# Native skill for screen reading and visual queries.

import os
import sys

# Ensure core module is in path if called oddly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.ui.screen_reader import get_screen_reader

SKILL_NAME  = "vision"
TRIGGERS    = ["read screen", "read my screen", "what is on my screen",
               "what's on my screen", "read the error", "describe screen"]
DESCRIPTION = "Reads and describes the active screen using OCR and Vision."


def run(command: str, context: dict) -> str:
    cmd = command.lower()
    sr = get_screen_reader()

    if "describe" in cmd:
        return sr.describe_screen()
    elif "error" in cmd or "active window" in cmd:
        return sr.read_active_window()
    else:
        return sr.read_screen()
