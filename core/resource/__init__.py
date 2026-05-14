# core/resource/__init__.py
"""
Resource monitoring layer for adaptive scheduling and overload prevention.
Critical for RTX 4050 laptop VRAM/CPU management.
"""
from core.resource.monitor import ResourceMonitor, ResourceProfile, get_resource_monitor

__all__ = ["ResourceMonitor", "ResourceProfile", "get_resource_monitor"]
