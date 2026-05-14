# core/providers/base.py
"""
Provider isolation layer base — P8.
Standardized contracts for Ollama, Kimi, Claude, Gemini, local models.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

log = logging.getLogger("ProviderRegistry")


class ProviderCapability(Enum):
    TEXT = auto()
    VISION = auto()
    TOOL_USE = auto()
    STREAMING = auto()
    FUNCTION_CALLING = auto()
    LONG_CONTEXT = auto()
    MULTIMODAL = auto()


@dataclass(frozen=True)
class ModelMetadata:
    name: str
    provider: str
    capabilities: tuple[ProviderCapability, ...]
    max_tokens: int
    context_window: int
    preferred_roles: tuple[str, ...]
    vram_mb: float
    latency_class: str = "unknown"


@dataclass
class InferenceRequest:
    model: str
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int = 512
    stream: bool = False
    timeout_sec: float = 60.0
    metadata: dict = field(default_factory=dict)


@dataclass
class InferenceResponse:
    content: str
    model: str
    provider: str
    latency_ms: float
    tokens_used: int = 0
    finish_reason: str = "stop"
    error: str | None = None


class ProviderHealth(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    UNHEALTHY = auto()
    UNKNOWN = auto()


@dataclass
class ProviderStatus:
    name: str
    health: ProviderHealth
    latency_ms: float
    failure_count: int = 0
    last_used: float = 0.0
    active_requests: int = 0


class BaseProvider:
    """Abstract base for all AI providers."""
    name: str = "base"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth.UNKNOWN

    def list_models(self) -> list[ModelMetadata]:
        return []

    def inference(self, request: InferenceRequest) -> InferenceResponse:
        raise NotImplementedError


class ProviderRegistry:
    """
    Provider isolation layer.
    Manages multiple AI providers, handles failover, capability-aware routing.
    """

    def __init__(self):
        self._providers: dict[str, BaseProvider] = {}
        self._models: dict[str, ModelMetadata] = {}
        self._provider_status: dict[str, ProviderStatus] = {}
        self._lock = threading.RLock()
        self._active_provider: str | None = None
        self._fallback_chain: list[str] = []
        self._last_used: dict[str, float] = {}

    def register(self, provider: BaseProvider):
        """Register a provider and its models."""
        with self._lock:
            self._providers[provider.name] = provider
            for model in provider.list_models():
                self._models[model.name] = model
            self._provider_status[provider.name] = ProviderStatus(
                name=provider.name, health=ProviderHealth.UNKNOWN, latency_ms=0.0,
            )
        log.info(f"[ProviderRegistry] Registered provider: {provider.name} with {len(provider.list_models())} models")

    def set_active(self, name: str):
        with self._lock:
            if name in self._providers:
                self._active_provider = name
                self._last_used[name] = time.time()

    def set_fallback_chain(self, chain: list[str]):
        with self._lock:
            self._fallback_chain = chain

    def get_provider_for_model(self, model_name: str) -> Optional[BaseProvider]:
        with self._lock:
            meta = self._models.get(model_name)
        if meta:
            with self._lock:
                return self._providers.get(meta.provider)
        return None

    def infer(self, request: InferenceRequest) -> InferenceResponse:
        """Attempt inference with fallback chain."""
        chain = []
        with self._lock:
            if self._active_provider and self._active_provider in self._providers:
                chain.append(self._active_provider)
            chain.extend(self._fallback_chain)
        errors = []
        for provider_name in chain:
            with self._lock:
                p = self._providers.get(provider_name)
            if not p:
                continue
            try:
                t0 = time.time()
                response = p.inference(request)
                response.latency_ms = (time.time() - t0) * 1000
                with self._lock:
                    self._last_used[provider_name] = time.time()
                    status = self._provider_status.get(provider_name)
                    if status:
                        status.last_used = time.time()
                        status.active_requests = max(0, status.active_requests - 1)
                return response
            except Exception as e:
                errors.append(f"{provider_name}: {str(e)[:50]}")
                with self._lock:
                    status = self._provider_status.get(provider_name)
                    if status:
                        status.failure_count += 1
                        status.health = ProviderHealth.DEGRADED
                log.warning(f"[ProviderRegistry] Provider '{provider_name}' failed: {e}")
        return InferenceResponse(
            content="", model=request.model, provider="none",
            latency_ms=0, error="; ".join(errors),
        )

    def get_healthy_provider(self) -> Optional[BaseProvider]:
        with self._lock:
            for name, p in self._providers.items():
                status = self._provider_status.get(name)
                if status and status.health in (ProviderHealth.HEALTHY, ProviderHealth.DEGRADED):
                    return p
        return None

    def get_capable_provider(self, capability: ProviderCapability) -> list[BaseProvider]:
        capable = []
        with self._lock:
            for name, p in self._providers.items():
                for model in p.list_models():
                    if capability in model.capabilities:
                        capable.append(p)
                        break
        return capable

    def health_report(self) -> dict:
        with self._lock:
            return {
                name: {
                    "health": s.health.name,
                    "latency_ms": s.latency_ms,
                    "failures": s.failure_count,
                    "models": len([m for m in self._models.values() if m.provider == name]),
                }
                for name, s in self._provider_status.items()
            }

    def stats(self) -> dict:
        with self._lock:
            return {
                "providers": len(self._providers),
                "models": len(self._models),
                "active_provider": self._active_provider,
                "fallback_chain": self._fallback_chain,
            }


_global_registry: ProviderRegistry | None = None
_pr_lock = threading.Lock()


def get_provider_registry() -> ProviderRegistry:
    global _global_registry
    with _pr_lock:
        if _global_registry is None:
            _global_registry = ProviderRegistry()
        return _global_registry
