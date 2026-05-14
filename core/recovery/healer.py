# core/recovery/healer.py
"""
Self-healing execution recovery — intelligent retry, alternate resolution,
stale cache repair, broken shortcut recovery, dead subprocess cleanup.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

log = logging.getLogger("SelfHealer")


class RecoveryStrategy(Enum):
    RETRY = auto()
    REFRESH_REGISTRY = auto()
    ALTERNATE_RESOLUTION = auto()
    CACHE_REPAIR = auto()
    FALLBACK_PATH = auto()
    SKIP = auto()


@dataclass
class RecoveryAction:
    """A single recovery attempt."""
    strategy: RecoveryStrategy
    target: str
    success: bool = False
    attempted_at: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class HealerConfig:
    """Configuration for self-healing behavior."""
    max_retries: int = 3
    retry_delay_sec: float = 1.0
    registry_refresh_max_age: float = 300.0
    alternate_resolution_tries: int = 3
    deadlock_timeout: float = 30.0
    enable_auto_refresh: bool = True


class SelfHealer:
    """
    Automatic recovery logic for execution failures.
    Retry intelligently, refresh registry, attempt alternate resolution,
    recover gracefully without infinite loops.
    """

    def __init__(self, config: HealerConfig | None = None):
        self.config = config or HealerConfig()
        self._recovery_log: deque[RecoveryAction] = deque(maxlen=500)
        self._lock = threading.RLock()
        self._retry_counts: dict[str, int] = {}
        self._registry_last_refresh: float = 0.0
        self._broken_paths: set[str] = set()

    def should_retry(self, target: str) -> bool:
        """Check if a target should be retried based on retry count."""
        count = self._retry_counts.get(target, 0)
        return count < self.config.max_retries

    def record_attempt(self, target: str, success: bool):
        """Record an attempt, incrementing retry count on failure."""
        with self._lock:
            if success:
                self._retry_counts.pop(target, None)
                return
            self._retry_counts[target] = self._retry_counts.get(target, 0) + 1

    def heal_missing_executable(self, path: str) -> tuple[bool, str]:
        """Heal a missing executable by attempting alternate resolution."""
        if path in self._broken_paths:
            return False, "already known to be broken"
        original_path = path
        strategies: list[tuple[RecoveryStrategy, Callable[[str], tuple[bool, str]]]] = [
            (RecoveryStrategy.REFRESH_REGISTRY, self._try_registry_refresh),
            (RecoveryStrategy.ALTERNATE_RESOLUTION, self._try_alternate_resolution),
            (RecoveryStrategy.CACHE_REPAIR, self._try_cache_repair),
            (RecoveryStrategy.FALLBACK_PATH, self._try_fallback_path),
        ]
        for strategy, fn in strategies:
            t0 = time.time()
            success, result = fn(path)
            duration = (time.time() - t0) * 1000
            action = RecoveryAction(
                strategy=strategy, target=original_path,
                success=success, duration_ms=duration, error=result if not success else None,
            )
            with self._lock:
                self._recovery_log.append(action)
            if success:
                self._broken_paths.discard(original_path)
                return True, result
        with self._lock:
            self._broken_paths.add(original_path)
        return False, "all recovery strategies exhausted"

    def _try_registry_refresh(self, path: str) -> tuple[bool, str]:
        """Refresh the app registry and retry."""
        if not self.config.enable_auto_refresh:
            return False, "auto-refresh disabled"
        try:
            from core.apps.app_registry import get_app_registry
            reg = get_app_registry()
            if hasattr(reg, "refresh"):
                reg.refresh(force=True)
            result = reg.resolve(os.path.basename(path).split(".")[0])
            if result and os.path.exists(result):
                return True, f"registry refreshed, found at {result}"
            return False, "registry refresh did not find alternate"
        except Exception as e:
            return False, f"registry refresh error: {e}"

    def _try_alternate_resolution(self, path: str) -> tuple[bool, str]:
        """Try alternate paths using Windows 'where' command."""
        try:
            import subprocess
            name = os.path.basename(path).split(".")[0]
            result = subprocess.run(
                ["where", name], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                candidates = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                for candidate in candidates:
                    if os.path.exists(candidate) and candidate.lower() != path.lower():
                        return True, f"alternate found at {candidate}"
            return False, "no alternate found via where"
        except Exception as e:
            return False, f"where resolution error: {e}"

    def _try_cache_repair(self, path: str) -> tuple[bool, str]:
        """Repair stale cache entry."""
        try:
            from core.apps.app_registry import get_app_registry
            reg = get_app_registry()
            name = os.path.basename(path).split(".")[0]
            for key in list(reg._cache.keys()):
                if key == name and not os.path.exists(reg._cache[key]):
                    reg._cache.pop(key, None)
            return False, "cache repair attempted"
        except Exception as e:
            return False, f"cache repair error: {e}"

    def _try_fallback_path(self, path: str) -> tuple[bool, str]:
        """Try common fallback paths."""
        name = os.path.basename(path)
        fallbacks = [
            os.path.join(os.path.expandvars(r"%LOCALAPPDATA%\Programs"), name),
            os.path.join(os.path.expandvars(r"%APPDATA%"), name),
            os.path.join(os.path.expandvars(r"%PROGRAMFILES%"), name),
        ]
        for fb in fallbacks:
            if os.path.exists(fb):
                return True, f"fallback found at {fb}"
        return False, "no fallback paths exist"

    def heal_stale_cache(self, identifier: str) -> tuple[bool, str]:
        """Heal a stale cache entry by forcing re-resolution."""
        try:
            from core.apps.app_registry import get_app_registry
            reg = get_app_registry()
            if hasattr(reg, "refresh"):
                reg.refresh(force=True)
            result = reg.resolve(identifier)
            if result and os.path.exists(result):
                return True, f"stale cache healed, resolved to {result}"
            return False, "stale cache repair failed"
        except Exception as e:
            return False, f"stale cache repair error: {e}"

    def heal_broken_shortcut(self, lnk_path: str) -> tuple[bool, str]:
        """Attempt to recover from a broken shortcut (.lnk)."""
        if not os.path.exists(lnk_path):
            return False, "shortcut file does not exist"
        try:
            target = self._resolve_lnk(lnk_path)
            if target and os.path.exists(target):
                return True, f"shortcut resolved to {target}"
            return False, "shortcut resolution failed"
        except Exception as e:
            return False, f"shortcut recovery error: {e}"

    def _resolve_lnk(self, lnk_path: str) -> str | None:
        """Resolve a .lnk shortcut without COM."""
        try:
            with open(lnk_path, "rb") as f:
                data = f.read()
            if b"D@\xe3" in data:
                parts = []
                offset = data.index(b"D@\xe3")
                i = offset + 18
                while i < len(data) - 1:
                    w = int.from_bytes(data[i:i+2], "little")
                    if w == 0:
                        break
                    try:
                        parts.append(data[i:i+w*2].decode("utf-16-le").rstrip("\x00"))
                    except Exception:
                        break
                    i += w * 2 + 2
                if parts:
                    target = parts[0].replace("\\\\", "\\")
                    if target.lower().endswith(".exe") and os.path.exists(target):
                        return target
        except Exception:
            pass
        return None

    def heal_dead_subprocess(self, pid: int) -> tuple[bool, str]:
        """Clean up a dead subprocess."""
        try:
            import ctypes
            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_VM_READ = 0x0010
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                if exit_code.value != 259:
                    return True, f"process {pid} confirmed dead (exit code {exit_code.value})"
            return False, "process still running or cannot determine state"
        except Exception as e:
            return False, f"dead subprocess check error: {e}"

    def get_recovery_log(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [{"strategy": a.strategy.name, "target": a.target, "success": a.success,
                     "duration_ms": round(a.duration_ms, 2), "error": a.error}
                    for a in list(reversed(self._recovery_log))[:limit]]

    def stats(self) -> dict:
        with self._lock:
            total = len(self._recovery_log)
            success = sum(1 for a in self._recovery_log if a.success)
            by_strategy = {}
            for a in self._recovery_log:
                by_strategy[a.strategy.name] = by_strategy.get(a.strategy.name, 0) + 1
            return {
                "total_recoveries": total,
                "success_rate": round(success / total, 3) if total > 0 else 0,
                "by_strategy": by_strategy,
                "broken_paths_tracked": len(self._broken_paths),
                "retry_counts": dict(self._retry_counts),
            }


_global_healer: SelfHealer | None = None
_healer_lock = threading.Lock()


def get_self_healer() -> SelfHealer:
    global _global_healer
    with _healer_lock:
        if _global_healer is None:
            _global_healer = SelfHealer()
        return _global_healer
