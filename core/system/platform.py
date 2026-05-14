"""
core/system/platform.py — Platform Abstraction Layer
=====================================================
Structure fix 2: decouples JARVIS from Windows-specific APIs.

PROBLEM:
  The codebase directly called winsound, ctypes.windll, and MessageBoxW
  in multiple places. On Linux/Mac (headless server, WSL, Docker) these
  imports raise ImportError or AttributeError at startup, making JARVIS
  unrunnable outside Windows.

SOLUTION:
  This module provides safe shims for every Windows-specific primitive.
  All callers import from here instead of calling the Windows API directly.

  On Windows: delegates to the real API.
  On Linux/Mac: uses a sensible no-op, subprocess, or logging fallback.

CAPABILITIES COVERED:
  - beep()               → winsound.Beep / no-op
  - play_sound()         → winsound.PlaySound / subprocess aplay
  - lock_workstation()   → LockWorkStation / xdg-screensaver
  - send_key()           → keybd_event / xdotool
  - is_windows()         → True/False
  - get_platform()       → "windows" | "linux" | "darwin"

USAGE:
  from core.system.platform import platform_shim as P
  P.beep(frequency=440, duration_ms=200)
  P.lock_workstation()
"""
from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from typing import Optional

log = logging.getLogger("PlatformShim")

_SYSTEM = platform.system().lower()   # "windows" | "linux" | "darwin"


def is_windows() -> bool:
    return _SYSTEM == "windows"


def is_linux() -> bool:
    return _SYSTEM == "linux"


def is_mac() -> bool:
    return _SYSTEM == "darwin"


def get_platform() -> str:
    return _SYSTEM


# ── Audio ─────────────────────────────────────────────────────────────────────

def beep(frequency: int = 800, duration_ms: int = 200):
    """Emit a system beep."""
    try:
        if is_windows():
            import winsound
            winsound.Beep(frequency, duration_ms)
        elif is_linux():
            # Use speaker-test or /dev/console bell (silent fallback)
            subprocess.run(
                ["bash", "-c", f"echo -e '\\a'"],
                timeout=1, capture_output=True
            )
        # macOS: afplay /System/Library/Sounds/Glass.aiff — skip for now
    except Exception as exc:
        log.debug(f"[Platform] beep() skipped: {exc}")


def play_sound(file_path: str):
    """Play an audio file using the platform's default player."""
    try:
        if is_windows():
            import winsound
            winsound.PlaySound(file_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        elif is_linux():
            subprocess.Popen(["aplay", file_path], stderr=subprocess.DEVNULL)
        elif is_mac():
            subprocess.Popen(["afplay", file_path], stderr=subprocess.DEVNULL)
    except Exception as exc:
        log.debug(f"[Platform] play_sound() skipped: {exc}")


# ── System Actions ────────────────────────────────────────────────────────────

def lock_workstation():
    """Lock the user session."""
    try:
        if is_windows():
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        elif is_linux():
            subprocess.run(["xdg-screensaver", "lock"], check=False)
        elif is_mac():
            subprocess.run([
                "osascript", "-e",
                'tell application "System Events" to keystroke "q" '
                'using {control down, command down}'
            ], check=False)
    except Exception as exc:
        log.warning(f"[Platform] lock_workstation() failed: {exc}")


def send_media_key(key: str):
    """Send a media key (play/pause, next, prev, mute)."""
    KEY_MAP_WIN = {
        "play_pause": 0xB3,
        "next":       0xB0,
        "prev":       0xB1,
        "mute":       0xAD,
        "vol_up":     0xAF,
        "vol_down":   0xAE,
    }
    KEY_MAP_XF86 = {
        "play_pause": "XF86AudioPlay",
        "next":       "XF86AudioNext",
        "prev":       "XF86AudioPrev",
        "mute":       "XF86AudioMute",
        "vol_up":     "XF86AudioRaiseVolume",
        "vol_down":   "XF86AudioLowerVolume",
    }
    try:
        if is_windows():
            import ctypes
            vk = KEY_MAP_WIN.get(key)
            if vk:
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        elif is_linux():
            xf86_key = KEY_MAP_XF86.get(key)
            if xf86_key:
                subprocess.run(["xdotool", "key", xf86_key], check=False)
    except Exception as exc:
        log.debug(f"[Platform] send_media_key({key}) skipped: {exc}")


def minimize_all_windows():
    """Show the desktop (minimize all windows)."""
    try:
        if is_windows():
            import ctypes
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win down
            ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)  # D down
            ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)  # D up
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)  # Win up
        elif is_linux():
            subprocess.run(["wmctrl", "-k", "on"], check=False)
    except Exception as exc:
        log.debug(f"[Platform] minimize_all_windows() skipped: {exc}")


def turn_off_display():
    """Turn off the display."""
    try:
        if is_windows():
            import ctypes
            ctypes.windll.user32.SendMessageW(-1, 0x0112, 0xF170, 2)
        elif is_linux():
            subprocess.run(["xset", "dpms", "force", "off"], check=False)
        elif is_mac():
            subprocess.run(["pmset", "displaysleepnow"], check=False)
    except Exception as exc:
        log.debug(f"[Platform] turn_off_display() skipped: {exc}")


# ── Module-level shim object (for ergonomic import) ───────────────────────────

class _PlatformShim:
    """Namespace object so callers can do: from core.system.platform import P; P.beep()"""
    is_windows      = staticmethod(is_windows)
    is_linux        = staticmethod(is_linux)
    is_mac          = staticmethod(is_mac)
    get_platform    = staticmethod(get_platform)
    beep            = staticmethod(beep)
    play_sound      = staticmethod(play_sound)
    lock_workstation   = staticmethod(lock_workstation)
    send_media_key     = staticmethod(send_media_key)
    minimize_all_windows = staticmethod(minimize_all_windows)
    turn_off_display   = staticmethod(turn_off_display)


platform_shim = _PlatformShim()
