"""LLM provider abstraction layer.

This module provides a pluggable architecture for different LLM backends.
Currently supported: Claude Code CLI.
"""

from .base import LLMClient, LLMConfig, StreamEvent, ToolCall, ToolResult
from .claude_code import ClaudeCodeClient
from .registry import get_provider, list_providers, register_provider

__all__ = [
    "LLMClient",
    "LLMConfig",
    "StreamEvent",
    "ToolCall",
    "ToolResult",
    "ClaudeCodeClient",
    "get_provider",
    "list_providers",
    "register_provider",
]
