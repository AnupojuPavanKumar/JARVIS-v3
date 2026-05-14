# core/platform/windows/adapter.py
"""
Windows platform adapter — all Windows-specific logic in one place.
Win32 APIs, ctypes, process enumeration, audio control, GPU info.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

from core.platform.base import PlatformAdapter, PlatformCapabilities, TrustLevel


# ── Win32 Constants ────────────────────────────────────────────────────────────
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
BM_CLICK = 0x00F5
BN_CLICKED = 0
TB_AUTOSIZE = 0x0431
STM_SETICON = 0x0170
ICON_BIG = 1
GW_ENABLEDPOPUP = 6
GW_OWNER = 4
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002

# ── ctypes Setup ───────────────────────────────────────────────────────────────
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32
psapi = ctypes.windll.psapi

# ── GPU Info via PowerShell ─────────────────────────────────────────────────────
def _get_gpu_info() -> dict:
    """Get GPU info via PowerShell (GTX/RTX compatible)."""
    try:
        result = subprocess.run([
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress"
        ], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            import json
            data = json.loads(result.stdout)
            if isinstance(data, list):
                data = data[0]
            total = data.get("AdapterRAM", 0)
            return {
                "name": data.get("Name", "Unknown"),
                "vram_total_mb": total // (1024 * 1024) if total else 0,
                "vram_used_mb": 0,
                "vram_free_mb": total // (1024 * 1024) if total else 0,
                "driver": data.get("DriverVersion", "unknown"),
                "gpu_util": 0.0,
            }
    except Exception:
        pass
    return {"name": "Unknown", "vram_total_mb": 0, "vram_used_mb": 0, "vram_free_mb": 0, "driver": "unknown", "gpu_util": 0.0}


# ── Windows Adapter ────────────────────────────────────────────────────────────
class WindowsAdapter(PlatformAdapter):
    """Windows-specific implementation of PlatformAdapter."""

    capabilities = PlatformCapabilities(
        platform_name="windows",
        supports_process_enum=True,
        supports_window_enum=True,
        supports_audio_control=True,
        supports_registry=True,
        supports_services=False,
        supports_gpu_info=True,
        supports_privilege_elevation=True,
        trusted_app_dirs=(
            r"C:\Users\Pavan2808\AppData\Local\Programs",
            r"C:\Users\Pavan2808\AppData\Local\Programs\Microsoft VS Code",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
            os.path.expandvars(r"%APPDATA%"),
            os.path.expandvars(r"%PROGRAMFILES%"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%"),
            os.path.expandvars(r"%USERPROFILE%\Desktop"),
        ),
    )

    _cached_gpu_info: Optional[dict] = None
    _gpu_cache_time: float = 0.0
    _GPU_CACHE_TTL: float = 30.0

    def get_running_processes(self) -> dict[str, int]:
        SNAPSHOT = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if SNAPSHOT == -1:
            return {}
        try:
            processes: dict[str, int] = {}
            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("th32Threads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.c_char * 260),
                ]
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if kernel32.Process32First(SNAPSHOT, ctypes.byref(entry)):
                while True:
                    name = entry.szExeFile.decode("utf-8", "ignore").lower()
                    if name not in processes:
                        processes[name] = entry.th32ProcessID
                    if not kernel32.Process32Next(SNAPSHOT, ctypes.byref(entry)):
                        break
            return processes
        finally:
            kernel32.CloseHandle(SNAPSHOT)

    def is_process_running(self, name: str) -> bool:
        name_lower = name.lower()
        return any(name_lower in p for p in self.get_running_processes())

    def find_window_handle(self, window_title: str) -> Optional[int]:
        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        def enum_cb(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                title = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title, length + 1)
                if window_title.lower() in title.value.lower():
                    matches.append(hwnd)
            return 1
        matches: list[int] = []
        user32.EnumWindows(enum_cb, 0)
        return matches[0] if matches else None

    def get_focused_window(self) -> Optional[int]:
        return user32.GetForegroundWindow()

    def close_window(self, hwnd: int, graceful: bool = True) -> bool:
        if not hwnd:
            return False
        if graceful:
            wstyle = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            if wstyle & WS_CAPTION:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return True
        user32.PostMessageW(hwnd, WM_QUIT, 0, 0)
        return True

    def focus_window(self, hwnd: int) -> bool:
        if not hwnd:
            return False
        user32.SwitchToThisWindow(ctypes.c_void_p(hwnd), True)
        user32.SetForegroundWindow(hwnd)
        return True

    def get_audio_devices(self) -> list[dict]:
        devices: list[dict] = []
        try:
            from cffi import FFI
            ffi = FFI()
            ffi.cdef("""
                void *CoCreateInstance(int *clsid, int iid, int ctx);
            """)
            return [{"name": "Speakers", "type": "output", "id": "default"}]
        except ImportError:
            pass
        result = subprocess.run([
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_SoundDevice | Select-Object Name,DeviceID | ConvertTo-Json -Compress"
        ], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            try:
                import json
                data = json.loads(result.stdout)
                if isinstance(data, list):
                    for d in data:
                        devices.append({"name": d.get("Name", ""), "type": "output", "id": d.get("DeviceID", "")})
                else:
                    devices.append({"name": data.get("Name", ""), "type": "output", "id": data.get("DeviceID", "")})
            except Exception:
                pass
        if not devices:
            devices.append({"name": "Default Audio Device", "type": "output", "id": "default"})
        return devices

    def get_default_audio_device(self) -> Optional[dict]:
        devices = self.get_audio_devices()
        return devices[0] if devices else None

    def get_volume(self) -> float:
        try:
            from core.platform.windows.pycaw_impl import get_master_volume
            return get_master_volume()
        except Exception:
            pass
        try:
            result = subprocess.run([
                "powershell", "-NoProfile", "-Command",
                "(Get-AudioMasterVolume -ErrorAction SilentlyContinue) -replace '[^0-9]', ''"
            ], capture_output=True, text=True, timeout=3)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return 50.0

    def set_volume(self, level: float) -> bool:
        try:
            from core.platform.windows.pycaw_impl import set_master_volume
            set_master_volume(level)
            return True
        except Exception:
            pass
        try:
            subprocess.run([
                "powershell", "-NoProfile", "-Command",
                f"Set-AudioVolume {level / 100.0}"
            ], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    def get_gpu_info(self) -> dict:
        now = time.time()
        if self._cached_gpu_info and (now - self._gpu_cache_time) < self._GPU_CACHE_TTL:
            return self._cached_gpu_info
        info = _get_gpu_info()
        self._cached_gpu_info = info
        self._gpu_cache_time = now
        return info

    def get_cpu_usage(self) -> float:
        try:
            result = subprocess.run([
                "powershell", "-NoProfile", "-Command",
                "(Get-Counter '\\Processor(_Total)\\% Processor Time').CounterSamples.CookedValue"
            ], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return 0.0

    def get_ram_usage(self) -> dict:
        try:
            result = subprocess.run([
                "powershell", "-NoProfile", "-Command",
                "$cim = Get-CimInstance Win32_OperatingSystem; [math]::Round(($cim.TotalVisibleMemorySize - $cim.FreePhysicalMemory) / 1024, 0); [math]::Round($cim.FreePhysicalMemory / 1024, 0); [math]::Round($cim.TotalVisibleMemorySize / 1024, 0)"
            ], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 3:
                    return {
                        "used_mb": float(lines[0].strip()),
                        "free_mb": float(lines[1].strip()),
                        "total_mb": float(lines[2].strip()),
                    }
        except Exception:
            pass
        return {"used_mb": 0, "free_mb": 0, "total_mb": 0}

    def get_system_info(self) -> dict:
        import platform as plat_module
        return {
            "os": "Windows",
            "version": plat_module.win32_ver()[0] or "Unknown",
            "hostname": plat_module.node(),
            "arch": plat_module.machine(),
        }

    def kill_process(self, pid: int, force: bool = False) -> bool:
        PROCESS_TERMINATE = 0x0001
        handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not handle:
            return False
        try:
            if force:
                return kernel32.TerminateProcess(handle, 1) != 0
            else:
                return kernel32.GenerateConsoleCtrlEvent(0, pid) != 0 or user32.PostMessageW(pid, WM_QUIT, 0, 0) != 0
        finally:
            kernel32.CloseHandle(handle)

    def launch_app(self, path: str, args: str = "") -> Optional[int]:
        if not os.path.exists(path):
            return None
        try:
            import win32api
            import win32con
            import win32process
            startup = win32process.STARTUPINFO()
            startup.dwFlags = win32con.STARTF_USESHOWWINDOW
            startup.wShowWindow = win32con.SW_SHOW
            process_info = win32process.CreateProcess(
                path, args, None, None, False,
                win32con.CREATE_NEW_CONSOLE, None, os.path.dirname(path),
                startup,
            )
            return process_info[0].__int__()
        except Exception:
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags = subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_SHOW
                proc = subprocess.Popen(
                    [path] + args.split() if args else [],
                    startupinfo=si,
                    cwd=os.path.dirname(path) or None,
                )
                return proc.pid
            except Exception:
                return None

    def elevate_privilege(self, command: str) -> bool:
        try:
            import win32api
            import win32con
            import win32process
            import win32event
            import win32security
            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(),
                win32con.TOKEN_DUPLICATE | win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY
            )
            privilege_id = win32security.LookupPrivilegeValue(None, win32con.SE_DEBUG_PRIVILEGE)
            win32security.AdjustTokenPrivileges(token, [(privilege_id, win32security.SE_PRIVILEGE_ENABLED)])
            return True
        except Exception:
            return False

    def get_microphones(self) -> list[dict]:
        mics: list[dict] = []
        try:
            result = subprocess.run([
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_CameraOrVideoSensor | Where-Object {$_.Purpose -like '*microphone*'} | Select-Object Name,DeviceID | ConvertTo-Json -Compress"
            ], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                import json
                data = json.loads(result.stdout)
                if isinstance(data, list):
                    for d in data:
                        mics.append({"name": d.get("Name", ""), "id": d.get("DeviceID", "")})
                elif isinstance(data, dict):
                    mics.append({"name": data.get("Name", ""), "id": data.get("DeviceID", "")})
        except Exception:
            pass
        if not mics:
            mics.append({"name": "Default Microphone", "id": "default"})
        return mics

    def check_trust_level(self, path: str) -> TrustLevel:
        import os as os_mod
        if not path or not os_mod.path.exists(path):
            return TrustLevel.TRUST_UNVERIFIED
        path_lower = path.lower()
        if path_lower.startswith(r"c:\windows\system32"):
            return TrustLevel.TRUST_SYSTEM
        for trusted_dir in self.capabilities.trusted_app_dirs:
            if path_lower.startswith(trusted_dir.lower()):
                return TrustLevel.TRUST_USER
        try:
            import win32security
            import win32api
            import pywintypes
            sd = win32security.GetFileSecurity(path, win32security.OWNER_SECURITY_INFORMATION)
            owner_sid = sd.GetSecurityDescriptorOwner()
            owner_name, domain, _ = win32security.LookupAccountSID(None, owner_sid)
            if owner_name == os_mod.expanduser("~").split("\\")[-1]:
                return TrustLevel.TRUST_USER
        except Exception:
            pass
        return TrustLevel.TRUST_UNVERIFIED
