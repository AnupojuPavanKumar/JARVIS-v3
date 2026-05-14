# core/executor/window_executor.py — Window Executor Plugin
"""Handles WINDOW_CONTROL operations (minimize, maximize, close, new tab, switch)."""

import ctypes
import logging

log = logging.getLogger("WindowExecutor")

SW_MINIMIZE   = 6
SW_MAXIMIZE   = 3
SW_RESTORE    = 9
WM_CLOSE      = 0x0010


class WindowExecutor:
    """Window management via Win32 API."""

    def control(self, action: str) -> tuple[bool, str]:
        try:
            user32 = ctypes.windll.user32
            win = user32.GetForegroundWindow()

            if action == "minimize":
                user32.ShowWindow(win, SW_MINIMIZE)
                return True, "Window minimized, sir."

            elif action in ("maximize", "restore"):
                user32.ShowWindow(win, SW_MAXIMIZE)
                return True, "Window maximized, sir."

            elif action == "close":
                user32.PostMessageW(win, WM_CLOSE, 0, 0)
                return True, "Window closed, sir."

            elif action == "new_tab":
                user32.keybd_event(0x11, 0, 0, 0)  # Ctrl
                user32.keybd_event(0x54, 0, 0, 0)   # T
                user32.keybd_event(0x54, 0, 2, 0)
                user32.keybd_event(0x11, 0, 2, 0)
                return True, "New tab opened, sir."

            elif action == "switch":
                user32.keybd_event(0x11, 0, 0, 0)  # Alt
                user32.keybd_event(0x09, 0, 0, 0)   # Tab
                user32.keybd_event(0x09, 0, 2, 0)
                user32.keybd_event(0x11, 0, 2, 0)
                return True, "Switching window, sir."

            elif action == "close_tab":
                user32.keybd_event(0x11, 0, 0, 0)  # Ctrl
                user32.keybd_event(0x57, 0, 0, 0)   # W
                user32.keybd_event(0x57, 0, 2, 0)
                user32.keybd_event(0x11, 0, 2, 0)
                return True, "Tab closed, sir."

            else:
                return False, f"Unknown window action: '{action}'"

        except Exception as e:
            log.warning(f"[WindowExecutor] Error: {e}")
            return False, f"Window control failed: {e}"