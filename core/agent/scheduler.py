# core/scheduler.py  —  JARVIS SCHEDULER (Natural Language Reminders + Recurring Tasks)
# ──────────────────────────────────────────────────────────────────────────────
# • "remind me in 20 minutes to check the server"
# • "remind me at 10pm to take a break"
# • "every day at 9am open my email"
# • "cancel reminder"  /  "list reminders"
# ──────────────────────────────────────────────────────────────────────────────

import threading
import time
import re
import datetime
import json
import os
from typing import Callable, Optional

# Module-level shutdown flag — set before interpreter teardown
_SHUTDOWN = False

def signal_shutdown():
    """Call from main.py before app.quit() to exit _poll immediately."""
    global _SHUTDOWN
    _SHUTDOWN = True


# ──────────────────────────────────────────────────────────────────────────────
# REMINDER STORE  (persists across restarts in memory/reminders.json)
# ──────────────────────────────────────────────────────────────────────────────
REMINDER_FILE = "memory/reminders.json"


class Reminder:
    _id_counter = 0

    def __init__(self, label: str, fire_at: float, recurring_sec: Optional[float] = None):
        Reminder._id_counter += 1
        self.id            = Reminder._id_counter
        self.label         = label
        self.fire_at       = fire_at        # unix timestamp
        self.recurring_sec = recurring_sec  # None = one-shot
        self.fired         = False

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "fire_at": self.fire_at,
            "recurring_sec": self.recurring_sec,
            "fired": self.fired,
        }

    @classmethod
    def from_dict(cls, d):
        r = cls.__new__(cls)
        r.id            = d["id"]
        r.label         = d["label"]
        r.fire_at       = d["fire_at"]
        r.recurring_sec = d.get("recurring_sec")
        r.fired         = d.get("fired", False)
        return r


# ──────────────────────────────────────────────────────────────────────────────
# NATURAL LANGUAGE PARSER
# ──────────────────────────────────────────────────────────────────────────────

_TIME_UNITS = {
    "second": 1, "seconds": 1, "sec": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600, "hr": 3600,
    "day": 86400, "days": 86400,
}

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _parse_time_expression(text: str):
    """
    Returns (fire_at_timestamp, recurring_sec, label).
    Supports:
      - "in 20 minutes to <label>"
      - "at 10pm to <label>"
      - "at 22:00 to <label>"
      - "every day at 9am <label>"
      - "every monday at 8am <label>"
    """
    text = text.lower().strip()
    now  = datetime.datetime.now()
    fire_at       = None
    recurring_sec = None
    label         = text  # fallback

    # ── Strip "remind me" prefix ──
    text = re.sub(r"^(remind me\s+|set (a\s+)?reminder\s+|set (a\s+)?timer\s+|timer\s+)", "", text).strip()

    # ── Extract label (after "to") ──
    to_match = re.search(r"\bto\b(.+)$", text)
    if to_match:
        label = to_match.group(1).strip()
        text  = text[:to_match.start()].strip()
    else:
        label = text  # use whole phrase

    # ── "in X units" ──────────────────────────────────────────
    m = re.search(r"(?:in|for)\s+(\d+)\s+(\w+)", text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        secs = _TIME_UNITS.get(unit)
        if secs:
            fire_at = now.timestamp() + n * secs
            return fire_at, None, label

    # ── "at HH:MM" or "at H am/pm" ────────────────────────────
    m = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if m:
        h  = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3)
        if meridiem == "pm" and h < 12: h += 12
        if meridiem == "am" and h == 12: h = 0
        target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)  # next occurrence

        # ── "every day at …" ───────────────────────────────────
        if "every day" in text or "daily" in text:
            recurring_sec = 86400
            fire_at = target.timestamp()
            return fire_at, recurring_sec, label

        # ── "every <weekday> at …" ─────────────────────────────
        for day_name, day_num in _WEEKDAYS.items():
            if day_name in text:
                days_ahead = (day_num - target.weekday()) % 7
                if days_ahead == 0 and target <= now:
                    days_ahead = 7
                target += datetime.timedelta(days=days_ahead)
                recurring_sec = 7 * 86400
                fire_at = target.timestamp()
                return fire_at, recurring_sec, label

        fire_at = target.timestamp()
        return fire_at, None, label

    return None, None, label


# ──────────────────────────────────────────────────────────────────────────────
# SCHEDULER SINGLETON
# ──────────────────────────────────────────────────────────────────────────────

class JarvisScheduler:
    """
    Lightweight scheduler. Runs a single background daemon thread that
    polls every second and fires callbacks when a reminder is due.
    Zero extra dependencies — uses only stdlib threading + datetime.
    """

    def __init__(self, speak_callback: Optional[Callable[[str], None]] = None):
        self._reminders: list[Reminder] = []
        self._lock      = threading.Lock()
        self._speak     = speak_callback or (lambda s: print(f"[SCHEDULER] {s}"))
        self._stop_evt  = threading.Event()   # set() to break poll loop immediately
        self._running   = False
        self._load()

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self):
        if not self._running:
            self._running = True
            self._stop_evt.clear()
            threading.Thread(target=self._poll, daemon=True, name="SchedulerThread").start()
            print("[Scheduler] Started — polling reminders every second.")

    def stop(self):
        self._running = False
        self._stop_evt.set()   # wake the sleeping poll loop immediately

    def add_from_text(self, text: str) -> str:
        """
        Parse a natural language reminder string and schedule it.
        Returns a human-readable confirmation or error string.
        """
        fire_at, recurring_sec, label = _parse_time_expression(text)
        if fire_at is None:
            return ("I couldn't understand that time, sir. Try: "
                    "'remind me in 20 minutes to check the server' or "
                    "'remind me at 10pm to take a break'.")

        r = Reminder(label, fire_at, recurring_sec)
        with self._lock:
            self._reminders.append(r)
        self._save()

        dt = datetime.datetime.fromtimestamp(fire_at)
        time_str = dt.strftime("%I:%M %p")
        if recurring_sec:
            recur = "daily" if recurring_sec == 86400 else "weekly"
            return f"Got it, sir. I'll remind you {recur} at {time_str}: \"{label}\"."
        delta_sec = int(fire_at - time.time())
        delta_min = delta_sec // 60
        if delta_min >= 60:
            delta_str = f"{delta_min // 60}h {delta_min % 60}m"
        elif delta_min > 0:
            delta_str = f"{delta_min} minute{'s' if delta_min != 1 else ''}"
        else:
            delta_str = f"{delta_sec} seconds"
        return f"Reminder set, sir. I'll alert you in {delta_str}: \"{label}\"."

    def list_reminders(self) -> str:
        with self._lock:
            active = [r for r in self._reminders if not r.fired or r.recurring_sec]
        if not active:
            return "No active reminders, sir."
        lines = []
        for r in active:
            dt  = datetime.datetime.fromtimestamp(r.fire_at)
            rec = " (recurring)" if r.recurring_sec else ""
            lines.append(f"  #{r.id} — {r.label!r} at {dt.strftime('%I:%M %p %d %b')}{rec}")
        return "Active reminders, sir:\n" + "\n".join(lines)

    def cancel_all(self) -> str:
        with self._lock:
            count = len(self._reminders)
            self._reminders.clear()
        self._save()
        return f"All {count} reminder(s) cancelled, sir." if count else "No reminders to cancel, sir."

    def cancel_id(self, rid: int) -> str:
        with self._lock:
            before = len(self._reminders)
            self._reminders = [r for r in self._reminders if r.id != rid]
            removed = before - len(self._reminders)
        self._save()
        return f"Reminder #{rid} cancelled, sir." if removed else f"No reminder #{rid} found."

    # ── Background poll ─────────────────────────────────────────────────────

    def _poll(self):
        while not _SHUTDOWN and self._running:
            try:
                waited = self._stop_evt.wait(timeout=1.0)
                if waited or _SHUTDOWN or not self._running:
                    break
            except Exception:
                break
            try:
                now = time.time()
                to_fire = []
                with self._lock:
                    for r in self._reminders:
                        if not r.fired and r.fire_at <= now:
                            to_fire.append(r)
                            if r.recurring_sec:
                                r.fire_at += r.recurring_sec
                            else:
                                r.fired = True
                    self._reminders = [r for r in self._reminders
                                       if not r.fired or r.recurring_sec]
                for r in to_fire:
                    msg = f"Sir, reminder: {r.label}."
                    print(f"[SCHEDULER] Firing: {msg}")
                    try:
                        if self._running and self._speak:
                            self._speak(msg)
                    except Exception as e:
                        print(f"[SCHEDULER] Speak error: {e}")
                if to_fire:
                    self._save()
            except Exception as e:
                print(f"[SCHEDULER] Poll error: {e}")


    # ── Persistence ─────────────────────────────────────────────────────────

    def _save(self):
        try:
            os.makedirs("memory", exist_ok=True)
            with self._lock:
                data = [r.to_dict() for r in self._reminders]
            with open(REMINDER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[SCHEDULER] Save error: {e}")

    def _load(self):
        try:
            if os.path.exists(REMINDER_FILE):
                with open(REMINDER_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                now = time.time()
                loaded = 0
                for d in data:
                    r = Reminder.from_dict(d)
                    # Skip fired one-shot reminders from previous sessions
                    if r.fired and not r.recurring_sec:
                        continue
                    # For recurring: fast-forward to next future occurrence
                    if r.recurring_sec:
                        while r.fire_at <= now:
                            r.fire_at += r.recurring_sec
                    self._reminders.append(r)
                    loaded += 1
                if loaded:
                    print(f"[Scheduler] Loaded {loaded} reminder(s) from disk.")
        except Exception as e:
            print(f"[SCHEDULER] Load error: {e}")

    def set_speak_callback(self, cb: Callable[[str], None]):
        self._speak = cb


# ── Singleton ────────────────────────────────────────────────────────────────
_scheduler: Optional[JarvisScheduler] = None

def get_scheduler(speak_cb=None) -> JarvisScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = JarvisScheduler(speak_cb)
    elif speak_cb and _scheduler._speak is None:
        _scheduler.set_speak_callback(speak_cb)
    return _scheduler
