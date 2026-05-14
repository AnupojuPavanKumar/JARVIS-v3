# core/workspace_manager.py — JARVIS WORKSPACE ISOLATION
# ──────────────────────────────────────────────────────────────────────────────
# Every agent-built project gets its OWN isolated directory under ~/Desktop/JARVIS_Projects/
# This prevents agents from accidentally writing into the JARVIS source tree.
#
# Usage:
#   from core.system.workspace_manager import WorkspaceManager
#   ws = WorkspaceManager()
#   path = ws.create("portfolio_site")   # → C:/Users/.../Desktop/JARVIS_Projects/portfolio_site_20260418_143022/
#   ws.list_active()                      # → list of active workspaces
# ──────────────────────────────────────────────────────────────────────────────

import os
import datetime
import json
import threading
import shutil


class WorkspaceManager:
    """
    Creates and tracks isolated project workspaces outside the JARVIS system directory.
    Thread-safe: can be called from the agent worker thread.
    """

    _BASE = os.path.join(os.path.expanduser("~"), "Desktop", "JARVIS_Projects")
    _REGISTRY = os.path.join(os.path.expanduser("~"), "Desktop", "JARVIS_Projects", ".registry.json")
    _lock = threading.Lock()

    def __init__(self):
        os.makedirs(self._BASE, exist_ok=True)
        with self._lock:
            if not os.path.exists(self._REGISTRY):
                self._save_registry({})

    # ── Registry helpers ───────────────────────────────────────────────────────
    def _load_registry(self) -> dict:
        try:
            with open(self._REGISTRY, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_registry(self, data: dict):
        try:
            with open(self._REGISTRY, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[WorkspaceManager] Registry save error: {e}")

    # ── Public API ─────────────────────────────────────────────────────────────
    def create(self, task_name: str) -> str:
        """
        Create a new isolated workspace for a task.
        Returns the absolute path to the workspace directory.
        """
        # Sanitize task name for use as a directory name
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in task_name)
        safe_name = safe_name.strip().replace(" ", "_")[:40]

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        ws_name = f"{safe_name}_{ts}"
        ws_path = os.path.join(self._BASE, ws_name)

        os.makedirs(ws_path, exist_ok=True)

        # Write a README.md so the agent knows context
        readme = (
            f"# JARVIS Project: {task_name}\n"
            f"Created: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"This workspace was created automatically by the JARVIS Autonomous Agent.\n"
        )
        try:
            with open(os.path.join(ws_path, "README.md"), "w", encoding="utf-8") as f:
                f.write(readme)
        except Exception:
            pass

        with self._lock:
            reg = self._load_registry()
            reg[ws_name] = {
                "task":    task_name,
                "path":    ws_path,
                "created": ts,
                "status":  "active"
            }
            self._save_registry(reg)

        print(f"[WorkspaceManager] Created workspace: {ws_path}")
        return ws_path

    def list_active(self) -> list[dict]:
        """Return all active workspaces."""
        with self._lock:
            reg = self._load_registry()
        return [v for v in reg.values() if v.get("status") == "active"]

    def complete(self, ws_path: str):
        """Mark a workspace as completed."""
        ws_name = os.path.basename(ws_path)
        with self._lock:
            reg = self._load_registry()
            if ws_name in reg:
                reg[ws_name]["status"] = "complete"
                self._save_registry(reg)

    def get_latest(self) -> str | None:
        """Return the path of the most recently created workspace."""
        active = self.list_active()
        if not active:
            return None
        return sorted(active, key=lambda x: x["created"], reverse=True)[0]["path"]

    def list_all(self) -> list[dict]:
        """Return all workspaces (active + archived + complete)."""
        with self._lock:
            reg = self._load_registry()
        return list(reg.values())

    def summary(self) -> str:
        """Human-readable summary of all projects — for 'list my projects' command."""
        all_ws = self.list_all()
        if not all_ws:
            return "No JARVIS projects found on the Desktop, sir."
        lines = [f"JARVIS Projects ({len(all_ws)} total):\n"]
        for ws in sorted(all_ws, key=lambda x: x["created"], reverse=True):
            status_icon = {"active": "🟢", "complete": "✅", "archived": "📦"}.get(ws["status"], "❓")
            lines.append(f"  {status_icon} [{ws['created']}] {ws['task']} — {ws['status']}")
        return "\n".join(lines)

    def cleanup(self, days_old: int = 7) -> str:
        """
        Archive workspaces older than `days_old` days.
        Moves them into JARVIS_Projects/_archive/ so the Desktop stays clean.
        Returns a plain-English summary of what was archived.
        """
        archive_dir = os.path.join(self._BASE, "_archive")
        os.makedirs(archive_dir, exist_ok=True)

        cutoff = datetime.datetime.now() - datetime.timedelta(days=days_old)
        archived = []

        with self._lock:
            reg = self._load_registry()
            for ws_name, info in list(reg.items()):
                if info.get("status") == "archived":
                    continue
                try:
                    created = datetime.datetime.strptime(info["created"], "%Y%m%d_%H%M%S")
                except Exception:
                    continue
                if created < cutoff:
                    src = info["path"]
                    dst = os.path.join(archive_dir, ws_name)
                    try:
                        if os.path.exists(src):
                            shutil.move(src, dst)
                            reg[ws_name]["status"] = "archived"
                            reg[ws_name]["archived_to"] = dst
                            archived.append(info["task"])
                    except Exception as e:
                        print(f"[WorkspaceManager] Archive error for {ws_name}: {e}")
            self._save_registry(reg)

        if not archived:
            return f"No projects older than {days_old} days to clean up, sir."
        return (f"Archived {len(archived)} old project(s) to _archive folder: "
                + ", ".join(archived[:5])
                + (f" and {len(archived)-5} more." if len(archived) > 5 else "."))

    def resolve_path(self, relative_or_absolute: str, task_ws: str | None = None) -> str:
        """
        Resolve a file path from the agent.
        - Absolute paths with C:\\Windows etc. are blocked by FileTool — no change.
        - Relative paths are anchored to the task workspace (not the JARVIS root).
        - If task_ws is None, anchors to the JARVIS system root (legacy behaviour).
        """
        if os.path.isabs(relative_or_absolute):
            return relative_or_absolute   # FileTool will guard system paths
        if task_ws:
            return os.path.join(task_ws, relative_or_absolute)
        return relative_or_absolute       # Legacy: relative to cwd


# Module-level singleton
_workspace_manager = WorkspaceManager()


def get_workspace_manager() -> WorkspaceManager:
    return _workspace_manager
