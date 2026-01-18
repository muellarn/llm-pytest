"""Base classes for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from ..models import Verdict


@dataclass
class LLMConfig:
    """Configuration for an LLM provider."""

    provider: str = "claude_code"
    model: str | None = None
    api_key: str | None = None
    timeout: int = 120
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    """Represents an LLM's request to call a tool."""

    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class ToolResult:
    """Result of a tool execution."""

    content: str
    is_error: bool = False


@dataclass
class StreamEvent:
    """Event emitted during streaming execution."""

    type: str  # "init", "text", "tool_call", "tool_result", "done", "error"
    data: dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    """Abstract base class for LLM providers.

    Implement this class to add support for a new LLM backend.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this provider."""
        ...

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        *,
        timeout: int = 120,
        stream: bool = False,
    ) -> str | AsyncIterator[StreamEvent]:
        """Execute a prompt and return the result.

        Args:
            prompt: The prompt to execute
            timeout: Timeout in seconds
            stream: If True, return an async iterator of StreamEvents

        Returns:
            If stream=False: The final result as a string
            If stream=True: An async iterator yielding StreamEvents
        """
        ...

    @abstractmethod
    def parse_verdict(self, output: str) -> "Verdict":
        """Parse LLM output into a Verdict object.

        Args:
            output: Raw output from the LLM

        Returns:
            Parsed Verdict object
        """
        ...
