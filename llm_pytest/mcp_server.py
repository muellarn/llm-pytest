"""Unified MCP server that loads all plugins.

This module provides:
1. Built-in tools (state management, sleep)
2. Dynamic loading of project plugins from tests/llm/plugins/
3. Automatic tool registration

The server is started automatically by the test runner.
"""

from __future__ import annotations

import asyncio
import atexit
import functools
import importlib.util
import inspect
import signal
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server import FastMCP

    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    FastMCP = None

from .plugin_base import LLMPlugin


class UnifiedMCPServer:
    """MCP server that combines built-in tools with project plugins."""

    def __init__(self, project_root: Path | None = None):
        """Initialize the unified server.

        Args:
            project_root: Root directory of the project (for finding plugins)
        """
        self.project_root = project_root or Path.cwd()
        self.plugins: list[LLMPlugin] = []
        self._mcp: FastMCP | None = None
        self._cleanup_registered: bool = False

    def _register_cleanup_handlers(self) -> None:
        """Register cleanup for all exit scenarios (normal, SIGTERM, SIGINT)."""
        if self._cleanup_registered:
            return

        atexit.register(self._sync_cleanup)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        self._cleanup_registered = True

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle termination signals by running cleanup."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.cleanup())
            else:
                loop.run_until_complete(self.cleanup())
        except Exception:
            pass
        sys.exit(128 + signum)

    def _sync_cleanup(self) -> None:
        """Synchronous wrapper for atexit."""
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.run_until_complete(self.cleanup())
        except Exception:
            pass

    def discover_plugins(self) -> list[LLMPlugin]:
        """Discover and load plugins from tests/llm/plugins/.

        Returns:
            List of loaded plugin instances
        """
        plugins_dir = self.project_root / "tests" / "llm" / "plugins"
        if not plugins_dir.exists():
            return []

        plugins = []
        for plugin_file in plugins_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue

            try:
                plugin = self._load_plugin(plugin_file)
                if plugin:
                    plugins.append(plugin)
            except Exception as e:
                print(f"Warning: Failed to load plugin {plugin_file}: {e}")

        return plugins

    def _load_plugin(self, plugin_path: Path) -> LLMPlugin | None:
        """Load a single plugin from a Python file.

        Args:
            plugin_path: Path to the plugin file

        Returns:
            Plugin instance or None if not a valid plugin
        """
        spec = importlib.util.spec_from_file_location(
            plugin_path.stem, plugin_path
        )
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[plugin_path.stem] = module
        spec.loader.exec_module(module)

        # Find LLMPlugin subclasses
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, LLMPlugin)
                and obj is not LLMPlugin
            ):
                return obj()

        return None

    def create_mcp_server(self) -> FastMCP:
        """Create the FastMCP server with all tools registered.

        Returns:
            Configured FastMCP instance
        """
        if not HAS_MCP:
            raise RuntimeError("MCP package not installed. Run: pip install mcp")

        self._mcp = FastMCP("llm_pytest")

        # Register built-in tools
        self._register_builtin_tools()

        # Discover and register project plugins
        self.plugins = self.discover_plugins()
        for plugin in self.plugins:
            self._register_plugin_methods(plugin)

        # Register cleanup handlers for graceful shutdown
        self._register_cleanup_handlers()

        return self._mcp

    def _register_builtin_tools(self) -> None:
        """Register built-in framework tools.

        Built-in tools are minimal - only state management and timing.
        All other functionality should be provided by plugins.
        """
        mcp = self._mcp

        # State management - shared storage for test state
        _state: dict[str, Any] = {}

        @mcp.tool()
        async def store_value(name: str, value: Any) -> dict:
            """Store a value with a name for later retrieval."""
            _state[name] = value
            return {"stored": name, "value": value}

        @mcp.tool()
        async def get_value(name: str, default: Any = None) -> dict:
            """Retrieve a stored value by name."""
            value = _state.get(name, default)
            return {"name": name, "value": value, "found": name in _state}

        @mcp.tool()
        async def list_values() -> dict:
            """List all stored value names."""
            return {"keys": list(_state.keys()), "count": len(_state)}

        @mcp.tool()
        async def sleep(seconds: float) -> dict:
            """Wait for specified seconds."""
            await asyncio.sleep(seconds)
            return {"slept": seconds}

    def _register_plugin_methods(self, plugin: LLMPlugin) -> None:
        """Register all async methods from a plugin as MCP tools.

        Args:
            plugin: The plugin instance
        """
        for method_name in dir(plugin):
            if method_name.startswith("_"):
                continue

            method = getattr(plugin, method_name)
            if not callable(method) or not asyncio.iscoroutinefunction(method):
                continue

            # Skip base class methods
            if method_name in ("get_tools", "call_tool", "cleanup"):
                continue

            # Create tool name with plugin prefix
            tool_name = f"{plugin.name}_{method_name}"

            # Register the bound method directly with custom name
            # FastMCP.tool(name=...) allows specifying the tool name
            self._mcp.tool(name=tool_name)(method)

    async def cleanup(self) -> None:
        """Cleanup all plugins with timeout protection."""
        for plugin in self.plugins:
            try:
                await asyncio.wait_for(plugin.cleanup(), timeout=5.0)
            except asyncio.TimeoutError:
                # Use print here since logger may not be available during shutdown
                print(f"[llm-pytest] WARNING: Plugin {plugin.name} cleanup timed out")
            except Exception as e:
                print(f"[llm-pytest] WARNING: Plugin {plugin.name} cleanup failed: {e}")


def run_server(project_root: str | None = None) -> None:
    """Run the unified MCP server.

    Args:
        project_root: Optional project root path
    """
    if not HAS_MCP:
        print("Error: MCP package not installed.")
        print("Install with: pip install mcp")
        sys.exit(1)

    root = Path(project_root) if project_root else Path.cwd()
    server = UnifiedMCPServer(root)
    mcp = server.create_mcp_server()
    mcp.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="llm-pytest MCP server")
    parser.add_argument(
        "--project-root",
        type=str,
        help="Project root directory",
    )
    args = parser.parse_args()

    run_server(args.project_root)
