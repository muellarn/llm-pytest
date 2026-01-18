"""Base MCP server with common tools for llm-pytest.

This module provides generic tools that can be used across different projects:
- HTTP requests (GET, POST)
- Sleep/wait functionality
- Basic assertions

Project-specific tools (like browser automation) should be implemented
in separate MCP servers within the project.

Usage:
    Register in ~/.claude/settings.json:
    {
        "mcpServers": {
            "llm_pytest": {
                "command": "python",
                "args": ["-m", "llm_pytest.mcp.base_server"]
            }
        }
    }
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

try:
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    HAS_MCP = True
except ImportError:
    HAS_MCP = False

    # Stub classes for when MCP is not installed
    class Server:
        def __init__(self, name: str):
            self.name = name

        def tool(self):
            def decorator(func):
                return func

            return decorator


server = Server("llm_pytest")


@server.tool()
async def http_get(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Make HTTP GET request.

    Args:
        url: The URL to fetch
        headers: Optional HTTP headers

    Returns:
        Dict with status_code, body, and headers
    """
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers or {})
        return {
            "status_code": response.status_code,
            "body": response.text[:10000],  # Limit response size
            "headers": dict(response.headers),
        }


@server.tool()
async def http_post(
    url: str,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Make HTTP POST request.

    Args:
        url: The URL to post to
        data: JSON data to send
        headers: Optional HTTP headers

    Returns:
        Dict with status_code, body, and headers
    """
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=data, headers=headers or {})
        return {
            "status_code": response.status_code,
            "body": response.text[:10000],
            "headers": dict(response.headers),
        }


@server.tool()
async def sleep(seconds: float) -> dict[str, float]:
    """Wait for specified seconds.

    Args:
        seconds: Number of seconds to wait

    Returns:
        Dict confirming the sleep duration
    """
    await asyncio.sleep(seconds)
    return {"slept": seconds}


@server.tool()
async def assert_equals(
    actual: Any,
    expected: Any,
    message: str = "",
) -> dict[str, Any]:
    """Assert that two values are equal.

    Args:
        actual: The actual value
        expected: The expected value
        message: Optional failure message

    Returns:
        Dict with passed status and details
    """
    passed = actual == expected
    return {
        "passed": passed,
        "actual": actual,
        "expected": expected,
        "message": message if not passed else "Assertion passed",
    }


@server.tool()
async def assert_contains(
    container: str | list | dict,
    item: Any,
    message: str = "",
) -> dict[str, Any]:
    """Assert that a container contains an item.

    Args:
        container: The container (string, list, or dict)
        item: The item to look for
        message: Optional failure message

    Returns:
        Dict with passed status and details
    """
    passed = item in container
    return {
        "passed": passed,
        "container_type": type(container).__name__,
        "item": item,
        "message": message if not passed else "Assertion passed",
    }


@server.tool()
async def assert_true(
    condition: bool,
    message: str = "",
) -> dict[str, Any]:
    """Assert that a condition is true.

    Args:
        condition: The condition to check
        message: Optional failure message

    Returns:
        Dict with passed status
    """
    return {
        "passed": bool(condition),
        "message": message if not condition else "Assertion passed",
    }


@server.tool()
async def compare_values(
    value1: Any,
    value2: Any,
    tolerance: float = 0.0,
) -> dict[str, Any]:
    """Compare two values with optional tolerance for numbers.

    Args:
        value1: First value
        value2: Second value
        tolerance: Tolerance for numeric comparison (as percentage, e.g., 0.05 = 5%)

    Returns:
        Dict with comparison results
    """
    if isinstance(value1, (int, float)) and isinstance(value2, (int, float)):
        if tolerance > 0:
            # Calculate relative difference
            if value2 == 0:
                diff_percent = float("inf") if value1 != 0 else 0
            else:
                diff_percent = abs(value1 - value2) / abs(value2)

            return {
                "equal": diff_percent <= tolerance,
                "value1": value1,
                "value2": value2,
                "difference": abs(value1 - value2),
                "difference_percent": diff_percent * 100,
                "tolerance_percent": tolerance * 100,
            }
        else:
            return {
                "equal": value1 == value2,
                "value1": value1,
                "value2": value2,
                "difference": abs(value1 - value2),
            }
    else:
        return {
            "equal": value1 == value2,
            "value1": value1,
            "value2": value2,
            "types": [type(value1).__name__, type(value2).__name__],
        }


@server.tool()
async def store_value(name: str, value: Any) -> dict[str, Any]:
    """Store a value for later retrieval.

    Note: This is a placeholder - actual state management
    happens in the LLM's context.

    Args:
        name: Name to store the value under
        value: The value to store

    Returns:
        Confirmation of storage
    """
    return {
        "stored": True,
        "name": name,
        "value_type": type(value).__name__,
    }


def main():
    """Run the MCP server."""
    if not HAS_MCP:
        print("Error: MCP package not installed.")
        print("Install with: pip install llm-pytest[mcp]")
        import sys

        sys.exit(1)

    import mcp

    mcp.run(server)


if __name__ == "__main__":
    main()
