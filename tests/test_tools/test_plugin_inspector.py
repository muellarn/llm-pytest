"""Tests for plugin_inspector module."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_pytest.tools.plugin_inspector import (
    _ast_annotation_to_string,
    _ast_function_to_signature,
    _ast_value_to_python,
    _extract_signatures_from_ast,
    _get_ast_name,
    _type_to_string,
    extract_plugin_name_from_source,
    format_plugins_for_prompt,
    inspect_plugins,
)


class TestExtractPluginName:
    """Tests for extract_plugin_name_from_source."""

    def test_extracts_simple_name(self):
        source = '''
from llm_pytest import LLMPlugin

class MyPlugin(LLMPlugin):
    name = "my_plugin"

    async def do_something(self) -> dict:
        return {}
'''
        assert extract_plugin_name_from_source(source) == "my_plugin"

    def test_extracts_name_with_double_quotes(self):
        source = '''
class TestPlugin(LLMPlugin):
    name = "test_api"
'''
        assert extract_plugin_name_from_source(source) == "test_api"

    def test_extracts_name_with_single_quotes(self):
        source = '''
class TestPlugin(LLMPlugin):
    name = 'another_plugin'
'''
        assert extract_plugin_name_from_source(source) == "another_plugin"

    def test_returns_none_for_no_name(self):
        source = '''
class TestPlugin(LLMPlugin):
    pass
'''
        assert extract_plugin_name_from_source(source) is None

    def test_returns_none_for_non_plugin_class(self):
        source = '''
class RegularClass:
    name = "not_a_plugin"
'''
        assert extract_plugin_name_from_source(source) is None

    def test_returns_none_for_syntax_error(self):
        source = "this is not valid python {{{"
        assert extract_plugin_name_from_source(source) is None


class TestInspectPlugins:
    """Tests for inspect_plugins function."""

    def test_returns_empty_for_missing_directory(self, tmp_path: Path):
        plugins_info, reserved = inspect_plugins(tmp_path)
        assert plugins_info == []
        assert reserved == set()

    def test_discovers_plugins(self, tmp_path: Path):
        # Create plugin directory structure
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)

        # Create a sample plugin
        plugin_code = '''
from llm_pytest import LLMPlugin

class SamplePlugin(LLMPlugin):
    """A sample plugin for testing."""

    name = "sample"

    async def action_one(self, param: str) -> dict:
        """Perform action one."""
        return {"result": param}

    async def action_two(self, x: int, y: int = 10) -> dict:
        """Perform action two with optional parameter."""
        return {"sum": x + y}
'''
        (plugins_dir / "sample_plugin.py").write_text(plugin_code)

        plugins_info, reserved = inspect_plugins(tmp_path)

        assert len(plugins_info) == 1
        assert "sample" in reserved
        assert plugins_info[0]["name"] == "sample"
        assert len(plugins_info[0]["tools"]) == 2

    def test_skips_private_files(self, tmp_path: Path):
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)

        # Create a private file (should be skipped)
        (plugins_dir / "_private.py").write_text("# private module")

        # Create a regular plugin
        plugin_code = '''
from llm_pytest import LLMPlugin

class TestPlugin(LLMPlugin):
    name = "test"

    async def do_test(self) -> dict:
        return {}
'''
        (plugins_dir / "test_plugin.py").write_text(plugin_code)

        plugins_info, reserved = inspect_plugins(tmp_path)

        assert len(plugins_info) == 1
        assert "test" in reserved

    def test_extracts_signatures_not_full_source(self, tmp_path: Path):
        """Problem #2: Should extract signatures, not full source code."""
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)

        # Create plugin with internal implementation details
        plugin_code = '''
from llm_pytest import LLMPlugin

class SecretPlugin(LLMPlugin):
    """Plugin with internal secrets."""

    name = "secret"
    _internal_secret = "super_secret_value_12345"

    async def public_method(self, data: str) -> dict:
        """A public method."""
        # This internal logic should NOT appear in output
        internal_variable = "internal_implementation_detail"
        secret_key = self._internal_secret
        return {"processed": data}
'''
        (plugins_dir / "secret_plugin.py").write_text(plugin_code)

        plugins_info, _ = inspect_plugins(tmp_path)

        # Convert to string for checking
        formatted = format_plugins_for_prompt(plugins_info)

        # Should have the tool signature
        assert "secret_public_method" in formatted
        assert "data: str" in formatted

        # Should NOT contain internal implementation details
        assert "super_secret_value_12345" not in formatted
        assert "internal_implementation_detail" not in formatted
        assert "_internal_secret" not in formatted


class TestFormatPluginsForPrompt:
    """Tests for format_plugins_for_prompt function."""

    def test_formats_empty_list(self):
        result = format_plugins_for_prompt([])
        assert result == "No plugins currently exist."

    def test_formats_single_plugin(self):
        plugins = [
            {
                "filename": "user_api.py",
                "name": "user_api",
                "tools": [
                    {
                        "name": "user_api_create",
                        "description": "Create a new user",
                        "parameters": [
                            {"name": "name", "type": "str", "required": True},
                            {"name": "email", "type": "str", "required": True},
                        ],
                    },
                    {
                        "name": "user_api_get",
                        "description": "Get user by ID",
                        "parameters": [
                            {"name": "user_id", "type": "int", "required": True},
                        ],
                    },
                ],
            }
        ]

        result = format_plugins_for_prompt(plugins)

        assert "### Plugin: user_api" in result
        assert "user_api.py" in result
        assert "user_api_create(name: str, email: str)" in result
        assert "user_api_get(user_id: int)" in result
        assert "Create a new user" in result

    def test_formats_optional_parameters(self):
        plugins = [
            {
                "filename": "api.py",
                "name": "api",
                "tools": [
                    {
                        "name": "api_request",
                        "description": "Make an API request",
                        "parameters": [
                            {"name": "url", "type": "str", "required": True},
                            {"name": "timeout", "type": "int", "required": False, "default": 30},
                            {"name": "headers", "type": "dict", "required": False, "default": None},
                        ],
                    },
                ],
            }
        ]

        result = format_plugins_for_prompt(plugins)

        assert "url: str" in result
        assert "timeout: int = 30" in result
        assert "headers: dict = None" in result

    def test_formats_multiple_plugins(self):
        plugins = [
            {
                "filename": "plugin_a.py",
                "name": "plugin_a",
                "tools": [{"name": "plugin_a_foo", "description": "Foo", "parameters": []}],
            },
            {
                "filename": "plugin_b.py",
                "name": "plugin_b",
                "tools": [{"name": "plugin_b_bar", "description": "Bar", "parameters": []}],
            },
        ]

        result = format_plugins_for_prompt(plugins)

        assert "### Plugin: plugin_a" in result
        assert "### Plugin: plugin_b" in result
        assert "plugin_a_foo" in result
        assert "plugin_b_bar" in result


class TestASTSignatureExtraction:
    """Tests for AST-based signature extraction (fallback when loading fails)."""

    def test_extracts_type_annotations(self, tmp_path: Path):
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)

        # Plugin with various type annotations
        plugin_code = '''
from llm_pytest import LLMPlugin
from typing import Optional

class TypedPlugin(LLMPlugin):
    name = "typed"

    async def with_types(
        self,
        text: str,
        number: int,
        flag: bool = False,
        items: list | None = None,
    ) -> dict:
        """Method with various types."""
        return {}
'''
        (plugins_dir / "typed_plugin.py").write_text(plugin_code)

        plugins_info, _ = inspect_plugins(tmp_path)
        formatted = format_plugins_for_prompt(plugins_info)

        assert "text: str" in formatted
        assert "number: int" in formatted
        assert "flag: bool = False" in formatted

    def test_handles_docstrings(self, tmp_path: Path):
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)

        plugin_code = '''
from llm_pytest import LLMPlugin

class DocPlugin(LLMPlugin):
    name = "doc"

    async def well_documented(self, param: str) -> dict:
        """This is the first line of the docstring.

        This is additional documentation that should not appear.
        """
        return {}
'''
        (plugins_dir / "doc_plugin.py").write_text(plugin_code)

        plugins_info, _ = inspect_plugins(tmp_path)

        # Should only include first line of docstring
        assert plugins_info[0]["tools"][0]["description"] == "This is the first line of the docstring."


class TestASTHelperFunctions:
    """Tests for AST helper functions used in fallback extraction."""

    def test_extract_signatures_from_ast_basic(self):
        """Test basic AST signature extraction."""
        source = '''
from llm_pytest import LLMPlugin

class MyPlugin(LLMPlugin):
    name = "my"

    async def action(self, param: str) -> dict:
        """Do an action."""
        return {}
'''
        signatures = _extract_signatures_from_ast(source, "my")

        assert len(signatures) == 1
        assert signatures[0]["name"] == "my_action"
        assert signatures[0]["description"] == "Do an action."
        assert len(signatures[0]["parameters"]) == 1
        assert signatures[0]["parameters"][0]["name"] == "param"
        assert signatures[0]["parameters"][0]["type"] == "str"

    def test_extract_signatures_from_ast_skips_private_methods(self):
        """Test that private methods are skipped."""
        source = '''
from llm_pytest import LLMPlugin

class MyPlugin(LLMPlugin):
    name = "my"

    async def _private_method(self, x: int) -> dict:
        return {}

    async def public_method(self) -> dict:
        return {}
'''
        signatures = _extract_signatures_from_ast(source, "my")

        assert len(signatures) == 1
        assert signatures[0]["name"] == "my_public_method"

    def test_extract_signatures_from_ast_skips_base_methods(self):
        """Test that base class methods are skipped."""
        source = '''
from llm_pytest import LLMPlugin

class MyPlugin(LLMPlugin):
    name = "my"

    async def cleanup(self) -> None:
        pass

    async def get_tools(self) -> list:
        return []

    async def call_tool(self, name: str, args: dict) -> dict:
        return {}

    async def real_method(self) -> dict:
        return {}
'''
        signatures = _extract_signatures_from_ast(source, "my")

        assert len(signatures) == 1
        assert signatures[0]["name"] == "my_real_method"

    def test_extract_signatures_from_ast_handles_defaults(self):
        """Test extraction of parameters with defaults."""
        source = '''
from llm_pytest import LLMPlugin

class MyPlugin(LLMPlugin):
    name = "my"

    async def with_defaults(
        self,
        required: str,
        optional: int = 42,
        flag: bool = True,
        name: str = "default",
    ) -> dict:
        return {}
'''
        signatures = _extract_signatures_from_ast(source, "my")

        params = signatures[0]["parameters"]
        assert len(params) == 4

        assert params[0]["name"] == "required"
        assert params[0]["required"] is True

        assert params[1]["name"] == "optional"
        assert params[1]["required"] is False
        assert params[1]["default"] == 42

        assert params[2]["name"] == "flag"
        assert params[2]["default"] is True

        assert params[3]["name"] == "name"
        assert params[3]["default"] == "default"

    def test_extract_signatures_from_ast_handles_syntax_error(self):
        """Test that syntax errors return empty list."""
        source = "this is not valid python {{{"
        signatures = _extract_signatures_from_ast(source, "my")
        assert signatures == []

    def test_extract_signatures_from_ast_non_plugin_class(self):
        """Test that non-LLMPlugin classes are ignored."""
        source = '''
class NotAPlugin:
    async def method(self) -> dict:
        return {}
'''
        signatures = _extract_signatures_from_ast(source, "not")
        assert signatures == []


class TestAstAnnotationToString:
    """Tests for _ast_annotation_to_string helper."""

    def test_simple_name(self):
        import ast
        node = ast.Name(id="str")
        assert _ast_annotation_to_string(node) == "str"

    def test_constant(self):
        import ast
        node = ast.Constant(value="literal")
        assert _ast_annotation_to_string(node) == "literal"

    def test_subscript_list(self):
        import ast
        # list[str]
        node = ast.Subscript(
            value=ast.Name(id="list"),
            slice=ast.Name(id="str"),
        )
        result = _ast_annotation_to_string(node)
        assert "list" in result
        assert "str" in result

    def test_union_with_bitor(self):
        import ast
        # str | None (Python 3.10+ union syntax)
        node = ast.BinOp(
            left=ast.Name(id="str"),
            op=ast.BitOr(),
            right=ast.Name(id="None"),
        )
        result = _ast_annotation_to_string(node)
        assert "str" in result
        assert "None" in result


class TestAstValueToPython:
    """Tests for _ast_value_to_python helper."""

    def test_constant_string(self):
        import ast
        node = ast.Constant(value="hello")
        assert _ast_value_to_python(node) == "hello"

    def test_constant_int(self):
        import ast
        node = ast.Constant(value=42)
        assert _ast_value_to_python(node) == 42

    def test_constant_bool(self):
        import ast
        node = ast.Constant(value=True)
        assert _ast_value_to_python(node) is True

    def test_list(self):
        import ast
        node = ast.List(elts=[
            ast.Constant(value=1),
            ast.Constant(value=2),
        ])
        assert _ast_value_to_python(node) == [1, 2]

    def test_dict(self):
        import ast
        node = ast.Dict(
            keys=[ast.Constant(value="a")],
            values=[ast.Constant(value=1)],
        )
        assert _ast_value_to_python(node) == {"a": 1}

    def test_name_none(self):
        import ast
        node = ast.Name(id="None")
        assert _ast_value_to_python(node) is None

    def test_name_true(self):
        import ast
        node = ast.Name(id="True")
        assert _ast_value_to_python(node) is True

    def test_name_false(self):
        import ast
        node = ast.Name(id="False")
        assert _ast_value_to_python(node) is False


class TestGetAstName:
    """Tests for _get_ast_name helper."""

    def test_simple_name(self):
        import ast
        node = ast.Name(id="MyClass")
        assert _get_ast_name(node) == "MyClass"

    def test_attribute(self):
        import ast
        # module.MyClass
        node = ast.Attribute(
            value=ast.Name(id="module"),
            attr="MyClass",
        )
        assert _get_ast_name(node) == "module.MyClass"

    def test_nested_attribute(self):
        import ast
        # a.b.c
        node = ast.Attribute(
            value=ast.Attribute(
                value=ast.Name(id="a"),
                attr="b",
            ),
            attr="c",
        )
        assert _get_ast_name(node) == "a.b.c"


class TestTypeToString:
    """Tests for _type_to_string helper."""

    def test_simple_types(self):
        assert _type_to_string(str) == "str"
        assert _type_to_string(int) == "int"
        assert _type_to_string(bool) == "bool"
        assert _type_to_string(float) == "float"
        assert _type_to_string(list) == "list"
        assert _type_to_string(dict) == "dict"

    def test_none_type(self):
        assert _type_to_string(type(None)) == "None"

    def test_optional_type(self):
        from typing import Optional
        result = _type_to_string(Optional[str])
        # Should show str | None or similar
        assert "str" in result

    def test_union_type(self):
        from typing import Union
        result = _type_to_string(Union[str, int])
        assert "str" in result or "int" in result

    def test_list_with_args(self):
        from typing import List
        result = _type_to_string(List[str])
        assert "str" in result

    def test_dict_with_args(self):
        from typing import Dict
        result = _type_to_string(Dict[str, int])
        assert "str" in result


class TestInspectPluginsEdgeCases:
    """Additional edge case tests for inspect_plugins."""

    def test_handles_plugin_without_name_attribute(self, tmp_path: Path):
        """Test handling when plugin class has no name attribute."""
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)

        plugin_code = '''
from llm_pytest import LLMPlugin

class NoNamePlugin(LLMPlugin):
    # No name attribute defined

    async def action(self) -> dict:
        return {}
'''
        (plugins_dir / "no_name.py").write_text(plugin_code)

        plugins_info, reserved = inspect_plugins(tmp_path)

        # Should still be discovered, using filename as fallback
        assert len(plugins_info) == 1

    def test_handles_import_error_gracefully(self, tmp_path: Path):
        """Test that import errors are handled gracefully."""
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)

        # Plugin that imports a non-existent module
        plugin_code = '''
from llm_pytest import LLMPlugin
from nonexistent_module import something  # This will fail

class BrokenPlugin(LLMPlugin):
    name = "broken"

    async def action(self) -> dict:
        return {}
'''
        (plugins_dir / "broken_plugin.py").write_text(plugin_code)

        # Should not raise, but use AST fallback
        plugins_info, reserved = inspect_plugins(tmp_path)

        # Plugin name should still be extracted via AST
        assert "broken" in reserved

    def test_handles_multiple_classes_in_file(self, tmp_path: Path):
        """Test handling of file with multiple classes."""
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)

        plugin_code = '''
from llm_pytest import LLMPlugin

class HelperClass:
    """Not a plugin."""
    pass

class ActualPlugin(LLMPlugin):
    name = "actual"

    async def action(self) -> dict:
        return {}

class AnotherHelper:
    """Also not a plugin."""
    pass
'''
        (plugins_dir / "multi_class.py").write_text(plugin_code)

        plugins_info, reserved = inspect_plugins(tmp_path)

        assert len(plugins_info) == 1
        assert "actual" in reserved
        assert plugins_info[0]["name"] == "actual"
