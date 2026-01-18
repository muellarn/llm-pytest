"""Base class for llm-pytest plugins.

Plugins extend the framework with project-specific MCP tools.
They are discovered automatically from tests/llm/plugins/ directory.

Example plugin:

    from llm_pytest import LLMPlugin

    class DatabasePlugin(LLMPlugin):
        name = "database"

        async def connect(self, connection_string: str) -> dict:
            '''Connect to the database.'''
            ...

        async def query(self, sql: str) -> dict:
            '''Execute a SQL query and return results.'''
            ...
"""

from __future__ import annotations

import asyncio
import inspect
from abc import ABC
from typing import Any, Callable, get_type_hints


class LLMPlugin(ABC):
    """Base class for llm-pytest plugins.

    Subclass this to create project-specific MCP tools.
    All public async methods become MCP tools automatically.

    Attributes:
        name: The plugin name (used as MCP server name and tool prefix)
    """

    name: str = "plugin"

    def __init__(self):
        self._state: dict[str, Any] = {}

    def get_tools(self) -> list[dict[str, Any]]:
        """Get all tool definitions from this plugin.

        Returns:
            List of tool definitions with name, description, and parameters
        """
        tools = []
        for method_name in dir(self):
            if method_name.startswith("_"):
                continue

            method = getattr(self, method_name)
            if not callable(method) or not asyncio.iscoroutinefunction(method):
                continue

            # Skip base class methods
            if method_name in ("get_tools", "call_tool", "cleanup"):
                continue

            # Build tool definition
            sig = inspect.signature(method)
            doc = inspect.getdoc(method) or ""

            # Parse parameters
            properties = {}
            required = []

            try:
                hints = get_type_hints(method)
            except Exception:
                hints = {}

            for param_name, param in sig.parameters.items():
                if param_name == "self":
                    continue

                param_type = hints.get(param_name, Any)
                json_type = self._python_type_to_json(param_type)

                properties[param_name] = {
                    "type": json_type,
                    "description": f"Parameter {param_name}",
                }

                if param.default == inspect.Parameter.empty:
                    required.append(param_name)
                else:
                    properties[param_name]["default"] = param.default

            tools.append({
                "name": f"{self.name}_{method_name}",
                "description": doc.split("\n")[0] if doc else method_name,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            })

        return tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool by name.

        Args:
            tool_name: The tool name (with or without plugin prefix)
            arguments: The tool arguments

        Returns:
            The tool result
        """
        # Strip plugin prefix if present
        if tool_name.startswith(f"{self.name}_"):
            method_name = tool_name[len(self.name) + 1:]
        else:
            method_name = tool_name

        method = getattr(self, method_name, None)
        if method is None or not asyncio.iscoroutinefunction(method):
            raise ValueError(f"Unknown tool: {tool_name}")

        return await method(**arguments)

    async def cleanup(self) -> None:
        """Cleanup resources. Override in subclass if needed."""
        pass

    @staticmethod
    def _python_type_to_json(python_type: type) -> str:
        """Convert Python type to JSON schema type."""
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }

        # Handle Optional, Union, etc.
        origin = getattr(python_type, "__origin__", None)
        if origin is not None:
            # For Optional[X], Union[X, None], etc.
            args = getattr(python_type, "__args__", ())
            for arg in args:
                if arg is not type(None):
                    return type_map.get(arg, "string")

        return type_map.get(python_type, "string")
