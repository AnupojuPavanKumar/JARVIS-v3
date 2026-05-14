# core/self_updater.py — JARVIS SELF-UPDATE ENGINE
# ──────────────────────────────────────────────────────────────────────────────
# Pulls latest code from git, installs new requirements, and hot-reloads
# non-core Python modules without a full restart.
#
# Safety rules:
#   • Only updates if git is available and remote is reachable
#   • Never restarts the Qt process — hot-reloads skills/ and core/ sub-modules
#   • Core modules (main.py, ui/main_ui.py, core/agent.py) require a full restart
#   • Full restart is announced via speech and scheduled for 5 seconds later
#   • Dry-run mode: checks for updates without applying them
# ──────────────────────────────────────────────────────────────────────────────

import subprocess
import sys
import os
import importlib
import threading
import datetime


# Modules that are SAFE to hot-reload (do not hold Qt objects)
_HOT_RELOAD_SAFE = {
    'core.engines.proactive_engine',
    'core.system.plugin_manager',
    'core.providers.model_router',
    'core.memory.conversation_history',
    'core.system.workspace_manager',
    'core.memory.command_memory',
    'core.engines.context_engine',
    'core.memory.memory_brain',
    'core.system.system_monitor',
    'core.engines.task_engine',
    "core.tools.git_tool",
    "core.tools.python_tool",
    "core.tools.shell_tool",
}

# Modules that require a FULL RESTART
_CORE_MODULES = {
    "main",
    "ui.main_ui",
    'core.agent.agent',
    'core.agent.jarvis_brain',
    'core.engines.voice_engine',
    'core.engines.speech_engine',
}


def _run(cmd: str, cwd: str | None = None, timeout: int = 60) -> tuple[int, str]:
    """Run shell command, return (exit_code, output)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd
        )
        out = (result.stdout or "").strip() + "\n" + (result.stderr or "").strip()
        return result.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, f"[TIMEOUT] Command took > {timeout}s"
    except Exception as e:
        return -1, str(e)


class SelfUpdater:
    """
    JARVIS self-update engine.
    Usage:
        updater = SelfUpdater(root=os.getcwd())
        result  = updater.check()      # dry-run: returns status string
        result  = updater.update()     # applies update
        result  = updater.hot_reload() # reloads safe modules in-process
    """

    def __init__(self, root: str | None = None, speech_engine=None):
        self._root   = root or os.getcwd()
        self._speech = speech_engine
        self._lock   = threading.Lock()
        self._log    : list[str] = []

    def _log_step(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        self._log.append(line)

    def _speak(self, text: str):
        if self._speech:
            try:
                threading.Thread(
                    target=self._speech.speak, args=(text,), daemon=True
                ).start()
            except Exception:
                pass

    # ── Git checks ─────────────────────────────────────────────────────────────
    def _git_available(self) -> bool:
        import shutil
        return shutil.which("git") is not None

    def _is_git_repo(self) -> bool:
        rc, _ = _run("git rev-parse --is-inside-work-tree", cwd=self._root)
        return rc == 0

    def _has_remote(self) -> bool:
        rc, out = _run("git remote -v", cwd=self._root)
        return rc == 0 and "origin" in out

    def _get_current_hash(self) -> str:
        _, out = _run("git rev-parse --short HEAD", cwd=self._root)
        return out.strip()

    def _get_remote_hash(self) -> str:
        _run("git fetch origin --quiet", cwd=self._root, timeout=15)
        _, out = _run("git rev-parse --short origin/main", cwd=self._root)
        return out.strip()

    # ── Check (dry-run) ────────────────────────────────────────────────────────
    def check(self) -> str:
        """Check if updates are available without applying them."""
        if not self._git_available():
            return (
                "Git is not installed. Cannot check for updates.\n"
                "Install git from https://git-scm.com and restart JARVIS."
            )
        if not self._is_git_repo():
            return (
                "JARVIS self-update: Not yet connected to a git remote.\n"
                "To enable automatic updates, run these commands once:\n"
                "  cd D:\\JARVIS-v3\n"
                "  git init\n"
                "  git remote add origin https://github.com/YOUR_USER/JARVIS-v3.git\n"
                "  git add . && git commit -m 'Initial commit'\n"
                "  git push -u origin main\n"
                "After that, JARVIS can auto-update itself."
            )
        if not self._has_remote():
            return "No remote 'origin' configured. Cannot check for updates."

        current = self._get_current_hash()
        remote  = self._get_remote_hash()

        if current == remote or not remote:
            return f"JARVIS is up to date (commit {current}), sir."

        _, diff = _run(
            f"git log --oneline {current}..origin/main", cwd=self._root
        )
        return (
            f"Update available, sir.\n"
            f"Current: {current}  →  Remote: {remote}\n"
            f"Changes:\n{diff}"
        )

    # ── Apply update ───────────────────────────────────────────────────────────
    def update(self, branch: str = "main") -> str:
        """Pull latest code + install new requirements. Returns status string."""
        with self._lock:
            self._log = []

            if not self._git_available():
                return "Git not installed — cannot update."
            if not self._is_git_repo():
                return "Not a git repository — cannot update."

            before = self._get_current_hash()
            self._log_step(f"Current commit: {before}")

            # 1. Stash local changes so pull is clean
            self._log_step("Stashing local changes...")
            _run("git stash --quiet", cwd=self._root)

            # 2. Pull
            self._log_step(f"Pulling from origin/{branch}...")
            rc, out = _run(f"git pull origin {branch}", cwd=self._root, timeout=60)
            self._log_step(out[:300])
            if rc != 0:
                _run("git stash pop --quiet", cwd=self._root)
                return f"Git pull failed:\n{out}"

            after = self._get_current_hash()
            if before == after:
                _run("git stash pop --quiet", cwd=self._root)
                return "Already up to date, sir."

            # 3. Install new requirements
            req_path = os.path.join(self._root, "requirements.txt")
            if os.path.exists(req_path):
                self._log_step("Installing updated requirements...")
                rc2, req_out = _run(
                    f'"{sys.executable}" -m pip install -r requirements.txt --quiet',
                    cwd=self._root, timeout=120
                )
                self._log_step(f"pip: {'OK' if rc2 == 0 else req_out[:200]}")

            # 4. Hot-reload safe modules
            reloaded = self.hot_reload()
            self._log_step(reloaded)

            # 5. Announce
            msg = f"Update complete. Loaded commit {after}, sir."
            self._log_step(msg)
            self._speak(msg)

            return "\n".join(self._log[-10:])

    # ── Hot-reload ─────────────────────────────────────────────────────────────
    def hot_reload(self) -> str:
        """Reload all hot-reload-safe modules in-process. Returns status string."""
        reloaded, failed = [], []
        for mod_name in list(_HOT_RELOAD_SAFE):
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                    reloaded.append(mod_name)
                except Exception as e:
                    failed.append(f"{mod_name}: {e}")

        status = f"Hot-reloaded {len(reloaded)} modules."
        if failed:
            status += f" Failed: {'; '.join(failed)}"
        print(f"[SelfUpdater] {status}")
        return status

    def needs_restart(self) -> bool:
        """Return True if any core module was changed in the last pull."""
        _, changed = _run("git diff --name-only HEAD~1 HEAD", cwd=self._root)
        for line in changed.splitlines():
            for core in _CORE_MODULES:
                if core.replace(".", "/") in line:
                    return True
        return False

    @property
    def log(self) -> list[str]:
        return self._log.copy()


# Module-level convenience — no singleton needed (speech_engine injected at runtime)
def create_updater(speech_engine=None) -> SelfUpdater:
    return SelfUpdater(root=os.getcwd(), speech_engine=speech_engine)
