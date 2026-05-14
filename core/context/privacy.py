# core/context/privacy.py — JARVIS PRIVACY CONTROLS
"""
Privacy-first controls for all contextual intelligence.
User has full control over what context is captured and when.

Controls:
  - pause_context_capture(): pause all context events
  - resume_context_capture(): resume
  - is_paused(): check state
  - set_feature(name, enabled): per-feature toggle
  - get_status(): full privacy dashboard data
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from core.context.bus import get_context_bus

_ALL_FEATURES = [
    "workspace_tracking",   # active window monitoring
    "workflow_detection",   # app sequence + workflow inference
    "suggestions",          # proactive suggestions
    "idle_detection",       # idle/active state detection
    "screen_capture",       # on-demand screen context
    "clipboard_context",    # clipboard for contextual commands
]


@dataclass
class PrivacyStatus:
    is_paused: bool
    paused_features: set[str]
    session_start: float
    capture_count: int


class PrivacyControls:
    """
    Privacy control center for contextual intelligence.
    Thread-safe, persists settings to SystemDB.
    """

    def __init__(self):
        self._lock          = threading.RLock()
        self._global_pause  = False
        self._feature_state = {f: True for f in _ALL_FEATURES}
        self._session_start = time.time()
        self._capture_count = 0
        self._load()

    # ── Global pause ─────────────────────────────────────────────────────────

    def pause_all(self):
        """Globally pause all context capture (emergency stop)."""
        with self._lock:
            self._global_pause = True
        get_context_bus().pause_all()
        self._save()

    def resume_all(self):
        """Resume all context capture."""
        with self._lock:
            self._global_pause = False
        get_context_bus().resume_all()
        self._save()

    def is_paused(self) -> bool:
        with self._lock:
            return self._global_pause

    def toggle(self) -> bool:
        """Toggle global pause. Returns new state."""
        with self._lock:
            if self._global_pause:
                self.resume_all()
                return False
            else:
                self.pause_all()
                return True

    # ── Per-feature controls ─────────────────────────────────────────────────

    def set_feature(self, feature: str, enabled: bool):
        """Enable or disable a specific contextual feature."""
        if feature not in _ALL_FEATURES:
            return
        with self._lock:
            self._feature_state[feature] = enabled
        if feature == "suggestions":
            bus = get_context_bus()
            if enabled:
                bus.resume_event("suggestion_ready")
            else:
                bus.pause_event("suggestion_ready")
        self._save()

    def is_feature_enabled(self, feature: str) -> bool:
        with self._lock:
            return self._feature_state.get(feature, True)

    @property
    def enabled_features(self) -> list[str]:
        with self._lock:
            return [f for f, v in self._feature_state.items() if v]

    # ── Privacy dashboard data ───────────────────────────────────────────────

    def get_status(self) -> PrivacyStatus:
        with self._lock:
            return PrivacyStatus(
                is_paused=self._global_pause,
                paused_features=set(k for k, v in self._feature_state.items() if not v),
                session_start=self._session_start,
                capture_count=self._capture_count,
            )

    def record_capture(self):
        """Increment capture counter (called by context systems)."""
        with self._lock:
            self._capture_count += 1

    def reset_session(self):
        """Reset session counter and timestamp."""
        with self._lock:
            self._session_start = time.time()
            self._capture_count = 0

    # ── Persistence ─────────────────────────────────────────────────────────

    def _load(self):
        try:
            from core.system.db import get_db
            db = get_db()
            for feature in _ALL_FEATURES:
                v = db.get_setting(f"privacy_{feature}", None)
                if v is not None:
                    self._feature_state[feature] = v == "true"
            gp = db.get_setting("privacy_global_pause", "false")
            self._global_pause = gp == "true"
        except Exception:
            pass

    def _save(self):
        try:
            from core.system.db import get_db
            db = get_db()
            for feature, enabled in self._feature_state.items():
                db.set_setting(f"privacy_{feature}", str(enabled).lower())
            db.set_setting("privacy_global_pause", str(self._global_pause).lower())
        except Exception:
            pass


# Singleton
_instance: Optional[PrivacyControls] = None
_lock = threading.Lock()

def get_privacy_controls() -> PrivacyControls:
    global _instance
    with _lock:
        if _instance is None:
            _instance = PrivacyControls()
        return _instance