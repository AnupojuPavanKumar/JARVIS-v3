# core/context/workflow.py — JARVIS WORKFLOW MEMORY
"""
Tracks workflow patterns: app sequences, session types, workspace habits.
Used to:
  - Suggest workspace restoration
  - Detect coding sessions
  - Understand daily rhythms
  - Provide continuity across sessions

No surveillance — just tracks app sequences and session metadata.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

_PATH = "memory/workflow_memory.json"
_MAX_HISTORY = 100


@dataclass
class WorkspaceSnapshot:
    """A point-in-time snapshot of open apps and workflow state."""
    timestamp: float
    apps: list[str]            # processes running
    workflow: str | None
    category: str              # dominant category
    session_type: str | None   # "coding", "browsing", "meeting", etc.
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "apps": self.apps,
            "workflow": self.workflow,
            "category": self.category,
            "session_type": self.session_type,
            "tags": self.tags,
        }


class WorkflowMemory:
    """
    Tracks app usage patterns and workspace snapshots.
    Persists to memory/workflow_memory.json.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._snapshots: list[WorkspaceSnapshot] = []
        self._app_seq: list[str] = []          # recent app sequence
        self._daily_counts: Counter = Counter()
        self._session_starts: dict[str, float] = {}
        self._current_session: Optional[str] = None
        self._load()

    # ── Snapshot recording ────────────────────────────────────────────────────

    def record_snapshot(self, apps: list[str], workflow: str | None, category: str):
        """Record a workspace snapshot when significant state change occurs."""
        cats = Counter()
        for a in apps:
            cats[_categorise(a)] += 1
        dominant = cats.most_common(1)[0][0] if cats else "other"

        session = self._infer_session_type(dominant, apps, workflow)

        snap = WorkspaceSnapshot(
            timestamp=time.time(),
            apps=list(apps),
            workflow=workflow,
            category=dominant,
            session_type=session,
        )
        with self._lock:
            self._snapshots.append(snap)
            if len(self._snapshots) > _MAX_HISTORY:
                self._snapshots = self._snapshots[-_MAX_HISTORY:]
            self._daily_counts[dominant] += 1

        self._save()

    def record_app_sequence(self, app: str):
        """Append app to sequence for pattern detection."""
        with self._lock:
            self._app_seq.append(app)
            if len(self._app_seq) > 50:
                self._app_seq = self._app_seq[-50:]
            # Detect session start
            if self._current_session is None:
                self._current_session = app
                self._session_starts[app] = time.time()
            elif self._current_session != app:
                # Session ended
                self._current_session = None

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_last_snapshot(self) -> Optional[WorkspaceSnapshot]:
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def get_recent_snapshots(self, n: int = 5) -> list[WorkspaceSnapshot]:
        with self._lock:
            return list(self._snapshots[-n:])

    def get_similar_snapshot(self, apps: list[str], threshold: float = 0.6) -> Optional[WorkspaceSnapshot]:
        """Find most recent snapshot with similar app set."""
        target_set = set(a.lower() for a in apps)
        with self._lock:
            for snap in reversed(self._snapshots):
                snap_set = set(a.lower() for a in snap.apps)
                if not snap_set:
                    continue
                overlap = len(target_set & snap_set)
                jaccard = overlap / len(target_set | snap_set)
                if jaccard >= threshold:
                    return snap
        return None

    def get_most_used_apps(self, since_hours: float = 8.0) -> list[tuple[str, int]]:
        """Return (app, count) sorted by usage in last N hours."""
        cutoff = time.time() - since_hours * 3600
        counts = Counter()
        with self._lock:
            for snap in self._snapshots:
                if snap.timestamp >= cutoff:
                    for app in snap.apps:
                        counts[app] += 1
        return counts.most_common(10)

    def should_restore_workspace(self, current_apps: list[str]) -> tuple[bool, str | None]:
        """Should we suggest workspace restoration?"""
        snap = self.get_similar_snapshot(current_apps, threshold=0.5)
        if snap and time.time() - snap.timestamp < 4 * 3600:  # within 4 hours
            return True, snap.session_type
        return False, None

    def get_daily_summary(self) -> dict:
        with self._lock:
            return {
                "dominant_category": self._daily_counts.most_common(1)[0][0] if self._daily_counts else "unknown",
                "total_snapshots": len(self._snapshots),
                "category_counts": dict(self._daily_counts),
            }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _infer_session_type(self, category: str, apps: list[str], workflow: str | None) -> str:
        if workflow:
            return workflow.replace("_session", "").replace("_research", "")
        app_set = set(a.lower() for a in apps)
        if "code" in str(app_set) or "pycharm" in str(app_set) or "terminal" in str(app_set):
            return "coding"
        if "chrome" in str(app_set) or "msedge" in str(app_set):
            return "browsing"
        if "zoom" in str(app_set) or "teams" in str(app_set):
            return "meeting"
        if "spotify" in str(app_set):
            return "media"
        return category

    # ── Persistence ─────────────────────────────────────────────────────────

    def _load(self):
        try:
            if os.path.exists(_PATH):
                with open(_PATH, "r") as f:
                    d = json.load(f)
                    self._snapshots = [
                        WorkspaceSnapshot(**s) for s in d.get("snapshots", [])
                        if "timestamp" in s
                    ]
                    today = time.strftime("%Y-%m-%d")
                    if d.get("date") == today:
                        self._daily_counts = Counter(d.get("daily_counts", {}))
        except Exception:
            pass

    def _save(self):
        try:
            os.makedirs(os.path.dirname(_PATH), exist_ok=True)
            with self._lock:
                with open(_PATH, "w") as f:
                    json.dump({
                        "date": time.strftime("%Y-%m-%d"),
                        "snapshots": [s.to_dict() for s in self._snapshots],
                        "daily_counts": dict(self._daily_counts),
                    }, f, indent=2)
        except Exception:
            pass


def _categorise(name: str) -> str:
    n = name.lower()
    if any(x in n for x in ["code", "pycharm", "idea", "sublime", "terminal", "powershell", "cmd"]):
        return "coding"
    if any(x in n for x in ["chrome", "msedge", "firefox", "brave"]):
        return "browser"
    if any(x in n for x in ["spotify", "vlc", "music"]):
        return "media"
    if any(x in n for x in ["slack", "discord", "teams", "zoom", "telegram"]):
        return "social"
    if any(x in n for x in ["figma", "photoshop", "illustrator"]):
        return "design"
    return "other"


_instance: Optional[WorkflowMemory] = None
_lock = threading.Lock()

def get_workflow_memory() -> WorkflowMemory:
    global _instance
    with _lock:
        if _instance is None:
            _instance = WorkflowMemory()
        return _instance