# core/proactive_engine.py — JARVIS PROACTIVE SUGGESTIONS ENGINE
# ──────────────────────────────────────────────────────────────────────────────
# Watches conversation history and time patterns to suggest actions BEFORE
# the user asks. Runs on a background timer, emits suggestions via callback.
#
# Suggestion triggers:
#   • Time-of-day routines (morning → "start your day?", night → "good night?")
#   • Repeat patterns ("you always open VSCode at 9am — shall I?")
#   • Last-command bursts ("you've searched 3 times — do you want to save this?")
#   • Idle detection (>10 min idle → "shall I close background apps?")
# ──────────────────────────────────────────────────────────────────────────────

import random
import threading
import datetime
import time
import json
import os
from collections import Counter

# Module-level shutdown flag — set before interpreter teardown
_SHUTDOWN = False

def signal_shutdown():
    """Call this from main.py before app.quit() to wake the loop immediately."""
    global _SHUTDOWN
    _SHUTDOWN = True


class ProactiveEngine:
    """
    Background engine that emits smart suggestions.
    Call start(callback) — callback(suggestion_text: str) fires on the Qt thread
    via a thread-safe mechanism (caller must marshal to UI if needed).
    """

    # ── Config ─────────────────────────────────────────────────────────────────
    _POLL_INTERVAL    = 60        # seconds between checks
    _IDLE_THRESHOLD   = 10 * 60  # seconds before "idle" suggestion
    _PATTERN_DAYS     = 7         # days of history to analyse
    _HISTORY_PATH     = "memory/proactive_patterns.json"

    # Time slots (hour ranges) → greeting tags
    _ROUTINES = {
        "morning":   (range(6, 10),   "Good morning, sir. Shall I activate Work Mode and open your usual apps?"),
        "lunch":     (range(12, 14),  "It's lunchtime, sir. Shall I pause all notifications?"),
        "evening":   (range(18, 20),  "Evening, sir. Want me to switch to Leisure Mode?"),
        "night":     (range(22, 25),  "It's getting late, sir. Shall I activate Night Mode?"),
    }

    # ── State ──────────────────────────────────────────────────────────────────
    def __init__(self, memory_brain=None):
        self._memory_brain   = memory_brain
        self._callback       = None
        self._thread         = None
        self._running        = False
        self._stop_evt       = threading.Event()
        self._last_activity  = time.time()
        self._last_command   = ""
        self._fired_today    : set[str] = set()
        self._patterns       = self._load_patterns()
        self._lock           = threading.Lock()

    # ── Persistence ────────────────────────────────────────────────────────────
    def _load_patterns(self) -> dict:
        try:
            if os.path.exists(self._HISTORY_PATH):
                with open(self._HISTORY_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"hourly_commands": {}, "command_freq": {}}

    def _save_patterns(self):
        try:
            os.makedirs(os.path.dirname(self._HISTORY_PATH), exist_ok=True)
            with self._lock:
                with open(self._HISTORY_PATH, "w", encoding="utf-8") as f:
                    json.dump(self._patterns, f, indent=2)
        except Exception as e:
            print(f"[Proactive] Save error: {e}")

    # ── Public API ─────────────────────────────────────────────────────────────
    def start(self, callback):
        """Start background suggestion loop. callback(text) called on matches."""
        self._callback = callback
        self._running  = True
        self._stop_evt.clear()
        self._thread   = threading.Thread(
            target=self._loop, daemon=True, name="ProactiveEngine"
        )
        self._thread.start()
        print("[Proactive] Engine started.")

    def stop(self):
        self._running = False
        self._stop_evt.set()   # wake immediately

    def record_command(self, command: str):
        """Call this after every user command to feed the pattern learner."""
        self._last_activity = time.time()
        self._last_command  = command
        hour = str(datetime.datetime.now().hour)

        with self._lock:
            # Track command frequency per hour
            hc = self._patterns.setdefault("hourly_commands", {})
            hc.setdefault(hour, [])
            hc[hour].append(command)
            hc[hour] = hc[hour][-200:]   # keep last 200 per hour

            # Overall frequency
            cf = self._patterns.setdefault("command_freq", {})
            cf[command] = cf.get(command, 0) + 1

        # Save periodically (every 10 commands)
        total = sum(self._patterns["command_freq"].values())
        if total % 10 == 0:
            self._save_patterns()

    # ── Suggestion loop ────────────────────────────────────────────────────────
    def _loop(self):
        from core.system.thread_manager import is_shutdown_requested
        while not _SHUTDOWN and not is_shutdown_requested() and self._running:
            try:
                waited = self._stop_evt.wait(timeout=self._POLL_INTERVAL)
                if waited or _SHUTDOWN or is_shutdown_requested() or not self._running:
                    break
            except Exception:
                break
            try:
                self._check_all()
            except Exception as e:
                print(f"[Proactive] Loop error: {e}")

    def _emit(self, suggestion: str, key: str):
        """Fire suggestion if not already fired today."""
        today = datetime.date.today().isoformat()
        fire_key = f"{today}:{key}"
        if fire_key in self._fired_today:
            return
        self._fired_today.add(fire_key)
        print(f"[Proactive] Suggesting: {suggestion}")
        if self._callback:
            try:
                self._callback(suggestion)
            except Exception as e:
                print(f"[Proactive] Callback error: {e}")

    def _check_all(self):
        import random

        # ── Global suppression gates ─────────────────────────────────────────
        try:
            from core.companion.fatigue_model import get_fatigue_model
            fm = get_fatigue_model()
            if fm.should_skip_suggestions():
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
            if gd.should_pause_proactive():
                return
        except Exception:
            pass

        try:
            from core.companion.behavior_drift import get_behavior_drift
            bd = get_behavior_drift()
            corrections = bd.get_correction()
            proactive_mult = corrections.get("proactive_mult", 1.0)
            if proactive_mult < 0.5 and random.random() > proactive_mult:
                return
        except Exception:
            pass

        now  = datetime.datetime.now()
        hour = now.hour

        # 1. Time-of-day routines
        for tag, (hour_range, msg) in self._ROUTINES.items():
            if hour in hour_range:
                self._emit(msg, f"routine_{tag}")

        # 2. Idle detection
        idle_secs = time.time() - self._last_activity
        if idle_secs > self._IDLE_THRESHOLD:
            self._emit(
                "You've been idle for a while, sir. Shall I close background apps to free memory?",
                "idle_{}".format(now.strftime("%H"))
            )

        # 3. Repeat-command pattern (most common command at this hour)
        hour_str = str(hour)
        with self._lock:
            hour_cmds = self._patterns.get("hourly_commands", {}).get(hour_str, [])

        # Filter out garbage: URLs, single words, very short strings
        def _is_meaningful(cmd: str) -> bool:
            if not cmd or len(cmd) < 6: return False
            if cmd.startswith(("http", "www", "/")): return False
            if not any(c.isalpha() for c in cmd): return False
            return True

        hour_cmds = [c for c in hour_cmds if _is_meaningful(c)]

        if len(hour_cmds) >= 5:
            most_common = Counter(hour_cmds).most_common(1)[0][0]
            count = Counter(hour_cmds)[most_common]
            if count >= 5:   # raised from 3 to 5 to reduce noise
                self._emit(
                    f"You usually ask me to '{most_common}' around this time. Shall I do it now?",
                    f"pattern_{hour_str}_{most_common[:20]}"
                )

    def get_top_suggestions(self, n: int = 3) -> list[str]:
        """Return top-n most frequent commands as quick-access suggestions."""
        freq = self._patterns.get("command_freq", {})
        top  = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:n]
        return [cmd for cmd, _ in top]


# Module singleton
_proactive = ProactiveEngine()


def get_proactive_engine() -> ProactiveEngine:
    return _proactive
