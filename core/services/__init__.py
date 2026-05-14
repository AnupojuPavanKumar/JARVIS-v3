# core/services/__init__.py
"""
Lightweight service container with lifecycle management.
Provides dependency injection without heavy frameworks.
"""
from core.services.container import ServiceContainer, service_container

__all__ = ["ServiceContainer", "service_container", "inject", "ServiceLifecycle"]
