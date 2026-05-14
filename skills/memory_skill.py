SKILL_NAME = "Memory & Notes"
DESCRIPTION = "Saves and recalls personal notes and memories."
TRIGGERS = ["remember", "make a note", "note that", "save this", "recall", "my notes", "show memory", "clear memory", "forget everything"]

def run(command: str, context: dict) -> str | None:
    cmd = command.lower()
    brain = context.get("memory_brain")

    # FIX: Add proper None check for brain
    if brain is None:
        # Try to get brain from context alternative
        brain = getattr(context.get("brain", None), "memory_brain", None)

    if any(p in cmd for p in ("remember","make a note","note that","save this")):
        text = (cmd.replace("remember","").replace("make a note","")
                   .replace("note that","").replace("save this","").strip())
        if text:
            if brain and hasattr(brain, "save_memory"):
                brain.save_memory(text)
                return "Got it, sir. Memory stored."
            else:
                # Fallback: save to file directly
                return _save_memory_fallback(text)

    if any(p in cmd for p in ("what do you remember","recall","my notes","show memory")):
        if brain and hasattr(brain, "recall_memory"):
            return brain.recall_memory()
        else:
            return _recall_memory_fallback()

    if "clear memory" in cmd or "forget everything" in cmd:
        return _clear_memory()

    return None


def _save_memory_fallback(text: str) -> str:
    """Fallback if brain is not available."""
    try:
        import os
        os.makedirs("memory", exist_ok=True)
        with open("memory/memory.txt", "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"[{datetime.now().isoformat()}] {text}\n")
        return "Got it, sir. Memory stored."
    except Exception as e:
        return f"Could not save memory: {e}"


def _recall_memory_fallback() -> str:
    """Fallback if brain is not available."""
    try:
        import os
        path = "memory/memory.txt"
        if not os.path.exists(path):
            return "No memories stored yet, sir."
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return "No memories stored yet, sir."
        # Return last 5 memories
        recent = lines[-5:]
        return "Recent memories: " + " | ".join([l.strip() for l in recent])
    except Exception as e:
        return f"Could not recall memory: {e}"


def _clear_memory() -> str:
    """Clear all memories."""
    try:
        import os
        path = "memory/memory.txt"
        if os.path.exists(path):
            with open(path, "w") as f:
                pass
        return "Memory cleared, sir."
    except Exception:
        return "Could not clear memory, sir."
