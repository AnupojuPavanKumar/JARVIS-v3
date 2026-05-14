# core/capabilities/__init__.py
"""
Capability registry — dynamic detection of system capabilities,
installed apps, GPU, audio endpoints, Ollama availability, model inventory.
"""
from core.capabilities.registry import CapabilityRegistry, Capability, get_capability_registry

__all__ = ["CapabilityRegistry", "Capability", "get_capability_registry"]
