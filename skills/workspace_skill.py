"""
skills/workspace_skill.py — Workspace Management Skill
======================================================
Provides JARVIS with the ability to manage the local project workspace.
Supports listing projects, creating new ones, and summarizing workspace health.
"""
from __future__ import annotations
import os
import shutil
from core.system.workspace_manager import get_workspace_manager

SKILL_NAME = "Workspace Skill"
DESCRIPTION = "Manages the local project workspace, projects, and directories."
TRIGGERS = [
    "list projects", "show projects", "what are my projects",
    "create project", "new project", "initialize project",
    "archive project", "delete project", "remove project",
    "workspace status", "workspace health", "analyze workspace"
]

def run(command: str, context: dict) -> str | None:
    cmd = command.lower()
    ws = get_workspace_manager()
    desktop_root = ws.desktop_root

    if any(p in cmd for p in ("list projects", "show projects", "what are my projects")):
        return _list_projects(desktop_root)
    
    if any(p in cmd for p in ("create project", "new project", "initialize project")):
        # Extract project name - naive approach
        name = command.split("project")[-1].strip() or "new-project"
        return _create_project(ws, name)

    if any(p in cmd for p in ("archive project", "delete project", "remove project")):
        name = command.split("project")[-1].strip()
        if not name: return "Please specify which project to archive, sir."
        return _archive_project(desktop_root, name)

    if any(p in cmd for p in ("workspace status", "workspace health", "analyze workspace")):
        return _workspace_status(desktop_root)

    return None

def _list_projects(root) -> str:
    try:
        items = os.listdir(root)
        projects = [i for i in items if os.path.isdir(os.path.join(root, i)) and not i.startswith(".")]
        if not projects:
            return "Your workspace is currently empty, sir."
        proj_list = "\n".join([f"• {p}" for p in projects])
        return f"I found {len(projects)} projects in your workspace:\n\n{proj_list}"
    except Exception as e:
        return f"Failed to list workspace projects: {e}"

def _create_project(ws, name) -> str:
    try:
        path = ws.create(name)
        return f"Project '{name}' has been initialized at {path}. Neural scaffolding ready."
    except Exception as e:
        return f"Failed to create project '{name}': {e}"

def _archive_project(root, name) -> str:
    try:
        src = os.path.join(root, name)
        if not os.path.exists(src):
            return f"Project '{name}' not found."
        archive_dir = os.path.join(root, "archived")
        os.makedirs(archive_dir, exist_ok=True)
        dst = os.path.join(archive_dir, name)
        shutil.move(src, dst)
        return f"Project '{name}' has been moved to archives."
    except Exception as e:
        return f"Failed to archive project: {e}"

def _workspace_status(root) -> str:
    try:
        total_size = 0
        count = 0
        for r, dirs, files in os.walk(root):
            if "venv" in r or ".git" in r: continue
            for f in files:
                fp = os.path.join(r, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
            count += len(dirs)
        size_mb = total_size / (1024 * 1024)
        return (f"Workspace Analysis:\n"
                f"• Active Projects: {count}\n"
                f"• Total Size: {size_mb:.2f} MB\n"
                f"• Location: {root}")
    except Exception as e:
        return f"Workspace analysis failed: {e}"
