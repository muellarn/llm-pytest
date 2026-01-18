"""Base MCP server with core tools for llm-pytest.

This module provides minimal built-in tools:
- State persistence (store_value, get_value, list_values)
- Sleep/wait functionality

All other functionality (HTTP, assertions, etc.) should be implemented
as project-specific plugins. This keeps the framework lean and focused
on orchestration rather than providing utility functions.

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
from typing import Any

try:
    from mcp.server import Server

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

# Session-scoped storage for values persisted across test steps
# This is module-level to allow state to persist across tool calls within a session
_stored_values: dict[str, Any] = {}


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
async def store_value(name: str, value: Any) -> dict[str, Any]:
    """Store a value for later retrieval within this test session.

    Use this to save results from one step for use in later steps.
    Values are cleared when the test session ends.

    Args:
        name: Name to store the value under
        value: The value to store

    Returns:
        Dict with stored name and value
    """
    _stored_values[name] = value
    return {"stored": name, "value": value}


@server.tool()
async def get_value(name: str, default: Any = None) -> dict[str, Any]:
    """Retrieve a previously stored value.

    Returns the stored value or the default if not found.

    Args:
        name: Name of the value to retrieve
        default: Default value if not found (defaults to None)

    Returns:
        Dict with name, value, and whether it was found
    """
    value = _stored_values.get(name, default)
    return {"name": name, "value": value, "found": name in _stored_values}


@server.tool()
async def list_values() -> dict[str, Any]:
    """List all stored value names in this test session.

    Returns:
        Dict with list of names and count
    """
    return {"keys": list(_stored_values.keys()), "count": len(_stored_values)}


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
