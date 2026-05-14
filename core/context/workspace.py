# core/context/workspace.py — JARVIS WORKSPACE INTELLIGENCE
"""
Lightweight workspace observer.
Tracks active window, app transitions, and infers current workflow context.
All local, no network, no storage of screenshots.

App categories (deterministic):
  coding:    VSCode, JetBrains, Terminal, PyCharm, Sublime, VSCodium
  browser:   Chrome, Firefox, Edge, Brave
  media:     Spotify, VLC, YouTube, Netflix, Discord
  social:    Slack, Teams, Telegram, WhatsApp
  design:    Figma, Photoshop, Illustrator, Affinity
  game:      fullscreen + known game processes
  meeting:   Zoom, Teams, Google Meet, Discord (call active)
  reading:   PDF readers, Kindle, Obsidian, Notion
"""
from __future__ import annotations

import ctypes
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

# ── Win32 ─────────────────────────────────────────────────────────────────────
user32 = ctypes.windll.user32

@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    pid: int
    timestamp: float = field(default_factory=time.time)
    is_fullscreen: bool = False

@dataclass
class AppTransition:
    from_app: str
    to_app: str
    timestamp: float
    session_duration: float  # seconds spent in from_app

# ── App category registry ────────────────────────────────────────────────────
_APP_CATEGORIES: dict[str, list[str]] = {
    "coding":    ["code", "pycharm", "idea", "webstorm", "rider", "sublime", "vscodium", "notepad++", "terminal", "powershell", "cmd", "git-bash", "jupyter", "spyder"],
    "browser":    ["chrome", "firefox", "msedge", "brave", "opera", "vivaldi"],
    "media":     ["spotify", "vlc", "audacity", "music", "youtube", "netflix", "wmplayer", "groove", "iina"],
    "social":     ["slack", "teams", "discord", "telegram", "whatsapp", "signal", "zoom"],
    "design":     ["figma", "photoshop", "illustrator", "indesign", "affinity", "sketch", "canva"],
    "game":       ["steam", "epic", "gog", "minecraft", "league", "valorant", "fortnite", "dota", "csgo", "overwatch", "rust", "terraria"],
    "meeting":    ["zoom", "teams"],
    "reading":    ["foxit", "sumatra", "adobe", "kindle", "obsidian", "notion", "evernote", "onenote"],
    "office":     ["winword", "excel", "powerpnt", "outlook", "onenote"],
}

def _categorise(proc_name: str) -> str:
    p = proc_name.lower()
    for cat, names in _APP_CATEGORIES.items():
        if any(n in p for n in names):
            return cat
    return "other"

_GAME_PROCESSES = {
    "steam", "steamwebhelper", "epicgameslauncher", "minecraft",
    "leagueclient", "valorant", "fortnite", "dota2", "csgo", "overwatch2",
    "rust", "terraria", "gta5", "red dead", "elden ring",
}

_FULLSCREEN_EXE = {"steam", "steamwebhelper", "epicgameslauncher", "minecraft",
                   "leagueclient", "valorant", "fortnite", "dota2",
                   "csgo", "overwatch2", "rust", "terraria"}

# ── Workflow inference ─────────────────────────────────────────────────────────
_WORKFLOW_SEQUENCES: list[tuple[list[str], str]] = [
    (["browser", "coding", "coding"],   "coding_session"),
    (["coding", "browser", "coding"],  "coding_research"),
    (["social", "social", "other"],     "communication_session"),
    (["media", "other", "other"],      "background_music"),
    (["browser", "browser", "browser"],"research_session"),
    (["meeting", "meeting", "other"], "post_meeting"),
    (["coding", "other", "other"],     "session_end"),
]

def _infer_workflow(history: list[str]) -> str | None:
    if len(history) < 3:
        return None
    seq = history[-3:]
    for pattern, workflow in _WORKFLOW_SEQUENCES:
        if seq == pattern:
            return workflow
    return None


class WorkspaceObserver:
    """
    Monitors active window transitions and infers workflow context.
    Runs in a background thread with 2-second polling.
    Emits events via subscribers.
    """

    def __init__(self, poll_interval: float = 2.0):
        self._poll        = poll_interval
        self._running     = False
        self._thread: threading.Thread | None = None
        self._stop_evt    = threading.Event()
        self._lock        = threading.RLock()

        # State
        self._current: WindowInfo | None = None
        self._history: deque[str] = deque(maxlen=20)  # category history
        self._transitions: deque[AppTransition] = deque(maxlen=50)
        self._session_starts: dict[str, float] = {}  # app → enter timestamp

        # Computed
        self._current_workflow: str | None = None
        self._is_focused: bool = True   # user at keyboard
        self._is_idle: bool = False
        self._idle_since: float = 0.0
        self._last_input: float = time.time()

        # Activity tracking
        self._keystroke_count: int = 0
        self._keystroke_t0: float = time.time()
        self._typing_speed: float = 0.0  # chars/sec recent average

        # Subscribers: event_name → list of callbacks
        self._subscribers: dict[str, list[callable]] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        if self._running: return
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="WorkspaceObs")
        self._thread.start()

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def subscribe(self, event: str, callback: callable):
        with self._lock:
            if event not in self._subscribers:
                self._subscribers[event] = []
            if callback not in self._subscribers[event]:
                self._subscribers[event].append(callback)

    def unsubscribe(self, event: str, callback: callable):
        with self._lock:
            if event in self._subscribers:
                try: self._subscribers[event].remove(callback)
                except ValueError: pass

    def _emit(self, event: str, data):
        with self._lock:
            cbs = list(self._subscribers.get(event, []))
        for cb in cbs:
            try: cb(data)
            except Exception: pass

    @property
    def current_category(self) -> str:
        with self._lock:
            return _categorise(self._current.process_name) if self._current else "unknown"

    @property
    def current_app(self) -> str:
        with self._lock:
            return self._current.process_name if self._current else ""

    @property
    def current_window_title(self) -> str:
        with self._lock:
            return self._current.title if self._current else ""

    @property
    def workflow(self) -> str | None:
        with self._lock:
            return self._current_workflow

    @property
    def is_focused(self) -> bool:
        with self._lock:
            return self._is_focused

    @property
    def is_idle(self) -> bool:
        with self._lock:
            return self._is_idle

    @property
    def idle_seconds(self) -> float:
        with self._lock:
            return time.time() - self._idle_since if self._is_idle else 0.0

    @property
    def typing_speed(self) -> float:
        with self._lock:
            return self._typing_speed

    def get_recent_transitions(self, n: int = 10) -> list[AppTransition]:
        with self._lock:
            return list(self._transitions)[-n:]

    def get_context_summary(self) -> dict:
        """All current context in one dict — for brain, telemetry, UI."""
        with self._lock:
            return {
                "app":         self._current.process_name  if self._current else "",
                "category":    _categorise(self._current.process_name) if self._current else "unknown",
                "title":       self._current.title if self._current else "",
                "workflow":    self._current_workflow,
                "is_idle":     self._is_idle,
                "idle_secs":   time.time() - self._idle_since if self._is_idle else 0.0,
                "is_fullscreen": self._current.is_fullscreen if self._current else False,
                "category_history": list(self._history),
            }

    # ── Background loop ───────────────────────────────────────────────────────

    def _run(self):
        while self._running and not self._stop_evt.is_set():
            try:
                self._tick()
            except Exception:
                pass
            self._stop_evt.wait(timeout=self._poll)

    def _tick(self):
        new_win = self._poll_window()
        changed = False

        with self._lock:
            if new_win is None:
                return

            prev = self._current
            self._current = new_win

            if prev is None or prev.process_name != new_win.process_name:
                changed = True
                prev_cat = _categorise(prev.process_name) if prev else "none"
                new_cat = _categorise(new_win.process_name)

                # Record transition
                if prev:
                    prev_enter = self._session_starts.get(prev.process_name, prev.timestamp)
                    dur = time.time() - prev_enter
                    self._transitions.append(AppTransition(
                        from_app=prev.process_name,
                        to_app=new_win.process_name,
                        timestamp=time.time(),
                        session_duration=dur,
                    ))

                self._session_starts[new_win.process_name] = time.time()
                self._history.append(new_cat)

                # Re-infer workflow
                self._current_workflow = _infer_workflow(list(self._history))

        if changed:
            self._emit("window_changed", {
                "from": prev.process_name if prev else "",
                "to":   new_win.process_name,
                "category": _categorise(new_win.process_name),
                "workflow": self._current_workflow,
                "title":    new_win.title,
            })

        # Idle detection
        self._update_idle()

    def _poll_window(self) -> WindowInfo | None:
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None

            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                title = ""
            else:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            # Process name
            PROCESS_QUERY_LIMITED = 0x1000
            proc_handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid.value)
            proc_name = ""
            if proc_handle:
                try:
                    buf = ctypes.create_unicode_buffer(260)
                    if ctypes.windll.psapi.GetModuleBaseNameW(proc_handle, None, buf, 260):
                        proc_name = buf.value
                except Exception:
                    pass
                finally:
                    ctypes.windll.kernel32.CloseHandle(proc_handle)

            # Fullscreen check
            is_fs = self._check_fullscreen(hwnd) if proc_name.lower() in _FULLSCREEN_EXE else False

            return WindowInfo(
                hwnd=hwnd, title=title, process_name=proc_name,
                pid=pid.value, is_fullscreen=is_fs,
            )
        except Exception:
            return None

    def _check_fullscreen(self, hwnd: int) -> bool:
        try:
            MONITOR_DEFAULTTONEAREST = 2
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", ctypes.c_ubyte * 16),
                    ("rcWork",    ctypes.c_ubyte * 16),
                    ("dwFlags",   wintypes.DWORD),
            ]
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(mi)):
                return bool(mi.dwFlags & 2)  # MONITORINFOF_PRIMARY
        except Exception:
            pass
        return False

    def _update_idle(self):
        now = time.time()
        idle_thresh = 60.0  # 60s = idle
        with self._lock:
            was_idle = self._is_idle
            self._is_idle = (now - self._last_input) > idle_thresh
            if self._is_idle and not was_idle:
                self._idle_since = now
                self._emit("user_idle", {"idle_seconds": 0.0})
            elif not self._is_idle and was_idle:
                self._emit("user_active", {"idle_seconds": now - self._idle_since})
                self._idle_since = 0.0

    def record_activity(self):
        """Call from keyboard/mouse event hooks when user is active."""
        with self._lock:
            self._last_input = time.time()
            self._is_idle = False


# Module singleton
_instance: WorkspaceObserver | None = None
_instance_lock = threading.Lock()


def get_workspace_observer() -> WorkspaceObserver:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = WorkspaceObserver()
            _instance.start()
    return _instance