# core/auto_pusher.py — AUTOMATIC GIT PUSH ENGINE
# ──────────────────────────────────────────────────────────────────────────────
# Periodically checks for changes in the workspace and pushes to GitHub.
# Ensures the sovereign orchestrator's code is always backed up.
# ──────────────────────────────────────────────────────────────────────────────

import os
import time
import threading
import subprocess
from datetime import datetime

class AutoPusher:
    def __init__(self, interval_seconds=1800): # Default: 30 minutes
        self.interval = interval_seconds
        self.running = False
        self._thread = None
        self._stop_event = threading.Event()
        self.cwd = os.getcwd()

    def start(self):
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[AUTO-PUSH] Engine started (Interval: {self.interval}s)")

    def stop(self):
        self.running = False
        self._stop_event.set()   # unblocks the sleep immediately
        print("[AUTO-PUSH] Engine stopped.")

    def _loop(self):
        while self.running:
            try:
                self._check_and_push()
            except Exception as e:
                print(f"[AUTO-PUSH] Error: {e}")

            # Use event-based wait so stop() wakes us immediately
            self._stop_event.wait(timeout=self.interval)
            self._stop_event.clear()

    def _run(self, cmd: list, **kwargs):
        """Run git command safely using a list of args — no shell injection."""
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=self.cwd, **kwargs
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def _check_and_push(self):
        # 1. Check if it's a git repo
        if not os.path.exists(os.path.join(self.cwd, ".git")):
            return

        # 2. Check for changes
        rc, out, err = self._run(["git", "status", "--short"])
        if rc != 0:
            return

        if not out:
            # No local changes, but check if we are ahead of remote
            rc, out, err = self._run(["git", "status"])
            if "Your branch is ahead of" not in out:
                return
            print("[AUTO-PUSH] Branch is ahead. Pushing to remote...")
        else:
            print("[AUTO-PUSH] Local changes detected. Committing and pushing...")
            # 3. Add and commit
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._run(["git", "add", "-A"])
            self._run(["git", "commit", "--message", f"JARVIS: auto-save {timestamp}"])

        # 4. Push — detect branch safely
        rc, branch, err = self._run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if rc != 0 or not branch or branch == "HEAD":
            branch = "main"

        rc, out, err = self._run(["git", "push", "origin", branch])
        if rc == 0:
            print(f"[AUTO-PUSH] Successfully pushed at {datetime.now().strftime('%H:%M:%S')}")
        else:
            print(f"[AUTO-PUSH] Push failed: {err}")

_pusher = None

def get_auto_pusher(interval=1800):
    global _pusher
    if _pusher is None:
        _pusher = AutoPusher(interval)
    return _pusher
