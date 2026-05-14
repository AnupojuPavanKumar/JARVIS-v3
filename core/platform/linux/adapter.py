# core/platform/linux/adapter.py
"""Linux platform adapter (stub implementation)."""
from __future__ import annotations
from typing import Optional
from core.platform.base import PlatformAdapter, PlatformCapabilities, TrustLevel


class LinuxAdapter(PlatformAdapter):
    """Linux-specific implementation (placeholder for future Linux support)."""

    capabilities = PlatformCapabilities(
        platform_name="linux",
        supports_process_enum=True,
        supports_window_enum=False,
        supports_audio_control=True,
        supports_registry=False,
        supports_services=True,
        supports_gpu_info=True,
        supports_privilege_elevation=False,
        trusted_app_dirs=(),
    )

    def get_running_processes(self) -> dict[str, int]:
        return {}

    def is_process_running(self, name: str) -> bool:
        return False

    def find_window_handle(self, window_title: str) -> Optional[int]:
        return None

    def get_focused_window(self) -> Optional[int]:
        return None

    def close_window(self, hwnd: int, graceful: bool = True) -> bool:
        return False

    def focus_window(self, hwnd: int) -> bool:
        return False

    def get_audio_devices(self) -> list[dict]:
        return [{"name": "Default Audio", "type": "output", "id": "default"}]

    def get_default_audio_device(self) -> Optional[dict]:
        return {"name": "Default Audio", "type": "output", "id": "default"}

    def get_volume(self) -> float:
        return 50.0

    def set_volume(self, level: float) -> bool:
        return True

    def get_gpu_info(self) -> dict:
        return {"name": "Unknown", "vram_total_mb": 0, "vram_used_mb": 0, "vram_free_mb": 0, "driver": "unknown", "gpu_util": 0.0}

    def get_cpu_usage(self) -> float:
        return 0.0

    def get_ram_usage(self) -> dict:
        return {"used_mb": 0, "free_mb": 0, "total_mb": 0}

    def get_system_info(self) -> dict:
        import platform
        return {"os": "Linux", "version": platform.release(), "hostname": platform.node(), "arch": platform.machine()}

    def kill_process(self, pid: int, force: bool = False) -> bool:
        import os, signal
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
            return True
        except Exception:
            return False

    def launch_app(self, path: str, args: str = "") -> Optional[int]:
        import subprocess
        try:
            parts = [path] + args.split()
            proc = subprocess.Popen(parts)
            return proc.pid
        except Exception:
            return None

    def elevate_privilege(self, command: str) -> bool:
        return False

    def get_microphones(self) -> list[dict]:
        return [{"name": "Default Microphone", "id": "default"}]

    def check_trust_level(self, path: str) -> TrustLevel:
        import os
        if not path or not os.path.exists(path):
            return TrustLevel.TRUST_UNVERIFIED
        if path.startswith("/usr/bin") or path.startswith("/usr/local/bin"):
            return TrustLevel.TRUST_SYSTEM
        if path.startswith(os.path.expanduser("~/")):
            return TrustLevel.TRUST_USER
        return TrustLevel.TRUST_UNVERIFIED
