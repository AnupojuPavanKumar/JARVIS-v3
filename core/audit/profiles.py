# core/audit/profiles.py
"""
Operational profiles — P14.
Runtime complexity adapts to situation.
MINIMAL / NORMAL / DEVELOPMENT / HIGH_AUTONOMY / GAMING / SAFE_MODE.
Each profile controls active subsystems, orchestration depth, background systems,
provider selection, monitoring intensity, autonomy level.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, List, Optional

log = logging.getLogger("ProfileManager")


class OperationalProfile(Enum):
    MINIMAL = auto()
    NORMAL = auto()
    DEVELOPMENT = auto()
    HIGH_AUTONOMY = auto()
    GAMING = auto()
    SAFE_MODE = auto()


@dataclass
class ProfileConfig:
    """Configuration for an operational profile."""
    profile: OperationalProfile
    active_daemons: List[str]
    max_orchestration_depth: int
    max_concurrent_actions: int
    enable_tracing: bool
    enable_observability: bool
    enable_policy_engine: bool
    enable_chaos_testing: bool
    enable_predictive_scheduler: bool
    enable_event_governance: bool
    enable_runtime_inspector: bool
    enable_shortcut_acceleration: bool
    monitoring_interval_sec: float
    description: str


PROFILE_CONFIGS: dict[OperationalProfile, ProfileConfig] = {
    OperationalProfile.MINIMAL: ProfileConfig(
        profile=OperationalProfile.MINIMAL,
        active_daemons=["ExecQueue-Worker"],
        max_orchestration_depth=5,
        max_concurrent_actions=5,
        enable_tracing=False,
        enable_observability=False,
        enable_policy_engine=False,
        enable_chaos_testing=False,
        enable_predictive_scheduler=False,
        enable_event_governance=False,
        enable_runtime_inspector=False,
        enable_shortcut_acceleration=True,
        monitoring_interval_sec=10.0,
        description="Minimal footprint — execution queue only",
    ),
    OperationalProfile.NORMAL: ProfileConfig(
        profile=OperationalProfile.NORMAL,
        active_daemons=["ExecQueue-Worker", "EventBus-Dispatch", "ResourceMonitor"],
        max_orchestration_depth=15,
        max_concurrent_actions=20,
        enable_tracing=True,
        enable_observability=True,
        enable_policy_engine=True,
        enable_chaos_testing=False,
        enable_predictive_scheduler=True,
        enable_event_governance=True,
        enable_runtime_inspector=True,
        enable_shortcut_acceleration=True,
        monitoring_interval_sec=2.0,
        description="Balanced — all standard systems active",
    ),
    OperationalProfile.DEVELOPMENT: ProfileConfig(
        profile=OperationalProfile.DEVELOPMENT,
        active_daemons=["ExecQueue-Worker", "EventBus-Dispatch", "ResourceMonitor", "PipelineDiagnostics"],
        max_orchestration_depth=20,
        max_concurrent_actions=20,
        enable_tracing=True,
        enable_observability=True,
        enable_policy_engine=True,
        enable_chaos_testing=True,
        enable_predictive_scheduler=True,
        enable_event_governance=True,
        enable_runtime_inspector=True,
        enable_shortcut_acceleration=True,
        monitoring_interval_sec=1.0,
        description="Development — full diagnostics, chaos testing enabled",
    ),
    OperationalProfile.HIGH_AUTONOMY: ProfileConfig(
        profile=OperationalProfile.HIGH_AUTONOMY,
        active_daemons=["ExecQueue-Worker", "EventBus-Dispatch", "ResourceMonitor"],
        max_orchestration_depth=25,
        max_concurrent_actions=30,
        enable_tracing=True,
        enable_observability=True,
        enable_policy_engine=True,
        enable_chaos_testing=False,
        enable_predictive_scheduler=True,
        enable_event_governance=True,
        enable_runtime_inspector=True,
        enable_shortcut_acceleration=True,
        monitoring_interval_sec=2.0,
        description="High autonomy — deeper orchestration, more concurrent actions",
    ),
    OperationalProfile.GAMING: ProfileConfig(
        profile=OperationalProfile.GAMING,
        active_daemons=["ExecQueue-Worker"],
        max_orchestration_depth=5,
        max_concurrent_actions=5,
        enable_tracing=False,
        enable_observability=False,
        enable_policy_engine=False,
        enable_chaos_testing=False,
        enable_predictive_scheduler=True,
        enable_event_governance=False,
        enable_runtime_inspector=False,
        enable_shortcut_acceleration=True,
        monitoring_interval_sec=5.0,
        description="Gaming mode — minimal overhead, only critical execution",
    ),
    OperationalProfile.SAFE_MODE: ProfileConfig(
        profile=OperationalProfile.SAFE_MODE,
        active_daemons=["ExecQueue-Worker"],
        max_orchestration_depth=3,
        max_concurrent_actions=3,
        enable_tracing=True,
        enable_observability=True,
        enable_policy_engine=False,
        enable_chaos_testing=False,
        enable_predictive_scheduler=False,
        enable_event_governance=True,
        enable_runtime_inspector=False,
        enable_shortcut_acceleration=False,
        monitoring_interval_sec=5.0,
        description="Safe mode — maximum restrictions, safety-first",
    ),
}


class ProfileManager:
    """
    Manages operational profiles.
    Each profile controls active subsystems and orchestration constraints.
    """

    def __init__(self):
        self._current: OperationalProfile = OperationalProfile.NORMAL
        self._lock = threading.Lock()
        self._on_profile_change: List[Callable[[OperationalProfile, OperationalProfile], None]] = []
        self._history: List[OperationalProfile] = [OperationalProfile.NORMAL]

    @property
    def current(self) -> OperationalProfile:
        with self._lock:
            return self._current

    @property
    def config(self) -> ProfileConfig:
        with self._lock:
            return PROFILE_CONFIGS[self._current]

    def set_profile(self, profile: OperationalProfile):
        with self._lock:
            old = self._current
            if profile == old:
                return
            self._current = profile
            self._history.append(profile)
        log.info(f"[ProfileManager] Switched {old.name} -> {profile.name}")
        for cb in self._on_profile_change:
            try:
                cb(old, profile)
            except Exception as e:
                log.warning(f"[ProfileManager] profile change callback error: {e}")

    def on_profile_change(self, callback: Callable[[OperationalProfile, OperationalProfile], None]):
        self._on_profile_change.append(callback)

    def get_active_daemons(self) -> List[str]:
        return list(self.config.active_daemons)

    def can_use_daemon(self, daemon_name: str) -> bool:
        return daemon_name in self.config.active_daemons

    def should_enable(self, feature: str) -> bool:
        cfg = self.config
        if feature == "tracing":
            return cfg.enable_tracing
        if feature == "observability":
            return cfg.enable_observability
        if feature == "policy_engine":
            return cfg.enable_policy_engine
        if feature == "chaos_testing":
            return cfg.enable_chaos_testing
        if feature == "predictive_scheduler":
            return cfg.enable_predictive_scheduler
        if feature == "event_governance":
            return cfg.enable_event_governance
        if feature == "runtime_inspector":
            return cfg.enable_runtime_inspector
        if feature == "shortcut_acceleration":
            return cfg.enable_shortcut_acceleration
        return True

    def get_max_orchestration_depth(self) -> int:
        return self.config.max_orchestration_depth

    def get_max_concurrent_actions(self) -> int:
        return self.config.max_concurrent_actions

    def get_history(self, limit: int = 20) -> List[str]:
        with self._lock:
            return [p.name for p in self._history[-limit:]]

    def get_summary(self) -> dict:
        cfg = self.config
        return {
            "profile": self._current.name,
            "description": cfg.description,
            "active_daemons": cfg.active_daemons,
            "max_orchestration_depth": cfg.max_orchestration_depth,
            "max_concurrent_actions": cfg.max_concurrent_actions,
            "features": {
                "tracing": cfg.enable_tracing,
                "observability": cfg.enable_observability,
                "policy_engine": cfg.enable_policy_engine,
                "chaos_testing": cfg.enable_chaos_testing,
                "predictive_scheduler": cfg.enable_predictive_scheduler,
                "event_governance": cfg.enable_event_governance,
                "runtime_inspector": cfg.enable_runtime_inspector,
                "shortcut_acceleration": cfg.enable_shortcut_acceleration,
            },
        }


_global_profile_manager: ProfileManager | None = None
_pm_lock = threading.Lock()


def get_profile_manager() -> ProfileManager:
    global _global_profile_manager
    with _pm_lock:
        if _global_profile_manager is None:
            _global_profile_manager = ProfileManager()
        return _global_profile_manager
