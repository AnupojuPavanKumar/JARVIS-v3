# core/plugin_manager.py — JARVIS PLUGIN / SKILL SYSTEM
# ──────────────────────────────────────────────────────────────────────────────
# Drop any .py file into skills/ and it auto-loads as a JARVIS plugin.
#
# Plugin contract:
#   • Module-level SKILL_NAME: str  — e.g. "weather"
#   • Module-level TRIGGERS: list[str]  — keywords that activate this skill
#   • Module-level run(command: str, context: dict) -> str  — returns response
#   • Optional DESCRIPTION: str  — shown in "list skills" HUD
#
# Example skill file (skills/weather_skill.py):
#   SKILL_NAME  = "weather"
#   TRIGGERS    = ["weather", "forecast", "temperature outside"]
#   DESCRIPTION = "Gets live weather for any city"
#   def run(command, context):
#       return "Checking weather..."
# ──────────────────────────────────────────────────────────────────────────────

import os
import sys
import importlib
import importlib.util
import threading
from typing import Callable


SKILLS_DIR = "skills"


class PluginManager:
    """
    Auto-discovers, loads, and dispatches to skill plugins.
    Thread-safe: plugins can be hot-reloaded at runtime.
    """

    def __init__(self, skills_dir: str = SKILLS_DIR):
        self._dir       = skills_dir
        self._skills    : dict[str, dict] = {}   # {name: {module, triggers, run, description}}
        self._lock      = threading.Lock()
        self._watcher   : threading.Thread | None = None
        self._watcher_stop = threading.Event()
        os.makedirs(self._dir, exist_ok=True)
        self._write_example_skill()
        self.scan_and_load()

    # ── Example skill scaffold ─────────────────────────────────────────────────
    def _write_example_skill(self):
        example = os.path.join(self._dir, "_example_skill.py")
        if not os.path.exists(example):
            with open(example, "w", encoding="utf-8") as f:
                f.write('''\
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
    return f"Example skill activated by: \\'{command}\\'"
''')

    # ── Discovery & Loading ────────────────────────────────────────────────────
    def scan_and_load(self):
        """Scan skills/ and load any new or changed .py files."""
        if not os.path.isdir(self._dir):
            return

        py_files = [
            f for f in os.listdir(self._dir)
            if f.endswith(".py") and not f.startswith("_") and not f.startswith(".")
        ]

        loaded, failed = 0, 0
        for fname in py_files:
            path = os.path.join(self._dir, fname)
            try:
                self._load_file(path)
                loaded += 1
            except Exception as e:
                print(f"[PluginManager] Failed to load {fname}: {e}")
                failed += 1

        print(f"[PluginManager] Loaded {loaded} skills, {failed} failed. "
              f"Active: {list(self._skills.keys())}")

    def _load_file(self, path: str):
        module_name = "skill__" + os.path.basename(path).replace(".py", "")
        spec   = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        name        = getattr(module, "SKILL_NAME",  module_name)
        triggers    = getattr(module, "TRIGGERS",    [])
        description = getattr(module, "DESCRIPTION", "")
        run_fn      = getattr(module, "run", None)

        if run_fn is None:
            raise ValueError(f"Skill '{name}' has no run() function.")
        if not callable(run_fn):
            raise ValueError(f"Skill '{name}'.run is not callable.")

        with self._lock:
            self._skills[name] = {
                "module":      module,
                "triggers":    [t.lower() for t in triggers],
                "run":         run_fn,
                "description": description,
                "path":        path,
            }

    def reload(self, skill_name: str) -> bool:
        """Hot-reload a specific skill by name."""
        with self._lock:
            skill = self._skills.get(skill_name)
        if not skill:
            return False
        try:
            self._load_file(skill["path"])
            print(f"[PluginManager] Reloaded: {skill_name}")
            return True
        except Exception as e:
            print(f"[PluginManager] Reload failed for {skill_name}: {e}")
            return False

    def reload_all(self):
        """Rescan and reload all skills."""
        self.scan_and_load()

    # ── File watcher ───────────────────────────────────────────────────────────
    def start_watcher(self, poll_interval: int = 5):
        """Watch skills/ for new or changed files and auto-reload."""
        if self._watcher and self._watcher.is_alive():
            return
        self._watcher_stop.clear()
        self._watcher = threading.Thread(
            target=self._watch_loop,
            args=(poll_interval,),
            daemon=True,
            name="SkillWatcher"
        )
        self._watcher.start()
        print("[PluginManager] File watcher started.")

    def stop_watcher(self):
        self._watcher_stop.set()

    def _watch_loop(self, interval: int):
        # Initialize mtimes so we don't reload everything on the first pass
        seen_mtimes : dict[str, float] = {}
        try:
            for fname in os.listdir(self._dir):
                if fname.endswith(".py") and not fname.startswith("_"):
                    path = os.path.join(self._dir, fname)
                    seen_mtimes[path] = os.path.getmtime(path)
        except Exception as e:
            print(f"[PluginManager] Init scan error: {e}")

        while not self._watcher_stop.is_set():
            try:
                for fname in os.listdir(self._dir):
                    if not fname.endswith(".py") or fname.startswith("_"):
                        continue
                    path  = os.path.join(self._dir, fname)
                    mtime = os.path.getmtime(path)
                    if seen_mtimes.get(path) != mtime:
                        seen_mtimes[path] = mtime
                        try:
                            self._load_file(path)
                            print(f"[PluginManager] Auto-reloaded: {fname}")
                        except Exception as e:
                            print(f"[PluginManager] Auto-reload error {fname}: {e}")
            except Exception as e:
                print(f"[PluginManager] Watch loop error: {e}")
            self._watcher_stop.wait(interval)

    # ── Dispatch ───────────────────────────────────────────────────────────────
    def dispatch(self, command: str, context: dict | None = None) -> str | None:
        """
        Check if any skill's triggers match command.
        Returns skill response or None if no match.
        """
        cmd_lower = command.lower()
        context   = context or {}

        with self._lock:
            skills = list(self._skills.values())

        for skill in skills:
            if any(trigger in cmd_lower for trigger in skill["triggers"]):
                try:
                    print(f"[PluginManager] Dispatching to skill: {skill.get('description', '')}")
                    return skill["run"](command, context)
                except Exception as e:
                    return f"[Skill error] {e}"
        return None

    # ── Info ───────────────────────────────────────────────────────────────────
    def list_skills(self) -> list[dict]:
        with self._lock:
            return [
                {"name": k, "triggers": v["triggers"], "description": v["description"]}
                for k, v in self._skills.items()
            ]

    def skill_count(self) -> int:
        return len(self._skills)


# Module singleton
_plugin_manager = PluginManager()


def get_plugin_manager() -> PluginManager:
    return _plugin_manager
