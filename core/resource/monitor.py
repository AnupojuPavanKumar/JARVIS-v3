# core/resource/monitor.py
"""
Resource monitoring layer — VRAM, CPU, RAM, model load tracking,
inference queue monitoring, adaptive scheduling, and low-resource protection.
Critical for RTX 4050 laptop.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

log = logging.getLogger("ResourceMonitor")

PLATFORM_AVAILABLE = False
try:
    from core.platform.base import PlatformAdapter
    from core.platform import get_platform
    PLATFORM_AVAILABLE = True
except ImportError:
    pass


class ResourceProfile(Enum):
    IDLE = auto()
    LIGHT = auto()
    MODERATE = auto()
    HEAVY = auto()
    CRITICAL = auto()


@dataclass
class ResourceSnapshot:
    timestamp: float
    cpu_percent: float
    ram_used_mb: float
    ram_free_mb: float
    ram_total_mb: float
    ram_percent: float
    vram_used_mb: float
    vram_free_mb: float
    vram_total_mb: float
    gpu_util: float
    profile: ResourceProfile = ResourceProfile.IDLE


@dataclass
class ResourceMonitorConfig:
    sample_interval: float = 2.0
    history_size: int = 60
    vram_reserve_mb: float = 512.0
    cpu_max_percent: float = 90.0
    ram_max_percent: float = 85.0
    profile_thresholds: dict[ResourceProfile, float] = field(default_factory=lambda: {
        ResourceProfile.IDLE: 0.0,
        ResourceProfile.LIGHT: 30.0,
        ResourceProfile.MODERATE: 60.0,
        ResourceProfile.HEAVY: 80.0,
        ResourceProfile.CRITICAL: 90.0,
    })


class ResourceMonitor:
    """
    Polls system resources on a background thread.
    Tracks VRAM, CPU, RAM, GPU util.
    Provides adaptive scheduling hints and low-resource protection for RTX 4050.
    """

    def __init__(self, config: ResourceMonitorConfig | None = None):
        self.config = config or ResourceMonitorConfig()
        self._platform = None
        if PLATFORM_AVAILABLE:
            try:
                self._platform = get_platform()
            except Exception as e:
                log.warning(f"[ResourceMonitor] Platform not available: {e}")
        self._history: deque[ResourceSnapshot] = deque(maxlen=self.config.history_size)
        self._model_vram: float = 0.0
        self._inference_queue_depth: int = 0
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_snapshot: ResourceSnapshot | None = None
        self._gpu_name: str = "Unknown"

    def start(self):
        """Start background monitoring thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="ResourceMonitor")
        self._thread.start()

    def stop(self):
        """Stop background monitoring thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def _poll_loop(self):
        """Background polling loop."""
        while self._running:
            try:
                snapshot = self._sample()
                with self._lock:
                    self._history.append(snapshot)
                    self._last_snapshot = snapshot
            except Exception as e:
                log.debug(f"[ResourceMonitor] Poll error: {e}")
            time.sleep(self.config.sample_interval)

    def _sample(self) -> ResourceSnapshot:
        """Take a resource snapshot."""
        cpu = self.get_cpu_usage()
        ram = self.get_ram_usage()
        gpu = self.get_gpu_info()
        vram_total = gpu.get("vram_total_mb", 0)
        vram_free = gpu.get("vram_free_mb", 0)
        vram_reserve = self.config.vram_reserve_mb
        effective_free = max(0, vram_free - vram_reserve)
        ram_total = ram.get("total_mb", 1)
        ram_used = ram.get("used_mb", 0)
        ram_percent = (ram_used / ram_total * 100) if ram_total > 0 else 0
        gpu_util = gpu.get("gpu_util", 0)
        profile = self._compute_profile(cpu, ram_percent, gpu_util, vram_free, vram_reserve)
        snapshot = ResourceSnapshot(
            timestamp=time.time(),
            cpu_percent=cpu,
            ram_used_mb=ram_used,
            ram_free_mb=ram.get("free_mb", 0),
            ram_total_mb=ram_total,
            ram_percent=ram_percent,
            vram_used_mb=gpu.get("vram_used_mb", 0),
            vram_free_mb=effective_free,
            vram_total_mb=vram_total,
            gpu_util=gpu_util,
            profile=profile,
        )
        if gpu.get("name") and self._gpu_name == "Unknown":
            self._gpu_name = gpu.get("name", "Unknown")
        return snapshot

    def _compute_profile(
        self, cpu: float, ram_pct: float, gpu_util: float, vram_free: float, vram_reserve: float
    ) -> ResourceProfile:
        """Compute current resource profile based on combined load."""
        max_cpu = self.config.profile_thresholds[ResourceProfile.HEAVY]
        max_ram = self.config.ram_max_percent
        gpu_heavy = 80.0
        vram_pressure = 1.0 - (max(0, vram_free) / max(1, vram_free + vram_reserve))
        composite = max(
            cpu / max_cpu,
            ram_pct / max_ram,
            gpu_util / 100.0,
            vram_pressure,
        )
        if composite >= 0.90:
            return ResourceProfile.CRITICAL
        elif composite >= 0.80:
            return ResourceProfile.HEAVY
        elif composite >= 0.60:
            return ResourceProfile.MODERATE
        elif composite >= 0.30:
            return ResourceProfile.LIGHT
        return ResourceProfile.IDLE

    def get_cpu_usage(self) -> float:
        if self._platform:
            try:
                return self._platform.get_cpu_usage()
            except Exception:
                pass
        return 0.0

    def get_ram_usage(self) -> dict:
        if self._platform:
            try:
                return self._platform.get_ram_usage()
            except Exception:
                pass
        return {"used_mb": 0, "free_mb": 0, "total_mb": 0}

    def get_gpu_info(self) -> dict:
        if self._platform:
            try:
                return self._platform.get_gpu_info()
            except Exception:
                pass
        return {"name": "Unknown", "vram_total_mb": 0, "vram_used_mb": 0, "vram_free_mb": 0, "driver": "unknown", "gpu_util": 0.0}

    def set_model_vram(self, size_mb: float):
        """Track VRAM used by loaded AI models."""
        with self._lock:
            self._model_vram = size_mb
            self._recompute_vram()

    def _recompute_vram(self):
        """Recompute effective VRAM based on model loads."""
        gpu = self.get_gpu_info()
        total = gpu.get("vram_total_mb", 0)

    def set_inference_queue_depth(self, depth: int):
        """Track number of pending inference requests."""
        with self._lock:
            self._inference_queue_depth = depth

    def can_load_model(self, required_mb: float) -> tuple[bool, str]:
        """Check if there's enough VRAM to load a model. Critical for RTX 4050."""
        gpu = self.get_gpu_info()
        vram_free = gpu.get("vram_free_mb", 0)
        effective_free = max(0, vram_free - self.config.vram_reserve_mb)
        if self._profile in (ResourceProfile.HEAVY, ResourceProfile.CRITICAL):
            return False, f"System under heavy load ({self._profile.name})"
        if effective_free < required_mb:
            return False, f"Insufficient VRAM: need {required_mb:.0f}MB, have {effective_free:.0f}MB free"
        return True, "OK"

    def should_throttle(self) -> bool:
        """Return True if system should throttle non-critical work."""
        profile = self.current_profile()
        return profile in (ResourceProfile.HEAVY, ResourceProfile.CRITICAL)

    def current_profile(self) -> ResourceProfile:
        with self._lock:
            snap = self._last_snapshot
        return snap.profile if snap else ResourceProfile.IDLE

    def current_snapshot(self) -> ResourceSnapshot | None:
        with self._lock:
            return self._last_snapshot

    def recent_history(self, seconds: float = 60.0) -> list[ResourceSnapshot]:
        """Get snapshots from the last N seconds."""
        cutoff = time.time() - seconds
        with self._lock:
            return [s for s in self._history if s.timestamp >= cutoff]

    def stats(self) -> dict:
        """Return aggregated stats."""
        with self._lock:
            history = list(self._history)
        if not history:
            snap = self._last_snapshot
            return {
                "gpu_name": self._gpu_name,
                "profile": snap.profile.name if snap else "unknown",
                "samples": 0,
                "avg_cpu_percent": snap.cpu_percent if snap else 0.0,
                "avg_ram_percent": snap.ram_percent if snap else 0.0,
                "avg_gpu_util": snap.gpu_util if snap else 0.0,
                "model_vram_mb": self._model_vram,
                "inference_queue": self._inference_queue_depth,
            }
        avg_cpu = sum(s.cpu_percent for s in history) / len(history)
        avg_ram = sum(s.ram_percent for s in history) / len(history)
        avg_gpu = sum(s.gpu_util for s in history) / len(history)
        with self._lock:
            profile = self._last_snapshot.profile if self._last_snapshot else ResourceProfile.IDLE
        return {
            "gpu_name": self._gpu_name,
            "profile": profile.name,
            "samples": len(history),
            "avg_cpu_percent": round(avg_cpu, 1),
            "avg_ram_percent": round(avg_ram, 1),
            "avg_gpu_util": round(avg_gpu, 1),
            "model_vram_mb": self._model_vram,
            "inference_queue": self._inference_queue_depth,
        }


_global_monitor: ResourceMonitor | None = None
_monitor_lock = threading.Lock()


def get_resource_monitor() -> ResourceMonitor:
    """Get the global resource monitor singleton."""
    global _global_monitor
    with _monitor_lock:
        if _global_monitor is None:
            _global_monitor = ResourceMonitor()
            _global_monitor.start()
        return _global_monitor
