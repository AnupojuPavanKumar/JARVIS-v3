# core/capabilities/registry.py
"""
Capability registry — dynamic detection of system capabilities.
Installed apps, GPU, audio endpoints, microphones, Ollama availability,
model inventory, platform features. Drives fallback routing.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

log = logging.getLogger("CapabilityRegistry")

PLATFORM_AVAILABLE = False
try:
    from core.platform import get_platform
    PLATFORM_AVAILABLE = True
except ImportError:
    pass


class Capability(Enum):
    PROCESS_ENUM = auto()
    WINDOW_ENUM = auto()
    AUDIO_CONTROL = auto()
    REGISTRY_ACCESS = auto()
    PRIVILEGE_ELEVATION = auto()
    GPU_INFO = auto()
    MICROPHONE = auto()
    CAMERA = auto()
    OLLAMA = auto()
    OLLAMA_VISION = auto()
    TTS = auto()
    STT = auto()
    CLIPBOARD = auto()
    SYSTEM_SOUNDS = auto()
    WIN32_COM = auto()
    PYCAW = auto()
    POWER_SHELL = auto()


@dataclass
class CapabilityInfo:
    """Metadata for a detected capability."""
    capability: Capability
    available: bool
    details: str = ""
    last_checked: float = 0.0
    version: str = ""
    confidence: float = 1.0


@dataclass
class ModelInfo:
    """Information about an available Ollama model."""
    name: str
    size_mb: float
    modified: str
    supports_vision: bool = False


@dataclass
class CapabilityRegistryData:
    """Full capability registry state."""
    capabilities: dict[Capability, CapabilityInfo] = field(default_factory=dict)
    installed_apps: dict[str, str] = field(default_factory=dict)
    audio_devices: list[dict] = field(default_factory=list)
    microphones: list[dict] = field(default_factory=list)
    gpu_name: str = "Unknown"
    gpu_vram_mb: float = 0
    models: list[ModelInfo] = field(default_factory=list)
    platform_features: dict[str, bool] = field(default_factory=dict)
    last_full_scan: float = 0.0


class CapabilityRegistry:
    """
    Dynamic capability detection and registry.
    Provides fallback routing based on what the system actually supports.
    Thread-safe, cached, refreshable.
    """

    def __init__(self):
        self._data = CapabilityRegistryData()
        self._lock = threading.RLock()
        self._scanning = False
        self._scan_thread: threading.Thread | None = None
        self._ollama_url: str = "http://localhost:11434"
        self._ollama_checked = False
        self._ollama_available: bool | None = None

        self._register_builtin_checks()
        self._schedule_scan()

    def _register_builtin_checks(self):
        """Register all built-in capability checks."""
        if PLATFORM_AVAILABLE:
            try:
                platform = get_platform()
                caps = platform.capabilities
                self._data.capabilities[Capability.PROCESS_ENUM] = CapabilityInfo(
                    Capability.PROCESS_ENUM, caps.supports_process_enum, "via platform adapter"
                )
                self._data.capabilities[Capability.WINDOW_ENUM] = CapabilityInfo(
                    Capability.WINDOW_ENUM, caps.supports_window_enum, "via platform adapter"
                )
                self._data.capabilities[Capability.AUDIO_CONTROL] = CapabilityInfo(
                    Capability.AUDIO_CONTROL, caps.supports_audio_control, "via platform adapter"
                )
                self._data.capabilities[Capability.GPU_INFO] = CapabilityInfo(
                    Capability.GPU_INFO, caps.supports_gpu_info, "via platform adapter"
                )
                self._data.capabilities[Capability.PRIVILEGE_ELEVATION] = CapabilityInfo(
                    Capability.PRIVILEGE_ELEVATION, caps.supports_privilege_elevation, "via platform adapter"
                )
            except Exception as e:
                log.debug(f"[CapabilityRegistry] Platform checks failed: {e}")

        try:
            import win32gui, win32con
            self._data.capabilities[Capability.WIN32_COM] = CapabilityInfo(
                Capability.WIN32_COM, True, "win32gui/win32con available"
            )
        except ImportError:
            self._data.capabilities[Capability.WIN32_COM] = CapabilityInfo(
                Capability.WIN32_COM, False, "win32gui not available"
            )

        try:
            from core.platform.windows.pycaw_impl import PYCAW_AVAILABLE
            self._data.capabilities[Capability.PYCAW] = CapabilityInfo(
                Capability.PYCAW, PYCAW_AVAILABLE, "pycaw available" if PYCAW_AVAILABLE else "pycaw not installed"
            )
        except ImportError:
            self._data.capabilities[Capability.PYCAW] = CapabilityInfo(
                Capability.PYCAW, False, "pycaw not installed"
            )

        try:
            result = subprocess.run(["powershell", "-NoProfile", "echo test"], capture_output=True, timeout=3)
            ps_available = result.returncode == 0
            self._data.capabilities[Capability.POWER_SHELL] = CapabilityInfo(
                Capability.POWER_SHELL, ps_available, "PowerShell available" if ps_available else "PowerShell unavailable"
            )
        except Exception:
            self._data.capabilities[Capability.POWER_SHELL] = CapabilityInfo(
                Capability.POWER_SHELL, False, "PowerShell not available"
            )

    def _schedule_scan(self):
        """Schedule a full capability scan in the background."""
        if self._scan_thread and self._scan_thread.is_alive():
            return
        self._scan_thread = threading.Thread(target=self._full_scan, daemon=True, name="CapabilityScan")
        self._scan_thread.start()

    def _full_scan(self):
        """Background thread: probe all dynamic capabilities."""
        with self._lock:
            self._scanning = True
        try:
            self._check_ollama()
            self._check_models()
            self._check_audio()
            self._check_microphones()
            self._check_gpu()
            self._check_installed_apps()
            self._data.last_full_scan = time.time()
        except Exception as e:
            log.warning(f"[CapabilityRegistry] Full scan error: {e}")
        finally:
            with self._lock:
                self._scanning = False

    def _check_ollama(self):
        """Check if Ollama is running."""
        if self._ollama_available is not None:
            return
        try:
            import urllib.request
            req = urllib.request.Request(f"{self._ollama_url}/api/tags", timeout=3)
            resp = urllib.request.urlopen(req, timeout=3)
            self._ollama_available = resp.status == 200
            self._data.capabilities[Capability.OLLAMA] = CapabilityInfo(
                Capability.OLLAMA, self._ollama_available, self._ollama_url
            )
        except Exception:
            self._ollama_available = False
            self._data.capabilities[Capability.OLLAMA] = CapabilityInfo(
                Capability.OLLAMA, False, "Ollama not responding at localhost:11434"
            )

    def _check_models(self):
        """Get list of installed Ollama models."""
        if not self._ollama_available:
            return
        try:
            import urllib.request
            import json
            req = urllib.request.Request(f"{self._ollama_url}/api/tags", timeout=5)
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            models = []
            for m in data.get("models", []):
                name = m.get("name", "")
                size = m.get("size", 0)
                modified = m.get("modified_at", "")
                vision = "vision" in name.lower() or "llava" in name.lower() or "qwen2-vl" in name.lower()
                models.append(ModelInfo(name=name, size_mb=size / (1024 * 1024), modified=modified, supports_vision=vision))
            self._data.models = models
            self._data.capabilities[Capability.OLLAMA_VISION] = CapabilityInfo(
                Capability.OLLAMA_VISION,
                any(m.supports_vision for m in models),
                f"{sum(1 for m in models if m.supports_vision)} vision models"
            )
        except Exception as e:
            log.debug(f"[CapabilityRegistry] Model check failed: {e}")

    def _check_audio(self):
        """Check audio devices."""
        if PLATFORM_AVAILABLE:
            try:
                platform = get_platform()
                self._data.audio_devices = platform.get_audio_devices()
            except Exception:
                pass

    def _check_microphones(self):
        """Check microphone devices."""
        if PLATFORM_AVAILABLE:
            try:
                platform = get_platform()
                self._data.microphones = platform.get_microphones()
            except Exception:
                pass

    def _check_gpu(self):
        """Check GPU info."""
        if PLATFORM_AVAILABLE:
            try:
                platform = get_platform()
                info = platform.get_gpu_info()
                with self._lock:
                    self._data.gpu_name = info.get("name", "Unknown")
                    self._data.gpu_vram_mb = info.get("vram_total_mb", 0)
            except Exception:
                pass

    def _check_installed_apps(self):
        """Check if key apps are installed."""
        from core.apps.app_registry import get_app_registry
        try:
            reg = get_app_registry()
            self._data.installed_apps = dict(reg._cache)
        except Exception:
            pass

    def is_available(self, cap: Capability) -> bool:
        """Check if a capability is available."""
        with self._lock:
            info = self._data.capabilities.get(cap)
        if info:
            return info.available
        return False

    def get(self, cap: Capability) -> CapabilityInfo | None:
        with self._lock:
            return self._data.capabilities.get(cap)

    def get_models(self) -> list[ModelInfo]:
        with self._lock:
            return list(self._data.models)

    def get_audio_devices(self) -> list[dict]:
        with self._lock:
            return list(self._data.audio_devices)

    def get_microphones(self) -> list[dict]:
        with self._lock:
            return list(self._data.microphones)

    def get_gpu_name(self) -> str:
        with self._lock:
            return self._data.gpu_name

    def is_ollama_available(self) -> bool:
        with self._lock:
            return self._ollama_available is True

    def refresh(self):
        """Trigger a background re-scan."""
        self._schedule_scan()

    def stats(self) -> dict:
        with self._lock:
            caps = {c.name: {"available": i.available, "details": i.details}
                    for c, i in self._data.capabilities.items()}
            return {
                "available_count": sum(1 for i in self._data.capabilities.values() if i.available),
                "capabilities": caps,
                "models": [{"name": m.name, "size_mb": round(m.size_mb, 1)} for m in self._data.models],
                "gpu_name": self._data.gpu_name,
                "gpu_vram_mb": self._data.gpu_vram_mb,
                "ollama_available": self._ollama_available or False,
                "scanning": self._scanning,
                "last_scan": self._data.last_full_scan,
            }


_global_registry: CapabilityRegistry | None = None
_reg_lock = threading.Lock()


def get_capability_registry() -> CapabilityRegistry:
    """Get the global capability registry singleton."""
    global _global_registry
    with _reg_lock:
        if _global_registry is None:
            _global_registry = CapabilityRegistry()
        return _global_registry
