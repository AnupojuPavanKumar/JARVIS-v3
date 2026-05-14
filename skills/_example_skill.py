# skills/_example_skill.py — EXAMPLE JARVIS SKILL
# Copy this file, rename it, fill it in. JARVIS auto-loads anything in skills/

SKILL_NAME  = "example"
TRIGGERS    = ["example", "demo skill", "test plugin"]
DESCRIPTION = "Example skill — replace with your own logic"


def run(command: str, context: dict) -> str:
    """
    command: the raw user voice/text command
    context: dict with keys: mode, identity, last_action, hour
    Returns: str response spoken/displayed by JARVIS
    """
    return f"Example skill activated by: \'{command}\'"
