"""Plugin inspection utilities for extracting tool signatures.

This module provides functions to discover plugins and extract their
tool signatures without including full source code. This keeps the
system prompt compact while providing all necessary information.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import Any, get_type_hints

from ..plugin_base import LLMPlugin

logger = logging.getLogger("llm_pytest")


def inspect_plugins(project_root: Path) -> tuple[list[dict[str, Any]], set[str]]:
    """Discover plugins and extract their tool signatures.

    Args:
        project_root: Project root directory

    Returns:
        Tuple of:
        - List of plugin info dicts with tool signatures
        - Set of reserved plugin names
    """
    plugins_dir = project_root / "tests" / "llm" / "plugins"
    reserved_names: set[str] = set()

    if not plugins_dir.exists():
        return [], reserved_names

    plugins_info = []

    for plugin_file in sorted(plugins_dir.glob("*.py")):
        if plugin_file.name.startswith("_"):
            continue

        try:
            # First, extract plugin name from source (without loading)
            source = plugin_file.read_text()
            plugin_name = extract_plugin_name_from_source(source)

            if plugin_name:
                reserved_names.add(plugin_name)

            # Try to load the plugin to get accurate signatures
            plugin_class = _load_plugin_class(plugin_file)

            if plugin_class:
                signatures = get_tool_signatures(plugin_class)
                plugins_info.append({
                    "filename": plugin_file.name,
                    "name": plugin_name or plugin_file.stem,
                    "tools": signatures,
                })
            else:
                # Fallback: extract signatures from AST
                signatures = _extract_signatures_from_ast(source, plugin_name)
                plugins_info.append({
                    "filename": plugin_file.name,
                    "name": plugin_name or plugin_file.stem,
                    "tools": signatures,
                })

        except Exception as e:
            logger.warning(f"Failed to inspect plugin {plugin_file}: {e}")
            continue

    return plugins_info, reserved_names


def get_tool_signatures(plugin_class: type[LLMPlugin]) -> list[dict[str, Any]]:
    """Extract tool signatures from a plugin class.

    Args:
        plugin_class: The plugin class to inspect

    Returns:
        List of tool signature dicts with name, description, and parameters
    """
    signatures = []
    plugin_name = getattr(plugin_class, "name", "plugin")

    # Create instance to inspect methods
    try:
        instance = plugin_class()
    except Exception:
        # Can't instantiate, use class directly
        instance = None

    for method_name in dir(plugin_class):
        if method_name.startswith("_"):
            continue

        method = getattr(plugin_class, method_name)
        if not callable(method) or not asyncio.iscoroutinefunction(method):
            continue

        # Skip base class methods
        if method_name in ("get_tools", "call_tool", "cleanup"):
            continue

        sig_info = _extract_method_signature(
            method, method_name, plugin_name, instance
        )
        if sig_info:
            signatures.append(sig_info)

    return signatures


def extract_plugin_name_from_source(source: str) -> str | None:
    """Extract the plugin name from source code using AST.

    More reliable than regex as it handles various formatting styles.

    Args:
        source: Python source code

    Returns:
        The plugin name or None if not found
    """
    try:
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Look for LLMPlugin subclass
                for base in node.bases:
                    base_name = _get_ast_name(base)
                    if base_name in ("LLMPlugin", "llm_pytest.LLMPlugin"):
                        # Found plugin class, look for name attribute
                        for item in node.body:
                            if isinstance(item, ast.Assign):
                                for target in item.targets:
                                    if isinstance(target, ast.Name) and target.id == "name":
                                        if isinstance(item.value, ast.Constant):
                                            return item.value.value

        return None
    except SyntaxError:
        return None


def format_plugins_for_prompt(plugins: list[dict[str, Any]]) -> str:
    """Format plugin info for the system prompt.

    Args:
        plugins: List of plugin info dicts from inspect_plugins()

    Returns:
        Formatted markdown string with plugin tools

    Example output:
        ### Plugin: user_api
        **Tools:**
        - `user_api_create(name: str, email: str) -> dict` - Create a new user
        - `user_api_get(user_id: int) -> dict` - Get user by ID
    """
    if not plugins:
        return "No plugins currently exist."

    lines = []

    for plugin in plugins:
        plugin_name = plugin["name"]
        tools = plugin["tools"]

        lines.append(f"### Plugin: {plugin_name}")
        lines.append(f"**File:** `{plugin['filename']}`")
        lines.append("**Tools:**")

        for tool in tools:
            tool_name = tool["name"]
            description = tool.get("description", "")
            params = tool.get("parameters", [])

            # Format parameters
            param_strs = []
            for p in params:
                p_name = p["name"]
                p_type = p.get("type", "Any")
                if p.get("required", True):
                    param_strs.append(f"{p_name}: {p_type}")
                else:
                    default = p.get("default")
                    if default is None:
                        param_strs.append(f"{p_name}: {p_type} = None")
                    else:
                        param_strs.append(f"{p_name}: {p_type} = {default!r}")

            params_str = ", ".join(param_strs)
            lines.append(f"- `{tool_name}({params_str}) -> dict` - {description}")

        lines.append("")  # Blank line between plugins

    return "\n".join(lines)


def _load_plugin_class(plugin_file: Path) -> type[LLMPlugin] | None:
    """Dynamically load a plugin class from a file.

    Args:
        plugin_file: Path to the plugin file

    Returns:
        The plugin class or None if loading fails
    """
    try:
        spec = importlib.util.spec_from_file_location(
            plugin_file.stem, plugin_file
        )
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[plugin_file.stem] = module
        spec.loader.exec_module(module)

        # Find the LLMPlugin subclass
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, LLMPlugin)
                and obj is not LLMPlugin
            ):
                return obj

        return None
    except Exception as e:
        logger.debug(f"Could not load plugin {plugin_file}: {e}")
        return None


def _extract_method_signature(
    method: Any,
    method_name: str,
    plugin_name: str,
    instance: LLMPlugin | None,
) -> dict[str, Any] | None:
    """Extract signature info from an async method.

    Args:
        method: The method to inspect
        method_name: The method name
        plugin_name: The plugin name (for tool name prefix)
        instance: Optional plugin instance for better type hints

    Returns:
        Signature info dict or None if extraction fails
    """
    try:
        sig = inspect.signature(method)
        doc = inspect.getdoc(method) or ""

        # Try to get type hints
        try:
            if instance:
                hints = get_type_hints(getattr(instance, method_name))
            else:
                hints = get_type_hints(method)
        except Exception:
            hints = {}

        params = []
        for name, param in sig.parameters.items():
            if name == "self":
                continue

            param_type = hints.get(name, Any)
            type_str = _type_to_string(param_type)

            params.append({
                "name": name,
                "type": type_str,
                "required": param.default == inspect.Parameter.empty,
                "default": None if param.default == inspect.Parameter.empty else param.default,
            })

        return {
            "name": f"{plugin_name}_{method_name}",
            "description": doc.split("\n")[0] if doc else method_name,
            "parameters": params,
        }
    except Exception:
        return None


def _extract_signatures_from_ast(
    source: str,
    plugin_name: str | None,
) -> list[dict[str, Any]]:
    """Extract method signatures from source using AST (fallback).

    Used when the plugin can't be loaded dynamically.

    Args:
        source: Python source code
        plugin_name: The plugin name for tool prefix

    Returns:
        List of signature dicts
    """
    signatures = []
    plugin_name = plugin_name or "plugin"

    try:
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check if it's an LLMPlugin subclass
                is_plugin = any(
                    _get_ast_name(base) in ("LLMPlugin", "llm_pytest.LLMPlugin")
                    for base in node.bases
                )

                if not is_plugin:
                    continue

                # Extract async methods
                for item in node.body:
                    if isinstance(item, ast.AsyncFunctionDef):
                        if item.name.startswith("_"):
                            continue
                        if item.name in ("get_tools", "call_tool", "cleanup"):
                            continue

                        sig_info = _ast_function_to_signature(item, plugin_name)
                        if sig_info:
                            signatures.append(sig_info)

    except SyntaxError:
        pass

    return signatures


def _ast_function_to_signature(
    func: ast.AsyncFunctionDef,
    plugin_name: str,
) -> dict[str, Any]:
    """Convert an AST function definition to a signature dict.

    Args:
        func: The AST function node
        plugin_name: The plugin name for tool prefix

    Returns:
        Signature dict
    """
    # Extract docstring
    docstring = ""
    if (
        func.body
        and isinstance(func.body[0], ast.Expr)
        and isinstance(func.body[0].value, ast.Constant)
        and isinstance(func.body[0].value.value, str)
    ):
        docstring = func.body[0].value.value.split("\n")[0]

    # Extract parameters
    params = []
    args = func.args

    # Regular arguments
    num_defaults = len(args.defaults)
    num_args = len(args.args)

    for i, arg in enumerate(args.args):
        if arg.arg == "self":
            continue

        # Check if this arg has a default
        default_index = i - (num_args - num_defaults)
        has_default = default_index >= 0

        # Get type annotation
        type_str = "Any"
        if arg.annotation:
            type_str = _ast_annotation_to_string(arg.annotation)

        param_info = {
            "name": arg.arg,
            "type": type_str,
            "required": not has_default,
            "default": None,
        }

        if has_default:
            default_node = args.defaults[default_index]
            param_info["default"] = _ast_value_to_python(default_node)

        params.append(param_info)

    return {
        "name": f"{plugin_name}_{func.name}",
        "description": docstring or func.name,
        "parameters": params,
    }


def _get_ast_name(node: ast.expr) -> str:
    """Get the name from an AST node (handles Name and Attribute)."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return f"{_get_ast_name(node.value)}.{node.attr}"
    return ""


def _ast_annotation_to_string(annotation: ast.expr) -> str:
    """Convert an AST type annotation to a string."""
    if isinstance(annotation, ast.Name):
        return annotation.id
    elif isinstance(annotation, ast.Constant):
        return str(annotation.value)
    elif isinstance(annotation, ast.Subscript):
        base = _ast_annotation_to_string(annotation.value)
        if isinstance(annotation.slice, ast.Tuple):
            args = ", ".join(
                _ast_annotation_to_string(elt) for elt in annotation.slice.elts
            )
        else:
            args = _ast_annotation_to_string(annotation.slice)
        return f"{base}[{args}]"
    elif isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        # Handle X | Y union syntax
        left = _ast_annotation_to_string(annotation.left)
        right = _ast_annotation_to_string(annotation.right)
        return f"{left} | {right}"
    elif isinstance(annotation, ast.Attribute):
        return _get_ast_name(annotation)
    return "Any"


def _ast_value_to_python(node: ast.expr) -> Any:
    """Convert an AST value node to a Python value."""
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.List):
        return [_ast_value_to_python(elt) for elt in node.elts]
    elif isinstance(node, ast.Dict):
        return {
            _ast_value_to_python(k): _ast_value_to_python(v)
            for k, v in zip(node.keys, node.values)
            if k is not None
        }
    elif isinstance(node, ast.Name):
        if node.id == "None":
            return None
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        return node.id
    return None


def _type_to_string(python_type: type) -> str:
    """Convert a Python type to a readable string."""
    if python_type is type(None):
        return "None"

    # Handle typing module types
    origin = getattr(python_type, "__origin__", None)
    args = getattr(python_type, "__args__", ())

    if origin is not None:
        origin_name = getattr(origin, "__name__", str(origin))

        # Handle common typing constructs
        if origin_name == "Union":
            arg_strs = [_type_to_string(arg) for arg in args]
            return " | ".join(arg_strs)

        if args:
            arg_strs = [_type_to_string(arg) for arg in args]
            return f"{origin_name}[{', '.join(arg_strs)}]"

        return origin_name

    # Handle simple types
    if hasattr(python_type, "__name__"):
        return python_type.__name__

    return str(python_type)
