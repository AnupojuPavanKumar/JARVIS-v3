# core/platform/base.py
"""
Platform abstraction base interfaces.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from enum import IntEnum


class TrustLevel(IntEnum):
    TRUST_UNVERIFIED = 0
    TRUST_SCRIPT = 1
    TRUST_USER = 2
    TRUST_ADMIN = 3
    TRUST_SYSTEM = 4


@dataclass(frozen=True)
class PlatformCapabilities:
    """Describes what capabilities a platform adapter provides."""
    platform_name: str
    supports_process_enum: bool = False
    supports_window_enum: bool = False
    supports_audio_control: bool = False
    supports_registry: bool = False
    supports_services: bool = False
    supports_gpu_info: bool = False
    supports_privilege_elevation: bool = False
    trusted_app_dirs: tuple[str, ...] = field(default_factory=tuple)


class PlatformAdapter(ABC):
    """
    Abstract base for platform-specific operations.
    All platform logic MUST flow through this interface.
    """
    capabilities: PlatformCapabilities

    @abstractmethod
    def get_running_processes(self) -> dict[str, int]:
        """Return {name: pid} of running processes."""

    @abstractmethod
    def is_process_running(self, name: str) -> bool:
        """Check if a process is running by name."""

    @abstractmethod
    def find_window_handle(self, window_title: str) -> Optional[int]:
        """Find a window handle by title substring. Returns HWND/int."""

    @abstractmethod
    def get_focused_window(self) -> Optional[int]:
        """Get the currently focused window handle."""

    @abstractmethod
    def close_window(self, hwnd: int, graceful: bool = True) -> bool:
        """Close a window. graceful=True uses WM_CLOSE first."""

    @abstractmethod
    def focus_window(self, hwnd: int) -> bool:
        """Bring window to foreground."""

    @abstractmethod
    def get_audio_devices(self) -> list[dict]:
        """Return list of audio endpoint devices."""

    @abstractmethod
    def get_default_audio_device(self) -> Optional[dict]:
        """Return the default audio output device."""

    @abstractmethod
    def get_volume(self) -> float:
        """Get master volume 0.0-100.0."""

    @abstractmethod
    def set_volume(self, level: float) -> bool:
        """Set master volume 0.0-100.0."""

    @abstractmethod
    def get_gpu_info(self) -> dict:
        """Return GPU name, VRAM used/free/total, GPU util."""

    @abstractmethod
    def get_cpu_usage(self) -> float:
        """Return CPU usage 0.0-100.0."""

    @abstractmethod
    def get_ram_usage(self) -> dict:
        """Return RAM used/free/total in MB."""

    @abstractmethod
    def get_system_info(self) -> dict:
        """Return OS name, version, hostname."""

    @abstractmethod
    def kill_process(self, pid: int, force: bool = False) -> bool:
        """Kill a process by PID."""

    @abstractmethod
    def launch_app(self, path: str, args: str = "") -> Optional[int]:
        """Launch an executable. Returns PID on success."""

    @abstractmethod
    def elevate_privilege(self, command: str) -> bool:
        """Run command with elevated privileges (UAC/admin)."""

    @abstractmethod
    def get_microphones(self) -> list[dict]:
        """Return list of available microphone devices."""

    @abstractmethod
    def check_trust_level(self, path: str) -> TrustLevel:
        """Determine trust level for a given executable path."""
