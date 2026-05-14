# core/executor/system_executor.py — System Executor Plugin
"""Handles SYSTEM_CONTROL operations (lock, sleep, restart, shutdown)."""

import ctypes
import subprocess
import logging

log = logging.getLogger("SystemExecutor")


class SystemExecutor:
    """System-level operations — lock, sleep, restart, shutdown."""

    def control(self, action: str) -> tuple[bool, str]:
        try:
            if action == "lock":
                ctypes.windll.user32.LockWorkStation()
                return True, "Locking workstation, sir."

            elif action in ("sleep", "hibernate"):
                ctypes.windll.PowrProf.SetSuspendStateState(0, 1, 0)
                return True, "Entering sleep mode, sir."

            elif action == "restart":
                subprocess.run(
                    ["shutdown", "/r", "/t", "30", "/c", "JARVIS restart in 30 seconds."],
                    capture_output=True, timeout=5,
                )
                return True, "Restarting in 30 seconds, sir."

            elif action == "shutdown":
                subprocess.run(
                    ["shutdown", "/s", "/t", "30", "/c", "JARVIS shutdown in 30 seconds."],
                    capture_output=True, timeout=5,
                )
                return True, "Shutting down in 30 seconds, sir."

            elif action == "logoff":
                ctypes.windll.user32.ExitWindowsEx(0, 0)
                return True, "Logging off, sir."

            elif action == "cancel_restart":
                subprocess.run(
                    ["shutdown", "/a"],
                    capture_output=True, timeout=3,
                )
                return True, "Restart cancelled, sir."

            else:
                return False, f"Unknown system action: '{action}'"

        except Exception as e:
            log.warning(f"[SystemExecutor] Error: {e}")
            return False, f"System control failed: {e}"