# core/platform/windows/pycaw_impl.py
"""
pycaw + Win32 Core Audio implementation.
Used by WindowsAdapter for volume control.
"""
from __future__ import annotations

PYCAW_AVAILABLE = False
_win32_core_audio_available = False

try:
    from ctypes import POINTER, c_float, c_void_p, cast, pointer
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    PYCAW_AVAILABLE = True
except ImportError:
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        PYCAW_AVAILABLE = True
    except ImportError:
        pass

try:
    from ctypes import wintypes
    import ctypes
    import sys
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32
        _win32_core_audio_available = True
    else:
        _win32_core_audio_available = False
except ImportError:
    pass


class CoreAudioVolume:
    """Win32 Core Audio master volume via MMDevice API (no pycaw required)."""
    def __init__(self):
        self._endpoint: c_void_p | None = None
        self._volume_iface: c_void_p | None = None
        if not _win32_core_audio_available:
            return
        try:
            from ctypes import wintypes
            from ctypes.wintypes import GUID

            class PROPERTYKEY(ctypes.Structure):
                _fields_ = [
                    ("fmtid", GUID), ("pid", wintypes.ULONG)
                ]

            class PROPVARIANT(ctypes.Structure):
                _fields_ = [
                    ("vt", wintypes.USHORT), ("wReserved1", wintypes.USHORT),
                    ("wReserved2", wintypes.USHORT), ("wReserved3", wintypes.USHORT),
                    ("h", ctypes.c_void_p),
                ]

            MMDeviceEnumerator = ctypes.windll.mmdevapi.MMDeviceEnumerator
            MMDeviceEnumerator.argtypes = []
            MMDeviceEnumerator.restype = ctypes.c_void_p
            e = MMDeviceEnumerator()
            GetDefaultAudioEndpoint = ctypes.windll.mmdevapi.MMDeviceEnumerator_GetDefaultAudioEndpoint
            GetDefaultAudioEndpoint.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
            endpoint = ctypes.c_void_p()
            GetDefaultAudioEndpoint(e, 0, 0, ctypes.byref(endpoint))
            self._endpoint = endpoint
            Activate = ctypes.windll.mmdevapi.MMDevice_Activate
            Activate.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            vol_iface = ctypes.c_void_p()
            Activate(endpoint, 23, None, ctypes.byref(vol_iface))
            self._volume_iface = vol_iface
        except Exception:
            pass

    def _set_volume(self, level: float) -> bool:
        if not self._volume_iface:
            return False
        try:
            SetMasterVolumeLevel = ctypes.windll.mmdevapi.MMDevice_SetMasterVolumeLevel
            SetMasterVolumeLevel.argtypes = [ctypes.c_void_p, ctypes.c_float]
            SetMasterVolumeLevel(self._endpoint, c_float(-(1.0 - level / 100.0) * 50.0))
            return True
        except Exception:
            return False

    def _get_volume(self) -> float:
        if not self._volume_iface:
            return 50.0
        try:
            GetMasterVolumeLevel = ctypes.windll.mmdevapi.MMDevice_GetMasterVolumeLevel
            GetMasterVolumeLevel.argtypes = [ctypes.c_void_p]
            GetMasterVolumeLevel.restype = ctypes.c_float
            level = GetMasterVolumeLevel(self._endpoint)
            db = level
            percent = 100.0 - (abs(db) / 50.0 * 100.0)
            return max(0, min(100, percent))
        except Exception:
            return 50.0


_core_audio: CoreAudioVolume | None = None

def get_master_volume() -> float:
    global _core_audio
    if PYCAW_AVAILABLE:
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            return round(volume.GetMasterVolumeLevelScalar() * 100, 1)
        except Exception:
            pass
    if _core_audio is None:
        _core_audio = CoreAudioVolume()
    return _core_audio._get_volume()

def set_master_volume(level: float) -> bool:
    global _core_audio
    clamped = max(0.0, min(100.0, level))
    if PYCAW_AVAILABLE:
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(clamped / 100.0, None)
            return True
        except Exception:
            pass
    if _core_audio is None:
        _core_audio = CoreAudioVolume()
    return _core_audio._set_volume(clamped)
