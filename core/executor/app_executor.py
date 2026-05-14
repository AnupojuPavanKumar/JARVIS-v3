# core/executor/app_executor.py — App Executor Plugin
"""
Handles OPEN_APP and CLOSE_APP deterministically.
Safe shutdown flow (Stage 1 → Stage 2 → Stage 3).
App already-running detection.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
import ctypes
from typing import Optional

from core.executor.action import Action, ActionState
from core.executor.execution_safety import SafetyValidator, get_safety_validator
from core.apps.app_registry import get_app_registry

log = logging.getLogger("AppExecutor")

# Allowlist of safe apps — required for close operations
SAFE_CLOSE_ALLOWLIST = {
    "vscode", "code", "chrome", "firefox", "edge", "notepad",
    "notepad++", "notepadplusplus", "explorer", "file explorer",
    "discord", "spotify", "teams", "slack", "zoom",
    "powershell", "cmd", "terminal", "sublime", "pycharm",
    "intellij", "jupyter", "postman", "obsidian", "docker",
    "anaconda", "virtualbox",
}

# App → process name mapping for close operations
APP_PROCESS_MAP = {
    "vscode": "Code.exe",
    "code": "Code.exe",
    "visual studio code": "Code.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "notepad": "Notepad.exe",
    "notepad++": "notepad++.exe",
    "sublime": "sublime_text.exe",
    "sublime text": "sublime_text.exe",
    "pycharm": "pycharm64.exe",
    "intellij": "idea64.exe",
    "webstorm": "webstorm64.exe",
    "notepadplusplus": "notepad++.exe",
    "notepad plus plus": "notepad++.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "discord": "Discord.exe",
    "spotify": "Spotify.exe",
    "teams": "Teams.exe",
    "microsoft teams": "Teams.exe",
    "slack": "Slack.exe",
    "zoom": "Zoom.exe",
    "powershell": "powershell.exe",
    "pwsh": "pwsh.exe",
    "cmd": "cmd.exe",
    "terminal": "WindowsTerminal.exe",
    "windows terminal": "WindowsTerminal.exe",
    "anaconda": "AnacondaNavigator.exe",
    "jupyter": "jupyter.exe",
    "postman": "Postman.exe",
    "obsidian": "Obsidian.exe",
    "docker": "Docker Desktop.exe",
    "virtualbox": "VirtualBox.exe",
}

GRACEFUL_CLOSE_TIMEOUT = 3.0  # seconds to wait before force-killing


class AppExecutor:
    """Plugin executor for OPEN_APP and CLOSE_APP actions."""

    def __init__(self):
        self._registry = get_app_registry()
        self._safety = get_safety_validator()
        self._recent_launches: dict[str, float] = {}
        self._LAUNCH_COOLDOWN = 3.0

    # ── OPEN_APP ────────────────────────────────────────────────────────────────

    def open(self, action: Action) -> tuple[bool, str]:
        """Open an application by name/alias."""
        target = (action.target or "").strip().lower()
        if not target:
            return False, "No application specified."

        # Rate limit
        if not self._can_launch(target):
            return False, f"'{target}' was just launched. Please wait."

        # Pre-execution validation
        path = self._registry.resolve(target)
        if path:
            if not self._safety.validate_path(path):
                return False, f"Safety check failed for '{target}'."

        # Check if already running → focus instead of relaunch
        existing = self._get_running_process(target)
        if existing:
            log.info(f"[AppExecutor] {target} already running — focusing window.")
            self._focus_window(existing)
            self._mark_launched(target)
            return True, f"Switched to {target.title()}, sir."

        # Launch path found → subprocess
        if path and os.path.exists(path):
            return self._launch_executable(action, path, target)

        # No path → use Windows Start command
        return self._start_by_name(action, target)

    def _launch_executable(self, action: Action, path: str, target: str) -> tuple[bool, str]:
        try:
            creation_flags = 0x08000000 if os.name == "nt" else 0
            subprocess.Popen(
                [path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            self._mark_launched(target)
            log.info(f"[AppExecutor] Launched: {path}")
            return True, f"Opening {target.title()}, sir."
        except PermissionError:
            return False, f"Permission denied for '{target}'."
        except FileNotFoundError:
            return False, f"File not found: {path}"
        except Exception as e:
            log.warning(f"[AppExecutor] Launch error: {e}")
            return False, f"Failed to launch '{target}': {e}"

    def _start_by_name(self, action: Action, target: str) -> tuple[bool, str]:
        """Use Windows 'start' command for Start Menu apps."""
        try:
            escaped = target.replace("^", "^^").replace("&", "^&")
            subprocess.Popen(
                ["cmd", "/c", "start", "", escaped],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
            )
            self._mark_launched(target)
            return True, f"Opening {target.title()}, sir."
        except Exception as e:
            return False, f"Failed to open '{target}': {e}"

    # ── CLOSE_APP (Safe Shutdown Flow) ────────────────────────────────────────

    def close(self, action: Action) -> tuple[bool, str]:
        """Close an application using safe 3-stage shutdown."""
        target = (action.target or "").strip().lower()
        if not target:
            return False, "No application specified."

        # Allowlist check
        if target not in SAFE_CLOSE_ALLOWLIST:
            return False, f"'{target}' is not on the safe close list, sir. Use 'open' instead."

        proc_name = APP_PROCESS_MAP.get(target, f"{target}.exe")

        # Check if running at all
        if not self._is_process_running(proc_name):
            return False, f"'{target}' is not currently running."

        # ── Stage 1: Graceful WM_CLOSE ──────────────────────────────────────────
        log.info(f"[AppExecutor] Closing {target} (Stage 1: graceful)...")
        closed_gracefully = self._graceful_close(proc_name)

        if closed_gracefully:
            time.sleep(0.5)
            if not self._is_process_running(proc_name):
                log.info(f"[AppExecutor] {target} closed gracefully.")
                return True, f"Closed {target.title()}, sir."

        # ── Stage 2: Wait ───────────────────────────────────────────────────────
        log.info(f"[AppExecutor] Waiting {GRACEFUL_CLOSE_TIMEOUT}s for {target}...")
        time.sleep(GRACEFUL_CLOSE_TIMEOUT)

        if not self._is_process_running(proc_name):
            return True, f"Closed {target.title()}, sir."

        # ── Stage 3: Force terminate ──────────────────────────────────────────
        log.warning(f"[AppExecutor] Force terminating {proc_name} (Stage 3)...")
        try:
            subprocess.run(
                ["taskkill", "/f", "/im", proc_name],
                capture_output=True, timeout=5,
            )
            return True, f"Force-closed {target.title()}, sir."
        except Exception as e:
            return False, f"Failed to close '{target}': {e}"

    # ── Process utilities ──────────────────────────────────────────────────────

    def _is_process_running(self, proc_name: str) -> bool:
        try:
            result = subprocess.run(
                ["tasklist", "/fi", f"IMAGENAME eq {proc_name}"],
                capture_output=True, text=True, timeout=3,
            )
            return proc_name in result.stdout
        except Exception:
            return False

    def _graceful_close(self, proc_name: str) -> bool:
        """Send WM_CLOSE to a process window without killing it."""
        try:
            import ctypes
            user32 = ctypes.windll.user32

            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", ctypes.c_ulong),
                    ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.c_ulong),
                    ("th32ModuleID", ctypes.c_ulong),
                    ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_char * 260),
                ]

            TH32CS_SNAPPROCESS = 0x00000002

            kernel32 = ctypes.windll.kernel32
            snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snapshot == -1:
                return False

            pe = PROCESSENTRY32()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

            found_hwnd = None
            if kernel32.Process32FirstW(snapshot, ctypes.byref(pe)):
                while True:
                    exe = pe.szExeFile.decode("utf-8", errors="ignore").lower()
                    if exe == proc_name.lower():
                        pid = pe.th32ProcessID
                        hwnd = user32.FindWindowW(None, None)
                        while hwnd:
                            w_pid = ctypes.c_ulong()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
                            if w_pid.value == pid:
                                found_hwnd = hwnd
                                break
                            hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
                        break
                    if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
                        break

            kernel32.CloseHandle(snapshot)

            if found_hwnd:
                user32.PostMessageW(found_hwnd, 0x0010, 0, 0)  # WM_CLOSE
                return True

        except Exception as e:
            log.debug(f"[AppExecutor] Graceful close error: {e}")

        return False

    def _focus_window(self, hwnd: int):
        """Bring a window to foreground."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.SetForegroundWindow(hwnd)
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        except Exception:
            pass

    def _get_running_process(self, app_name: str) -> Optional[int]:
        """Return HWND of a running app, or None."""
        proc_name = APP_PROCESS_MAP.get(app_name, f"{app_name}.exe")
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong), ("th32DefaultHeapID", ctypes.c_ulong),
                    ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_char * 260),
                ]

            TH32CS_SNAPPROCESS = 0x00000002
            snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            pe = PROCESSENTRY32()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32)

            if kernel32.Process32FirstW(snapshot, ctypes.byref(pe)):
                while True:
                    exe = pe.szExeFile.decode("utf-8", errors="ignore").lower()
                    if exe == proc_name.lower():
                        pid = pe.th32ProcessID
                        kernel32.CloseHandle(snapshot)
                        hwnd = user32.FindWindowW(None, None)
                        while hwnd:
                            w_pid = ctypes.c_ulong()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
                            if w_pid.value == pid:
                                return hwnd
                            hwnd = user32.GetWindow(hwnd, 2)
                        return None
                    if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
                        break

            kernel32.CloseHandle(snapshot)
        except Exception:
            pass
        return None

    # ── Rate limiting ───────────────────────────────────────────────────────────

    def _can_launch(self, identifier: str) -> bool:
        now = time.time()
        last = self._recent_launches.get(identifier, 0)
        return now - last >= self._LAUNCH_COOLDOWN

    def _mark_launched(self, identifier: str):
        self._recent_launches[identifier] = time.time()


def get_app_executor() -> AppExecutor:
    return AppExecutor()