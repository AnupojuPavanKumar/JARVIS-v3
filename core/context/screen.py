# core/context/screen.py — JARVIS SCREEN CONTEXT (On-Demand Only)
"""
Lightweight on-demand screen context capture.
NEVER captures screenshots continuously.
User-triggered or command-triggered only.

Uses:
  - Win32 GetWindowText for active window title
  - optional OCR via Tesseract if installed (user must opt-in)
  - clipboard text when user says "summarize this"

Privacy: all local, no network, no storage of captures.
"""
from __future__ import annotations

import ctypes
import subprocess
import time
from dataclasses import dataclass

user32 = ctypes.windll.user32


@dataclass
class ScreenContext:
    """Lightweight snapshot of what's visible."""
    window_title: str
    app_name: str
    app_category: str
    timestamp: float
    text_sample: str = ""   # only if user opted in
    is_fullscreen: bool = False


class ScreenContextCapture:
    """
    On-demand screen context. Call capture() when user requests it.
    Does NOT continuously monitor.
    """

    _GAME_PROCESSES = {
        "steam", "steamwebhelper", "epicgameslauncher", "minecraft",
        "leagueclient", "valorant", "fortnite", "dota2",
    }

    def capture_now(self) -> ScreenContext:
        """Capture current active window context. No storage, no persistence."""
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return ScreenContext("", "", "unknown", time.time())

            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            PROCESS_Q = 0x1000
            proc_handle = ctypes.windll.kernel32.OpenProcess(PROCESS_Q, False, pid.value)
            app = ""
            if proc_handle:
                try:
                    buf = ctypes.create_unicode_buffer(260)
                    if ctypes.windll.psapi.GetModuleBaseNameW(proc_handle, None, buf, 260):
                        app = buf.value
                except Exception:
                    pass
                finally:
                    ctypes.windll.kernel32.CloseHandle(proc_handle)

            cat = _categorise_app(app)

            return ScreenContext(
                window_title=title,
                app_name=app,
                app_category=cat,
                timestamp=time.time(),
            )
        except Exception:
            return ScreenContext("", "", "unknown", time.time())

    def capture_with_clipboard(self) -> ScreenContext:
        """Capture context + clipboard text for contextual commands."""
        ctx = self.capture_now()
        ctx.text_sample = self._get_clipboard()
        return ctx

    def _get_clipboard(self) -> str:
        try:
            CF_UNICODE = 13
            if not user32.IsClipboardFormatAvailable(CF_UNICODE):
                return ""
            if not user32.OpenClipboard(None):
                return ""
            try:
                hMem = user32.GetClipboardData(CF_UNICODE)
                if hMem:
                    text = ctypes.c_wchar_p(hMem).value
                    return text or ""
            finally:
                user32.CloseClipboard()
        except Exception:
            pass
        return ""


# Minimal categorisation (mirrors workspace.py but standalone)
_APP_MAP = {
    "code": "coding", "code.exe": "coding", "pycharm": "coding", "idea": "coding",
    "sublime": "coding", "notepad++": "coding", "terminal": "coding",
    "powershell": "coding", "cmd": "coding", "jupyter": "coding",
    "chrome": "browser", "msedge": "browser", "firefox": "browser",
    "spotify": "media", "vlc": "media",
    "slack": "social", "discord": "social", "teams": "social",
    "zoom": "meeting",
    "code": "coding",
}

def _categorise_app(name: str) -> str:
    n = name.lower()
    for key, cat in _APP_MAP.items():
        if key in n:
            return cat
    return "other"


# Singleton
_capture: ScreenContextCapture | None = None

def get_screen_capture() -> ScreenContextCapture:
    global _capture
    if _capture is None:
        _capture = ScreenContextCapture()
    return _capture