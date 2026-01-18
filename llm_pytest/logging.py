"""Logging configuration for llm-pytest.

This module provides a centralized logging system that replaces print()
statements with proper logging. The logger uses a custom formatter that
adds the [llm-pytest] prefix for consistency with the original output.

Usage:
    from llm_pytest.logging import logger, configure_logging

    # Configure at startup (usually in plugin.py)
    configure_logging(verbose=True)

    # Use throughout the codebase
    logger.info("Running test: %s", test_name)
    logger.debug("Tool call: %s", tool_name)
    logger.warning("Plugin cleanup failed: %s", error)
    logger.error("Test failed: %s", reason)
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

# Create the logger for llm-pytest
logger = logging.getLogger("llm_pytest")


class LLMPytestFormatter(logging.Formatter):
    """Custom formatter that adds [llm-pytest] prefix.

    Different prefixes are used for different log levels:
    - INFO: [llm-pytest]
    - DEBUG: [tool] or [claude] depending on context
    - WARNING: [llm-pytest] WARNING:
    - ERROR: [llm-pytest] ERROR:
    """

    # Prefix mapping for different contexts
    PREFIXES = {
        "tool_call": "[tool]",
        "tool_result": "[tool result]",
        "claude": "[claude]",
        "default": "[llm-pytest]",
    }

    def format(self, record: logging.LogRecord) -> str:
        # Check for context-specific prefix
        context = getattr(record, "context", "default")
        prefix = self.PREFIXES.get(context, self.PREFIXES["default"])

        # Add level indicator for warnings and errors
        if record.levelno >= logging.ERROR:
            prefix = f"{prefix} ERROR:"
        elif record.levelno >= logging.WARNING:
            prefix = f"{prefix} WARNING:"

        # Format the message
        message = record.getMessage()
        return f"{prefix} {message}"


class LLMPytestHandler(logging.StreamHandler):
    """Custom stream handler with immediate flushing.

    This handler ensures output is immediately visible, which is important
    for real-time feedback during test execution.
    """

    def __init__(self, stream: TextIO | None = None):
        super().__init__(stream or sys.stdout)
        self.setFormatter(LLMPytestFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_logging(verbose: bool = False) -> None:
    """Configure the llm-pytest logger.

    Args:
        verbose: If True, set level to DEBUG. Otherwise, set to INFO.
    """
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()

    # Set level based on verbosity
    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)

    # Add our custom handler
    handler = LLMPytestHandler()
    handler.setLevel(level)
    logger.addHandler(handler)

    # Prevent propagation to root logger (avoids duplicate output)
    logger.propagate = False


def log_tool_call(tool_name: str, args_str: str) -> None:
    """Log a tool call with appropriate formatting.

    Args:
        tool_name: Name of the tool being called
        args_str: String representation of the arguments
    """
    logger.debug(
        "%s(%s)",
        tool_name,
        args_str,
        extra={"context": "tool_call"},
    )


def log_tool_result(status: str, preview: str) -> None:
    """Log a tool result with appropriate formatting.

    Args:
        status: "OK" or "ERROR"
        preview: Preview of the result content
    """
    logger.debug(
        "%s: %s",
        status,
        preview,
        extra={"context": "tool_result"},
    )


def log_claude_output(text: str) -> None:
    """Log Claude's text output with appropriate formatting.

    Args:
        text: The text output from Claude
    """
    logger.debug(
        "%s",
        text,
        extra={"context": "claude"},
    )


# Configure with default settings on import
# This ensures basic logging works even without explicit configuration
configure_logging(verbose=False)
