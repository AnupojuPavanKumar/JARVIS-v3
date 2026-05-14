# core/orchestration/modes.py
"""
System mode management — P11.
NORMAL, GAMING, LOW_POWER, DEVELOPMENT, PRIVACY, PERFORMANCE, SILENT.
Each mode controls: model selection, resource limits, background tasks,
logging verbosity, inference complexity, voice behavior.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

log = logging.getLogger("SystemMode")


class SystemMode(Enum):
    NORMAL = "normal"
    GAMING = "gaming"
    LOW_POWER = "low_power"
    DEVELOPMENT = "development"
    PRIVACY = "privacy"
    PERFORMANCE = "performance"
    SILENT = "silent"


@dataclass
class ModeProfile:
    """Profile configuration for a system mode."""
    mode: SystemMode
    max_concurrent_actions: int
    max_inference_concurrency: int
    throttle_heavy_reasoning: bool
    disable_background_agents: bool
    enable_verbose_logging: bool
    model_priority: str
    resource_reserve_mb: float
    audio_behavior: str
    ui_responsiveness: float


MODE_PROFILES: dict[SystemMode, ModeProfile] = {
    SystemMode.NORMAL: ModeProfile(
        mode=SystemMode.NORMAL,
        max_concurrent_actions=20, max_inference_concurrency=2,
        throttle_heavy_reasoning=False, disable_background_agents=False,
        enable_verbose_logging=False, model_priority="default",
        resource_reserve_mb=512.0, audio_behavior="normal", ui_responsiveness=1.0,
    ),
    SystemMode.GAMING: ModeProfile(
        mode=SystemMode.GAMING,
        max_concurrent_actions=5, max_inference_concurrency=1,
        throttle_heavy_reasoning=True, disable_background_agents=True,
        enable_verbose_logging=False, model_priority="lightweight",
        resource_reserve_mb=1024.0, audio_behavior="minimal", ui_responsiveness=1.0,
    ),
    SystemMode.LOW_POWER: ModeProfile(
        mode=SystemMode.LOW_POWER,
        max_concurrent_actions=5, max_inference_concurrency=1,
        throttle_heavy_reasoning=True, disable_background_agents=True,
        enable_verbose_logging=False, model_priority="minimal",
        resource_reserve_mb=256.0, audio_behavior="silent", ui_responsiveness=0.5,
    ),
    SystemMode.DEVELOPMENT: ModeProfile(
        mode=SystemMode.DEVELOPMENT,
        max_concurrent_actions=20, max_inference_concurrency=2,
        throttle_heavy_reasoning=False, disable_background_agents=False,
        enable_verbose_logging=True, model_priority="default",
        resource_reserve_mb=512.0, audio_behavior="normal", ui_responsiveness=1.0,
    ),
    SystemMode.PRIVACY: ModeProfile(
        mode=SystemMode.PRIVACY,
        max_concurrent_actions=10, max_inference_concurrency=1,
        throttle_heavy_reasoning=True, disable_background_agents=True,
        enable_verbose_logging=False, model_priority="local_only",
        resource_reserve_mb=512.0, audio_behavior="normal", ui_responsiveness=1.0,
    ),
    SystemMode.PERFORMANCE: ModeProfile(
        mode=SystemMode.PERFORMANCE,
        max_concurrent_actions=30, max_inference_concurrency=4,
        throttle_heavy_reasoning=False, disable_background_agents=False,
        enable_verbose_logging=False, model_priority="high_performance",
        resource_reserve_mb=256.0, audio_behavior="normal", ui_responsiveness=1.0,
    ),
    SystemMode.SILENT: ModeProfile(
        mode=SystemMode.SILENT,
        max_concurrent_actions=3, max_inference_concurrency=1,
        throttle_heavy_reasoning=True, disable_background_agents=True,
        enable_verbose_logging=False, model_priority="minimal",
        resource_reserve_mb=512.0, audio_behavior="muted", ui_responsiveness=1.0,
    ),
}


@dataclass
class ModeTransition:
    mode: SystemMode
    reason: str
    timestamp: float = field(default_factory=time.time)
    automatic: bool = False
    from_mode: SystemMode | None = None


class SystemModeManager:
    """
    Manages system operational modes.
    Supports automatic switching, manual override, mode transition rules.
    """

    def __init__(self):
        self._current_mode: SystemMode = SystemMode.NORMAL
        self._profile: ModeProfile = MODE_PROFILES[self._current_mode]
        self._lock = threading.RLock()
        self._transition_history: deque[ModeTransition] = deque(maxlen=50)
        self._on_mode_change: list[Callable[[SystemMode, SystemMode], None]] = []
        self._auto_switch_enabled: bool = True
        self._auto_switch_rules: list[Callable[[], SystemMode | None]] = []

    @property
    def current_mode(self) -> SystemMode:
        with self._lock:
            return self._current_mode

    @property
    def profile(self) -> ModeProfile:
        with self._lock:
            return self._profile

    def set_mode(self, mode: SystemMode, reason: str = "manual", automatic: bool = False):
        """Switch to a different system mode."""
        with self._lock:
            if mode == self._current_mode:
                return
            old_mode = self._current_mode
            self._current_mode = mode
            self._profile = MODE_PROFILES[mode]
            t = ModeTransition(mode=mode, reason=reason, automatic=automatic, from_mode=old_mode)
            self._transition_history.append(t)
        log.info(f"[SystemMode] Switched {old_mode.value} -> {mode.value} ({reason})")
        for cb in self._on_mode_change:
            try:
                cb(old_mode, mode)
            except Exception as e:
                log.warning(f"[SystemMode] mode change callback error: {e}")

    def on_mode_change(self, callback: Callable[[SystemMode, SystemMode], None]):
        """Register a mode change callback."""
        self._on_mode_change.append(callback)

    def register_auto_rule(self, rule: Callable[[], SystemMode | None]):
        """Register an automatic mode switching rule."""
        self._auto_switch_rules.append(rule)

    def check_auto_switch(self):
        """Evaluate auto-switch rules. Call periodically."""
        if not self._auto_switch_enabled:
            return
        for rule in self._auto_switch_rules:
            try:
                suggested = rule()
                if suggested and suggested != self._current_mode:
                    self.set_mode(suggested, reason=f"auto: {rule.__name__}", automatic=True)
                    break
            except Exception as e:
                log.debug(f"[SystemMode] auto rule error: {e}")

    def enable_auto_switch(self, enabled: bool):
        self._auto_switch_enabled = enabled

    def get_transition_history(self, limit: int = 10) -> list[ModeTransition]:
        with self._lock:
            return list(self._transition_history)[-limit:]

    def can_perform_action(self, action_type: str) -> bool:
        """Check if an action type is allowed in the current mode."""
        p = self.profile
        if action_type == "heavy_inference" and p.throttle_heavy_reasoning:
            return False
        if action_type == "background_agent" and p.disable_background_agents:
            return False
        return True

    def get_model_priority(self) -> str:
        return self.profile.model_priority


_global_mode_manager: SystemModeManager | None = None
_mode_lock = threading.Lock()


def get_mode_manager() -> SystemModeManager:
    global _global_mode_manager
    with _mode_lock:
        if _global_mode_manager is None:
            _global_mode_manager = SystemModeManager()
        return _global_mode_manager
