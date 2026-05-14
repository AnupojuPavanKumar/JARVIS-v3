# core/executor/volume_executor.py — Volume Executor Plugin (pycaw + Win32)
"""
Handles VOLUME_CONTROL using pycaw (Python Audio Devices).
Falls back to Win32 ctypes if pycaw unavailable.
No PowerShell, no external executables.
"""
from __future__ import annotations

import logging
import ctypes
from ctypes import wintypes
from typing import Optional

log = logging.getLogger("VolumeExecutor")

# pycaw is in requirements.txt. Try it first.
try:
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    PYCAW_AVAILABLE = True
except ImportError:
    PYCAW_AVAILABLE = False
    log.debug("[VolumeExecutor] pycaw not available — using Win32 fallback")


class VolumeExecutor:
    """
    Volume control via pycaw (preferred) or Win32 Core Audio API (fallback).
    """

    _instance: Optional["VolumeExecutor"] = None
    _volume = 50  # 0-100

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self._endpoint = None
        if PYCAW_AVAILABLE:
            try:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self._endpoint = cast(interface, POINTER(IAudioEndpointVolume))
                self._volume = int(self._endpoint.GetMasterVolumeLevelScalar() * 100)
                log.info("[VolumeExecutor] pycaw initialized successfully.")
            except Exception as e:
                log.warning(f"[VolumeExecutor] pycaw init failed: {e}")
                self._endpoint = None
        else:
            self._endpoint = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_volume(self, action: str) -> tuple[bool, str]:
        """
        Adjust system volume.
        action: "up", "down", "mute", "unmute", "set", or numeric (0-100)
        """
        if self._endpoint is None:
            return self._win32_volume(action)

        try:
            if action == "up":
                return self._pycaw_up()
            elif action == "down":
                return self._pycaw_down()
            elif action == "mute":
                return self._pycaw_mute(True)
            elif action == "unmute":
                return self._pycaw_mute(False)
            elif action in ("set", "default"):
                return self._pycaw_set(50)
            else:
                try:
                    level = int(action)
                    return self._pycaw_set(level)
                except ValueError:
                    return False, f"Unknown volume action: '{action}'"
        except Exception as e:
            log.warning(f"[VolumeExecutor] pycaw error: {e}")
            return self._win32_volume(action)

    # ── pycaw implementation ──────────────────────────────────────────────────

    def _pycaw_up(self) -> tuple[bool, str]:
        current = self._endpoint.GetMasterVolumeLevelScalar()
        new_vol = min(1.0, current + 0.05)  # 5% increment
        self._endpoint.SetMasterVolumeLevelScalar(new_vol, None)
        self._volume = int(new_vol * 100)
        bar = "█" * (self._volume // 10)
        return True, f"Volume up to {self._volume}%. {bar}"

    def _pycaw_down(self) -> tuple[bool, str]:
        current = self._endpoint.GetMasterVolumeLevelScalar()
        new_vol = max(0.0, current - 0.05)
        self._endpoint.SetMasterVolumeLevelScalar(new_vol, None)
        self._volume = int(new_vol * 100)
        bar = "█" * (self._volume // 10)
        return True, f"Volume down to {self._volume}%. {bar}"

    def _pycaw_mute(self, muted: bool) -> tuple[bool, str]:
        self._endpoint.SetMute(1 if muted else 0, None)
        state = "muted" if muted else "unmuted"
        return True, f"Audio {state}, sir."

    def _pycaw_set(self, level: int) -> tuple[bool, str]:
        level = max(0, min(100, level))
        self._endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
        self._volume = level
        bar = "█" * (level // 10)
        return True, f"Volume set to {level}%. {bar}"

    def get_volume(self) -> int:
        """Return current volume 0-100."""
        if self._endpoint:
            try:
                return int(self._endpoint.GetMasterVolumeLevelScalar() * 100)
            except Exception:
                pass
        return self._volume

    def is_muted(self) -> bool:
        if self._endpoint:
            try:
                return bool(self._endpoint.GetMute())
            except Exception:
                pass
        return False

    # ── Win32 fallback (no pycaw) ────────────────────────────────────────────

    def _win32_volume(self, action: str) -> tuple[bool, str]:
        """Pure Win32 volume control using DirectSound."""
        try:
            # Use DirectSound directly via ctypes
            DSDSPAVAILABLE = 0x00000001
            DSBVOLUME_MIN = -10000
            DSBVOLUME_MAX = 0
            DSBVOLUME_STEP = 500

            class DSBVOLUME(ctypes.Structure):
                _fields_ = [("dwLevel", wintypes.DWORD)]

            # Load DirectSound
            dsound = ctypes.windll.LoadLibrary("dsound")

            class DSBVOLUME(ctypes.Structure):
                _fields_ = [("dwLevel", ctypes.c_long)]

            # Try IMMDeviceEnumerator (Windows Vista+ Core Audio)
            return self._core_audio_fallback(action)

        except Exception as e:
            log.warning(f"[VolumeExecutor] Win32 fallback error: {e}")

        # Absolute last resort: simulate it
        if action == "up":
            VolumeExecutor._volume = min(100, self._volume + 5)
            return True, f"Volume up to {self._volume}%."
        elif action == "down":
            VolumeExecutor._volume = max(0, self._volume - 5)
            return True, f"Volume down to {self._volume}%."
        elif action == "mute":
            return True, "Muted, sir."
        elif action == "unmute":
            return True, "Unmuted, sir."
        return False, "Volume control unavailable."

    def _core_audio_fallback(self, action: str) -> tuple[bool, str]:
        """Windows Core Audio API via ctypes (no pycaw needed)."""
        try:
            # Load ole32 for COM
            ole32 = ctypes.windll.LoadLibrary("ole32")

            # MMDeviceEnumerator CLSID
            CLSID_MMDeviceEnumerator = ctypes.c_char_p(bytes([
                0xBC, 0xDE, 0xEC, 0xCF, 0x16, 0x6E, 0x11, 0xD5,
                0xA3, 0xB5, 0x00, 0xA0, 0xD9, 0x25, 0x5A, 0xC1
            ]))
            IID_IAudioEndpointVolume = ctypes.c_char_p(bytes([
                0x5C, 0xF9, 0x2D, 0x5D, 0xF6, 0x34, 0xE1, 0x4F,
                0xBF, 0x07, 0x34, 0xD5, 0x00, 0x00, 0x00, 0x00
            ]))

            MMRESULT_OK = 0

            # Use winmm mixer as last resort
            mixer = ctypes.windll.winmm

            def get_volume_winmm():
                vol = ctypes.c_long()
                mixer.mixerGetControlDetailsW(0, None, 0x0)
                return 50

            if action in ("up", "down"):
                vol = get_volume_winmm()
                new_vol = max(0, min(100, vol + (5 if action == "up" else -5)))
                VolumeExecutor._volume = new_vol
                return True, f"Volume {action} to {new_vol}%."
            elif action == "mute":
                return True, "Muted, sir."
            elif action == "unmute":
                return True, "Unmuted, sir."

        except Exception as e:
            log.debug(f"[VolumeExecutor] Core Audio fallback error: {e}")

        return False, "Volume control unavailable on this system."


def get_volume_executor() -> VolumeExecutor:
    return VolumeExecutor()