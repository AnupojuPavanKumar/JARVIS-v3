# core/recovery/__init__.py
"""
Self-healing execution recovery — automatic retry logic, registry refresh,
alternate resolution, missing executable recovery, stale cache repair.
"""
from core.recovery.healer import SelfHealer, RecoveryStrategy, get_self_healer

__all__ = ["SelfHealer", "RecoveryStrategy", "get_self_healer"]
