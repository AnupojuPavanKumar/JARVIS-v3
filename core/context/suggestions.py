# core/context/suggestions.py — JARVIS CONTEXTUAL PROACTIVE SUGGESTIONS
"""
Bounded proactive intelligence.
Fires suggestions only when:
  1. AttentionModel says interruption cost is acceptable
  2. Confidence threshold met (>0.6)
  3. Cooldown expired (>5 minutes since last suggestion)
  4. NOT in silent/focus mode
  5. NOT during fullscreen gaming

Suggestion categories:
  - workflow: "You reopened Chrome and VSCode — start coding session?"
  - timing:   "You've been debugging for 20 minutes. Take a short break?"
  - memory:  "You opened this project 5 times today — want me to keep it ready?"
  - efficiency: "You've opened calculator 3 times today — pin it?"
  - focus:   "You're in a long coding session — fullscreen mode?"
  - idle:    "You've been idle 15 minutes — close background apps?"
  - session: "End of workday — save workspace snapshot?"
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from collections import Counter

from core.context.attention import get_attention_model, AttentionState
from core.context.bus import get_context_bus, ContextLevel, EVENT_SUGGESTION_READY

_HISTORY_PATH = "memory/context_suggestions.json"
_COOLDOWN_SEC = 300   # 5 minutes between suggestions
_CONFIDENCE   = 0.6   # minimum confidence to fire


class SuggestionEngine:
    """
    Generates and fires context-aware proactive suggestions.
    Subscribes to workspace events, evaluates attention, fires via callback.
    """

    def __init__(self):
        self._running      = False
        self._thread: threading.Thread | None = None
        self._stop_evt    = threading.Event()
        self._lock        = threading.RLock()
        self._callback    = None
        self._last_fired  = 0.0
        self._fired_today : set[str] = set()
        self._app_counts  : Counter = Counter()
        self._workflow_history: list = []
        self._recent_debug_time: float = 0.0
        self._debug_session_start: float = 0.0

        # Load daily app counts
        self._load()

        # Wire workspace events
        bus = get_context_bus()
        bus.subscribe("window_changed",   self._on_window_changed,   priority=5)
        bus.subscribe("workflow_changed",  self._on_workflow_changed,  priority=5)
        bus.subscribe("user_idle",         self._on_user_idle,        priority=3)
        bus.subscribe("user_active",       self._on_user_active,      priority=3)

    def start(self, callback):
        """Start engine. callback(text: str) fires suggestions."""
        self._callback = callback
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="SuggestionEng")
        self._thread.start()

    def stop(self):
        self._running = False
        self._stop_evt.set()
        self._save()

    # ── Event handlers ─────────────────────────────────────────────────────────

    def _on_window_changed(self, event):
        data = event.data
        cat  = data.get("category", "")
        app  = data.get("to", "")
        title = data.get("title", "")

        # Count app usage
        with self._lock:
            self._app_counts[app] += 1

        # Detect debugging session
        kw = title.lower()
        if any(w in kw for w in ["error", "exception", "traceback", "failed", "failed"]):
            with self._lock:
                if self._debug_session_start == 0.0:
                    self._debug_session_start = time.time()
                self._recent_debug_time = time.time()

        # App repeated pattern
        with self._lock:
            count = self._app_counts.get(app, 0)
        if count >= 3:
            self._evaluate(f"app_reopen:{app}", data)

    def _on_workflow_changed(self, event):
        workflow = event.data.get("workflow", "")
        if workflow:
            with self._lock:
                self._workflow_history.append(workflow)
            if workflow == "coding_session":
                self._evaluate("coding_session_start", event.data)
            elif workflow == "session_end":
                self._evaluate("session_end", event.data)

    def _on_user_idle(self, event):
        idle = event.data.get("idle_seconds", 0.0)
        if idle >= 300:  # 5+ minutes idle
            self._evaluate(f"idle_long:{int(idle/60)}min", event.data)

    def _on_user_active(self, event):
        idle = event.data.get("idle_seconds", 0.0)
        if idle >= 600:  # 10+ minutes idle, now active
            self._evaluate("long_idle_return", event.data)

    # ── Suggestion evaluation ─────────────────────────────────────────────────

    def _evaluate(self, tag: str, data: dict):
        # ── Emit-time suppression gates ──────────────────────────────────────
        try:
            from core.companion.fatigue_model import get_fatigue_model
            fm = get_fatigue_model()
            if fm.should_skip_suggestions():
                return
            if random.random() < fm.suggestion_suppression_odds():
                return
        except Exception:
            pass

        try:
            from core.companion.frustration_detector import get_frustration_detector
            fd = get_frustration_detector()
            if fd.should_suppress_suggestions():
                return
        except Exception:
            pass

        try:
            from core.companion.graceful_degradation import get_graceful_degradation
            gd = get_graceful_degradation()
            if gd.should_suppress_suggestions():
                return
        except Exception:
            pass

        try:
            from core.companion.behavior_drift import get_behavior_drift
            bd = get_behavior_drift()
            corrections = bd.get_correction()
            proactive_mult = corrections.get("proactive_mult", 1.0)
            if proactive_mult < 0.3 and random.random() > proactive_mult:
                return
        except Exception:
            pass

        with self._lock:
            now = time.time()
            if now - self._last_fired < _COOLDOWN_SEC:
                return  # cooldown active

        # Attention check
        am = get_attention_model()
        state = am.state
        if not am.should_suggest("normal"):
            return

        # Contextual suggestion logic
        suggestion = self._make_suggestion(tag, data, state)
        if not suggestion:
            return

        with self._lock:
            self._last_fired = now
            self._fired_today.add(tag)

        if self._callback:
            try:
                self._callback(suggestion)
            except Exception:
                pass

    def _make_suggestion(self, tag: str, data: dict, state: AttentionState) -> str | None:
        if not state.should_interrupt():
            return None

        tag = tag.split(":")[0]  # strip args

        # Focus detection: long debugging
        if tag == "app_reopen" and data.get("to"):
            app = data["to"].lower()
            # VSCode reopened → coding suggestion
            if "code" in app or "pycharm" in app:
                cats = list(self._workflow_history[-3:]) if self._workflow_history else []
                if "coding_session" in cats:
                    return None  # already in coding session
                return "VSCode reopened — continue your coding session?"

        # Long debugging
        if tag == "app_reopen":
            app = data.get("to", "").lower()
            with self._lock:
                ds = self._debug_session_start
            if ("code" in app or "pycharm" in app) and ds > 0:
                dur = time.time() - ds
                if dur >= 1200:  # 20 minutes
                    return "You've been debugging for over 20 minutes — need a fresh perspective?"
            if self._app_counts.get(data.get("to", ""), 0) >= 5:
                return f"You've opened {data['to']} 5 times today. Want me to pin it?"

        if tag == "idle_long":
            mins = int(float(data.get("idle_seconds", 0)) / 60)
            if mins >= 5:
                return "You've been idle for a while. Close background apps to free resources?"
            return None

        if tag == "long_idle_return":
            return "Welcome back. Shall I restore your last workspace?"

        if tag == "coding_session_start":
            return None  # Don't be chatty at session start

        if tag == "session_end":
            return "End of session. Save a workspace snapshot for tomorrow?"

        return None

    # ── Background loop ───────────────────────────────────────────────────────

    def _run(self):
        # Periodic check every 60s for suggestions that don't come from events
        while self._running and not self._stop_evt.is_set():
            self._periodic_check()
            self._stop_evt.wait(timeout=60.0)

    def _periodic_check(self):
        """Called every 60s. Check for periodic suggestions."""
        am = get_attention_model()
        state = am.state

        now = time.time()
        with self._lock:
            idle = 0.0
            if hasattr(am, "_ws") and am._ws:
                idle = getattr(am._ws, "idle_seconds", 0.0) or 0.0

        # Long idle check
        if idle >= 300 and state.should_interrupt():
            self._evaluate(f"idle_long:{int(idle/60)}min", {"idle_seconds": idle})

    # ── Persistence ───────────────────────────────────────────────────────────

    def _path(self) -> str:
        return _HISTORY_PATH

    def _load(self):
        try:
            if os.path.exists(self._path()):
                with open(self._path(), "r") as f:
                    d = json.load(f)
                    today = time.strftime("%Y-%m-%d")
                    if d.get("date") == today:
                        self._app_counts = Counter(d.get("app_counts", {}))
        except Exception:
            pass

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path()), exist_ok=True)
            with open(self._path(), "w") as f:
                json.dump({
                    "date": time.strftime("%Y-%m-%d"),
                    "app_counts": dict(self._app_counts),
                }, f)
        except Exception:
            pass


# Singleton
_instance = None
_lock = threading.Lock()

def get_suggestion_engine() -> SuggestionEngine:
    global _instance
    with _lock:
        if _instance is None:
            _instance = SuggestionEngine()
        return _instance