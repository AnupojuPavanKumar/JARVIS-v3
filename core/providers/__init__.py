# core/providers/__init__.py
"""
Provider isolation layer — P8.
Unified provider contracts, standardized inference interface,
model capability metadata, fallback routing, provider health checks.
"""
from core.providers.base import (
    ProviderCapability, ModelMetadata, InferenceRequest,
    InferenceResponse, ProviderHealth, BaseProvider,
    get_provider_registry, ProviderRegistry,
)

__all__ = [
    "ProviderCapability", "ModelMetadata", "InferenceRequest",
    "InferenceResponse", "ProviderHealth", "BaseProvider",
    "get_provider_registry", "ProviderRegistry",
]
