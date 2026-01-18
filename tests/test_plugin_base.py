"""Tests for plugin base class in llm_pytest.plugin_base."""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from llm_pytest.plugin_base import LLMPlugin


class SamplePlugin(LLMPlugin):
    """A sample plugin for testing."""

    name = "sample"

    async def simple_method(self, value: str) -> dict:
        """A simple method that returns the input."""
        return {"input": value}

    async def method_with_defaults(
        self,
        required: str,
        optional: str = "default",
        number: int = 42,
    ) -> dict:
        """A method with optional parameters."""
        return {
            "required": required,
            "optional": optional,
            "number": number,
        }

    async def no_params(self) -> dict:
        """A method with no parameters."""
        return {"result": "success"}

    async def typed_params(
        self,
        text: str,
        count: int,
        ratio: float,
        flag: bool,
        items: list,
        config: dict,
    ) -> dict:
        """A method with various typed parameters."""
        return {
            "text": text,
            "count": count,
            "ratio": ratio,
            "flag": flag,
            "items": items,
            "config": config,
        }

    async def optional_param(self, value: Optional[str] = None) -> dict:
        """A method with an Optional parameter."""
        return {"value": value}

    def sync_method(self) -> str:
        """A synchronous method (should be ignored)."""
        return "sync"

    def _private_method(self) -> str:
        """A private method (should be ignored)."""
        return "private"

    async def _private_async(self) -> str:
        """A private async method (should be ignored)."""
        return "private async"


class MinimalPlugin(LLMPlugin):
    """A minimal plugin with just one method."""

    name = "minimal"

    async def action(self, input: str) -> dict:
        """Perform an action."""
        return {"output": input.upper()}


class TestPluginToolDiscovery:
    """Tests for tool discovery from plugin methods."""

    def test_discovers_async_methods(self):
        """Should discover all public async methods as tools."""
        plugin = SamplePlugin()
        tools = plugin.get_tools()
        tool_names = [t["name"] for t in tools]

        assert "sample_simple_method" in tool_names
        assert "sample_method_with_defaults" in tool_names
        assert "sample_no_params" in tool_names
        assert "sample_typed_params" in tool_names
        assert "sample_optional_param" in tool_names

    def test_ignores_sync_methods(self):
        """Should not discover synchronous methods."""
        plugin = SamplePlugin()
        tools = plugin.get_tools()
        tool_names = [t["name"] for t in tools]

        assert "sample_sync_method" not in tool_names

    def test_ignores_private_methods(self):
        """Should not discover private methods."""
        plugin = SamplePlugin()
        tools = plugin.get_tools()
        tool_names = [t["name"] for t in tools]

        assert "sample__private_method" not in tool_names
        assert "sample__private_async" not in tool_names

    def test_ignores_base_methods(self):
        """Should not discover base class methods."""
        plugin = SamplePlugin()
        tools = plugin.get_tools()
        tool_names = [t["name"] for t in tools]

        assert "sample_get_tools" not in tool_names
        assert "sample_call_tool" not in tool_names
        assert "sample_cleanup" not in tool_names

    def test_tool_name_includes_plugin_prefix(self):
        """Tool names should include plugin name prefix."""
        plugin = SamplePlugin()
        tools = plugin.get_tools()

        for tool in tools:
            assert tool["name"].startswith("sample_")

    def test_minimal_plugin_tools(self):
        """Minimal plugin should have one tool."""
        plugin = MinimalPlugin()
        tools = plugin.get_tools()

        assert len(tools) == 1
        assert tools[0]["name"] == "minimal_action"


class TestToolDefinitionStructure:
    """Tests for tool definition structure."""

    def test_tool_has_required_fields(self):
        """Each tool should have name, description, and inputSchema."""
        plugin = SamplePlugin()
        tools = plugin.get_tools()

        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    def test_description_from_docstring(self):
        """Tool description should come from method docstring."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        assert tools["sample_simple_method"]["description"] == "A simple method that returns the input."
        assert tools["sample_no_params"]["description"] == "A method with no parameters."

    def test_input_schema_structure(self):
        """Input schema should be a valid JSON schema object."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_simple_method"]["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema

    def test_required_parameters(self):
        """Required parameters should be in the required list."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_method_with_defaults"]["inputSchema"]
        assert "required" in schema["required"]
        assert "optional" not in schema["required"]
        assert "number" not in schema["required"]

    def test_default_values_in_schema(self):
        """Optional parameters should have default values in schema."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_method_with_defaults"]["inputSchema"]
        assert schema["properties"]["optional"]["default"] == "default"
        assert schema["properties"]["number"]["default"] == 42

    def test_no_params_empty_properties(self):
        """Method with no params should have empty properties."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_no_params"]["inputSchema"]
        assert schema["properties"] == {}
        assert schema["required"] == []


class TestTypeHintToJsonSchema:
    """Tests for Python type to JSON schema conversion."""

    def test_string_type(self):
        """str should map to 'string'."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_typed_params"]["inputSchema"]
        assert schema["properties"]["text"]["type"] == "string"

    def test_int_type(self):
        """int should map to 'integer'."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_typed_params"]["inputSchema"]
        assert schema["properties"]["count"]["type"] == "integer"

    def test_float_type(self):
        """float should map to 'number'."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_typed_params"]["inputSchema"]
        assert schema["properties"]["ratio"]["type"] == "number"

    def test_bool_type(self):
        """bool should map to 'boolean'."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_typed_params"]["inputSchema"]
        assert schema["properties"]["flag"]["type"] == "boolean"

    def test_list_type(self):
        """list should map to 'array'."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_typed_params"]["inputSchema"]
        assert schema["properties"]["items"]["type"] == "array"

    def test_dict_type(self):
        """dict should map to 'object'."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_typed_params"]["inputSchema"]
        assert schema["properties"]["config"]["type"] == "object"

    def test_optional_type(self):
        """Optional[str] should map to 'string'."""
        plugin = SamplePlugin()
        tools = {t["name"]: t for t in plugin.get_tools()}

        schema = tools["sample_optional_param"]["inputSchema"]
        assert schema["properties"]["value"]["type"] == "string"

    def test_untyped_defaults_to_string(self):
        """Untyped parameters should default to 'string'."""
        # MinimalPlugin's action method has 'input: str', so we create a custom one
        class UntypedPlugin(LLMPlugin):
            name = "untyped"

            async def method(self, param):
                """Method without type hint."""
                return {"param": param}

        plugin = UntypedPlugin()
        tools = plugin.get_tools()
        schema = tools[0]["inputSchema"]

        # Without type hint, should default to string
        assert schema["properties"]["param"]["type"] == "string"


class TestCallTool:
    """Tests for calling tools."""

    @pytest.mark.anyio
    async def test_call_with_full_name(self):
        """Call tool with full prefixed name."""
        plugin = SamplePlugin()
        result = await plugin.call_tool("sample_simple_method", {"value": "test"})

        assert result == {"input": "test"}

    @pytest.mark.anyio
    async def test_call_with_short_name(self):
        """Call tool with just method name."""
        plugin = SamplePlugin()
        result = await plugin.call_tool("simple_method", {"value": "test"})

        assert result == {"input": "test"}

    @pytest.mark.anyio
    async def test_call_with_defaults(self):
        """Call tool using default parameter values."""
        plugin = SamplePlugin()
        result = await plugin.call_tool(
            "method_with_defaults",
            {"required": "value"},
        )

        assert result == {
            "required": "value",
            "optional": "default",
            "number": 42,
        }

    @pytest.mark.anyio
    async def test_call_override_defaults(self):
        """Call tool overriding default values."""
        plugin = SamplePlugin()
        result = await plugin.call_tool(
            "method_with_defaults",
            {"required": "value", "optional": "custom", "number": 100},
        )

        assert result == {
            "required": "value",
            "optional": "custom",
            "number": 100,
        }

    @pytest.mark.anyio
    async def test_call_no_params(self):
        """Call tool with no parameters."""
        plugin = SamplePlugin()
        result = await plugin.call_tool("no_params", {})

        assert result == {"result": "success"}

    @pytest.mark.anyio
    async def test_call_unknown_tool(self):
        """Calling unknown tool raises ValueError."""
        plugin = SamplePlugin()

        with pytest.raises(ValueError) as exc_info:
            await plugin.call_tool("nonexistent", {})

        assert "Unknown tool" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_call_sync_method_fails(self):
        """Calling sync method as tool raises ValueError."""
        plugin = SamplePlugin()

        with pytest.raises(ValueError):
            await plugin.call_tool("sync_method", {})


class TestCleanup:
    """Tests for cleanup method."""

    @pytest.mark.anyio
    async def test_default_cleanup_does_nothing(self):
        """Default cleanup method does nothing."""
        plugin = SamplePlugin()
        # Should not raise
        await plugin.cleanup()

    @pytest.mark.anyio
    async def test_custom_cleanup_called(self):
        """Custom cleanup method should be called."""
        cleanup_called = False

        class CleanupPlugin(LLMPlugin):
            name = "cleanup"

            async def action(self) -> dict:
                """An action."""
                return {}

            async def cleanup(self) -> None:
                nonlocal cleanup_called
                cleanup_called = True

        plugin = CleanupPlugin()
        await plugin.cleanup()

        assert cleanup_called is True


class TestPluginState:
    """Tests for plugin state management."""

    def test_initial_state_empty(self):
        """Plugin should start with empty state."""
        plugin = SamplePlugin()
        assert plugin._state == {}

    def test_state_isolation(self):
        """Different plugin instances should have independent state."""
        plugin1 = SamplePlugin()
        plugin2 = SamplePlugin()

        plugin1._state["key"] = "value"

        assert plugin2._state == {}


class TestPluginName:
    """Tests for plugin name attribute."""

    def test_default_name(self):
        """Default plugin name is 'plugin'."""

        class DefaultNamePlugin(LLMPlugin):
            async def action(self) -> dict:
                """Action."""
                return {}

        plugin = DefaultNamePlugin()
        assert plugin.name == "plugin"

    def test_custom_name(self):
        """Custom plugin name is used in tool names."""
        plugin = SamplePlugin()
        assert plugin.name == "sample"

        tools = plugin.get_tools()
        for tool in tools:
            assert tool["name"].startswith("sample_")


class TestEdgeCases:
    """Edge cases for plugin system."""

    def test_method_without_docstring(self):
        """Method without docstring uses method name as description."""

        class NoDocPlugin(LLMPlugin):
            name = "nodoc"

            async def action(self, value: str) -> dict:
                return {"value": value}

        plugin = NoDocPlugin()
        tools = plugin.get_tools()

        # Should use method name when no docstring
        assert tools[0]["description"] == "action"

    def test_multiline_docstring_uses_first_line(self):
        """Multi-line docstring should use only first line."""

        class MultilineDocPlugin(LLMPlugin):
            name = "multiline"

            async def action(self) -> dict:
                """First line.

                This is additional documentation
                that should not be included.
                """
                return {}

        plugin = MultilineDocPlugin()
        tools = plugin.get_tools()

        assert tools[0]["description"] == "First line."

    @pytest.mark.anyio
    async def test_tool_with_complex_return(self):
        """Tool returning complex nested structure."""

        class ComplexPlugin(LLMPlugin):
            name = "complex"

            async def get_data(self) -> dict:
                """Get complex data."""
                return {
                    "nested": {"a": 1, "b": [1, 2, 3]},
                    "list": [{"x": 1}, {"y": 2}],
                }

        plugin = ComplexPlugin()
        result = await plugin.call_tool("get_data", {})

        assert result == {
            "nested": {"a": 1, "b": [1, 2, 3]},
            "list": [{"x": 1}, {"y": 2}],
        }

    def test_inherited_methods_from_subclass(self):
        """Methods from parent plugin class should be available."""

        class ParentPlugin(LLMPlugin):
            name = "parent"

            async def parent_action(self) -> dict:
                """Parent action."""
                return {"source": "parent"}

        class ChildPlugin(ParentPlugin):
            name = "child"

            async def child_action(self) -> dict:
                """Child action."""
                return {"source": "child"}

        plugin = ChildPlugin()
        tools = plugin.get_tools()
        tool_names = [t["name"] for t in tools]

        # Both parent and child methods should be available
        # Note: name prefix is from child
        assert "child_parent_action" in tool_names
        assert "child_child_action" in tool_names
