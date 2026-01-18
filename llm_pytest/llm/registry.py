"""LLM provider registry for dynamic provider selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import LLMClient

_PROVIDERS: dict[str, type["LLMClient"]] = {}


def register_provider(name: str):
    """Decorator to register an LLM provider.

    Usage:
        @register_provider("my_provider")
        class MyProvider(LLMClient):
            ...
    """

    def decorator(cls: type["LLMClient"]) -> type["LLMClient"]:
        _PROVIDERS[name] = cls
        return cls

    return decorator


def get_provider(name: str) -> type["LLMClient"]:
    """Get a provider class by name.

    Args:
        name: Provider name (e.g., "claude_code")

    Returns:
        The provider class

    Raises:
        ValueError: If provider not found
    """
    if name not in _PROVIDERS:
        available = ", ".join(_PROVIDERS.keys()) or "(none)"
        raise ValueError(f"Unknown LLM provider: {name}. Available: {available}")
    return _PROVIDERS[name]


def list_providers() -> list[str]:
    """List all registered provider names."""
    return list(_PROVIDERS.keys())
