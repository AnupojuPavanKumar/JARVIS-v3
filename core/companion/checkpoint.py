# core/companion/checkpoint.py — JARVIS STATE CHECKPOINTS
"""
Crash-safe state persistence.
Periodically snapshots JARVIS operational state so it can recover gracefully
after a crash, restart, or suspend/resume cycle.

Saved state (JSON, memory/checkpoint.json):
  - last_mode
  - last_app_context
  - recent_command_count
  - active_workflow
  - last_interaction
  - suggestion_cooldowns
  - session_id
  - uptime_at_shutdown

Loaded on startup to restore continuity.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from typing import Optional

_CHECKPOINT_PATH = "memory/checkpoint.json"
_COOLDOWN_PATH  = "memory/cooldowns.json"


@dataclass
class Checkpoint:
    session_id:    str
    last_mode:    str
    last_app:      str
    last_category: str
    workflow:      str
    last_interaction: float
    command_count: int
    suggestion_count: int
    uptime_s:     float
    created_at:   float

    def age(self) -> float:
        return time.time() - self.last_interaction

    def is_recent(self, max_age: float = 3600.0) -> bool:
        return self.age() < max_age


class CheckpointManager:
    """
    Saves and loads JARVIS state for session continuity.
    Thread-safe. Saves on significant events, not continuously.
    """

    def __init__(self):
        self._lock       = threading.RLock()
        self._session_id = f"{int(time.time())}"
        self._start_time = time.time()
        self._dirty      = False
        self._data: Checkpoint | None = None
        self._load()

    def _make_fresh(self) -> Checkpoint:
        return Checkpoint(
            session_id=self._session_id,
            last_mode="idle",
            last_app="",
            last_category="unknown",
            workflow=None,
            last_interaction=time.time(),
            command_count=0,
            suggestion_count=0,
            uptime_s=0.0,
            created_at=time.time(),
        )

    def _load(self):
        try:
            if os.path.exists(_CHECKPOINT_PATH):
                with open(_CHECKPOINT_PATH, "r") as f:
                    d = json.load(f)
                    self._data = Checkpoint(**d)
                    self._session_id = self._data.session_id
                    print(f"[Checkpoint] Loaded session {self._session_id}, "
                          f"last mode: {self._data.last_mode}")
        except Exception as e:
            print(f"[Checkpoint] Load error: {e}")
            self._data = self._make_fresh()

    def save(self, force: bool = False):
        """Persist checkpoint to disk. Only write if dirty."""
        if not force and not self._dirty:
            return
        with self._lock:
            if self._data is None:
                return
            self._data.uptime_s = time.time() - self._start_time
            self._data.last_interaction = time.time()
            try:
                os.makedirs(os.path.dirname(_CHECKPOINT_PATH), exist_ok=True)
                with open(_CHECKPOINT_PATH, "w") as f:
                    json.dump(asdict(self._data), f, indent=2)
                self._dirty = False
            except Exception as e:
                print(f"[Checkpoint] Save error: {e}")

    def update(self, **kwargs):
        """Update fields and mark dirty for next save."""
        with self._lock:
            if self._data is None:
                self._data = self._make_fresh()
            for k, v in kwargs.items():
                if hasattr(self._data, k):
                    setattr(self._data, k, v)
            self._dirty = True

    def record_command(self):
        with self._lock:
            if self._data:
                self._data.command_count += 1
                self._dirty = True
        self.save()

    def get_last_session(self) -> Optional[Checkpoint]:
        return self._data

    def get_recovery_context(self) -> dict:
        """Return context for resuming from a crash/restart."""
        with self._lock:
            if self._data is None:
                return {}
            d = self._data
            ctx = {
                "session_age": d.age(),
                "last_mode":   d.last_mode,
                "last_app":   d.last_app,
                "workflow":    d.workflow,
                "is_recent":   d.is_recent(),
                "commands":   d.command_count,
            }
        return ctx

    def should_restore_workflow(self) -> bool:
        """Suggest workflow restoration if session was recent and active."""
        ctx = self.get_recovery_context()
        if not ctx:
            return False
        return (
            ctx["is_recent"] and
            ctx["commands"] > 5 and
            ctx["workflow"] is not None
        )

    def new_session(self):
        """Start fresh — clear checkpoint."""
        with self._lock:
            self._session_id = f"{int(time.time())}"
            self._start_time = time.time()
            self._data = self._make_fresh()
            self._dirty = True
        self.save(force=True)

    def save_cooldown(self, key: str, until: float):
        """Persist a cooldown timestamp."""
        try:
            os.makedirs(os.path.dirname(_COOLDOWN_PATH), exist_ok=True)
            cooldowns = {}
            if os.path.exists(_COOLDOWN_PATH):
                with open(_COOLDOWN_PATH, "r") as f:
                    cooldowns = json.load(f)
            cooldowns[key] = until
            with open(_COOLDOWN_PATH, "w") as f:
                json.dump(cooldowns, f)
        except Exception:
            pass

    def get_cooldown(self, key: str) -> float:
        """Return remaining cooldown (0 if expired or absent)."""
        try:
            if os.path.exists(_COOLDOWN_PATH):
                with open(_COOLDOWN_PATH, "r") as f:
                    cooldowns = json.load(f)
                until = cooldowns.get(key, 0)
                return max(0.0, until - time.time())
        except Exception:
            pass
        return 0.0


_instance: Optional[CheckpointManager] = None
_lock = threading.Lock()

def get_checkpoint() -> CheckpointManager:
    global _instance
    with _lock:
        if _instance is None:
            _instance = CheckpointManager()
        return _instance