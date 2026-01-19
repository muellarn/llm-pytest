"""Create test tool implementation.

This module provides the create_test MCP tool that generates
YAML test files and optionally Python plugin files using Claude Code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, PackageLoader

from ..models import Step, TestSpec
from ..schema import validate_test_yaml
from .plugin_inspector import (
    extract_plugin_name_from_source,
    format_plugins_for_prompt,
    inspect_plugins,
)

logger = logging.getLogger("llm_pytest")

# Problem #6: Allow hyphens in filenames
SAFE_FILENAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*\.(?:py|yaml)$")

# Problem #4: Robust JSON extraction pattern
# Matches JSON in markdown blocks or raw JSON containing "plugin" or "test"
JSON_EXTRACT_PATTERN = re.compile(
    r'```(?:json)?\s*(\{[\s\S]*?"(?:plugin|test)"[\s\S]*?\})\s*```|'
    r'(\{[\s\S]*?"(?:plugin|test)"[\s\S]*?\})',
    re.MULTILINE,
)

# Jinja2 environment for templates
_env = Environment(
    loader=PackageLoader("llm_pytest", "templates"),
    autoescape=False,  # We're not generating HTML
)


async def create_test_tool(
    description: str,
    filename: str | None = None,
    extend_plugin: str | None = None,
    timeout: int = 120,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Create a YAML test file, including plugins if needed.

    This tool analyzes your description, checks existing plugins,
    and generates both plugin code (if needed) and test YAML.

    Args:
        description: Natural language description of what to test.
                    Be specific about functionality and expected behaviors.
        filename: Optional test filename (without path, e.g., "test_user.yaml").
                 If not provided, will be auto-derived from description.
        extend_plugin: Optional existing plugin name to extend with new methods
                      instead of creating a new plugin.
        timeout: Timeout in seconds for Claude Code subprocess (default: 120).
        project_root: Project root directory (auto-detected if not provided).

    Returns:
        Dict with:
        - success: bool
        - test_path: str - Path to created test file
        - test_content: str - Generated YAML
        - plugin_path: str | None - Path to created plugin (if any)
        - plugin_content: str | None - Generated plugin code (if any)
        - error: str (only if success=False)
    """
    if project_root is None:
        project_root = Path.cwd()

    # Gather context about existing plugins
    plugins_info, reserved_names = inspect_plugins(project_root)

    # Render the system prompt using Jinja2 (Problem #1)
    system_prompt = _render_system_prompt(
        plugins_info=plugins_info,
        reserved_names=reserved_names,
        extend_plugin=extend_plugin,
    )

    # Call Claude Code subprocess
    result = await _call_claude_code(
        system_prompt=system_prompt,
        user_prompt=description,
        project_root=project_root,
        timeout=timeout,
    )

    if "error" in result:
        return {"success": False, **result}

    # Problem #4: Robust JSON parsing with multiple fallbacks
    parsed = _parse_claude_output(result.get("output", ""))
    if "error" in parsed:
        return {"success": False, **parsed}

    # Problem #3: Validate generated YAML against schema
    validation_result = _validate_generated_content(parsed, project_root)
    if "error" in validation_result:
        return {"success": False, **validation_result}

    # Problem #5: Atomic file writing with rollback
    return await _atomic_write_files(
        parsed=parsed,
        project_root=project_root,
        reserved_names=reserved_names,
        filename_override=filename,
    )


def _render_system_prompt(
    plugins_info: list[dict[str, Any]],
    reserved_names: set[str],
    extend_plugin: str | None,
) -> str:
    """Render the system prompt using Jinja2.

    Problem #1 Solution: Uses Jinja2 instead of .format()
    Problem #9 Solution: Generates parts dynamically from schema

    Args:
        plugins_info: List of plugin info dicts
        reserved_names: Set of reserved plugin names
        extend_plugin: Optional plugin name to extend

    Returns:
        Rendered system prompt string
    """
    template = _env.get_template("create_test_system_prompt.jinja2")

    # Problem #9: Generate schema documentation dynamically
    schema_docs = _generate_schema_docs()
    builtin_tools = _get_builtin_tools_docs()
    existing_plugins = format_plugins_for_prompt(plugins_info)

    return template.render(
        yaml_schema=schema_docs,
        builtin_tools=builtin_tools,
        existing_plugins=existing_plugins,
        reserved_plugin_names=", ".join(sorted(reserved_names)) if reserved_names else "",
        extend_plugin=extend_plugin,
    )


def _parse_claude_output(output: str) -> dict[str, Any]:
    """Parse Claude's output with robust JSON extraction.

    Problem #4 Solution: Multiple fallback strategies for JSON parsing.

    Args:
        output: Raw output from Claude Code

    Returns:
        Parsed dict or error dict
    """
    # Strategy 1: Try direct JSON parse (if output is pure JSON)
    try:
        data = json.loads(output)

        # Handle wrapped format from Claude's --output-format json
        if isinstance(data, dict) and "result" in data:
            content = data["result"]
            if isinstance(content, str):
                # Try to parse the string as JSON first
                try:
                    parsed_content = json.loads(content)
                    if isinstance(parsed_content, dict) and ("test" in parsed_content or "plugin" in parsed_content):
                        return parsed_content
                except json.JSONDecodeError:
                    pass
                # Fall back to text extraction
                return _extract_json_from_text(content)
            if isinstance(content, dict):
                return content

        # Check if it's our expected format
        if isinstance(data, dict) and ("test" in data or "plugin" in data):
            return data

        # Might be wrapped differently, try extracting
        return _extract_json_from_text(str(data))

    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from markdown code blocks or raw JSON in text
    return _extract_json_from_text(output)


def _extract_json_from_text(text: str) -> dict[str, Any]:
    """Extract JSON from text using robust regex.

    Problem #4 Solution: Handles markdown blocks and raw JSON.

    Args:
        text: Text that may contain JSON

    Returns:
        Extracted dict or error dict
    """
    match = JSON_EXTRACT_PATTERN.search(text)
    if match:
        json_str = match.group(1) or match.group(2)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            return {
                "error": f"Invalid JSON in response: {e}",
                "raw_output": text[:500],
            }

    return {
        "error": "No valid JSON found in response",
        "raw_output": text[:500],
    }


def _validate_generated_content(
    parsed: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """Validate the generated plugin and test content.

    Problem #3 Solution: Uses existing schema.py validation.

    Args:
        parsed: Parsed output from Claude
        project_root: Project root directory

    Returns:
        Dict with "valid": True or "error" key
    """
    errors = []

    # Validate test YAML if present
    test_data = parsed.get("test")
    if not test_data:
        return {"error": "No test content in response"}

    yaml_content = test_data.get("code", "")
    if not yaml_content:
        return {"error": "Empty test content"}

    try:
        content = yaml.safe_load(yaml_content)
        _, validation_errors = validate_test_yaml(
            content,
            Path("generated_test.yaml"),  # Placeholder path for errors
        )
        if validation_errors:
            errors.extend(validation_errors)
    except yaml.YAMLError as e:
        errors.append(f"Invalid YAML syntax: {e}")

    # Validate plugin Python syntax if present
    plugin_data = parsed.get("plugin")
    if plugin_data:
        plugin_code = plugin_data.get("code", "")
        if plugin_code:
            try:
                compile(plugin_code, "<plugin>", "exec")
            except SyntaxError as e:
                errors.append(f"Invalid Python syntax in plugin: {e}")

    if errors:
        return {"error": "Validation failed", "details": errors}

    return {"valid": True}


async def _atomic_write_files(
    parsed: dict[str, Any],
    project_root: Path,
    reserved_names: set[str],
    filename_override: str | None,
) -> dict[str, Any]:
    """Write files atomically with rollback on failure.

    Problem #5 Solution: Write to temp files first, then rename.
    Problem #6 Solution: Relaxed filename pattern allows hyphens.
    Problem #7 Solution: Auto-derive paths from filename.

    Args:
        parsed: Validated parsed output
        project_root: Project root directory
        reserved_names: Set of reserved plugin names
        filename_override: Optional filename override for test

    Returns:
        Result dict with success status and file paths
    """
    files_to_write: list[tuple[Path, str]] = []
    temp_files: list[tuple[Path, Path]] = []

    try:
        # Prepare test file
        test_data = parsed.get("test", {})
        test_filename = filename_override or test_data.get("filename", "")

        if not test_filename:
            return {"success": False, "error": "No test filename provided"}

        # Problem #6: Allow hyphens in filenames
        if not SAFE_FILENAME_PATTERN.match(test_filename):
            return {"success": False, "error": f"Invalid test filename: {test_filename}"}
        if not test_filename.startswith("test_"):
            return {"success": False, "error": f"Test filename must start with 'test_': {test_filename}"}
        if not test_filename.endswith(".yaml"):
            return {"success": False, "error": f"Test filename must end with '.yaml': {test_filename}"}

        # Problem #7: Auto-derive full path
        tests_dir = project_root / "tests" / "llm"
        tests_dir.mkdir(parents=True, exist_ok=True)

        test_path = tests_dir / test_filename
        test_content = test_data.get("code", "")

        if test_path.exists():
            return {"success": False, "error": f"Test file already exists: {test_path}"}

        files_to_write.append((test_path, test_content))

        # Prepare plugin file if needed
        plugin_path: Path | None = None
        plugin_content: str | None = None

        plugin_data = parsed.get("plugin")
        if plugin_data:
            plugin_filename = plugin_data.get("filename", "")

            if not plugin_filename:
                return {"success": False, "error": "Plugin specified but no filename provided"}

            if not SAFE_FILENAME_PATTERN.match(plugin_filename):
                return {"success": False, "error": f"Invalid plugin filename: {plugin_filename}"}
            if not plugin_filename.endswith(".py"):
                return {"success": False, "error": f"Plugin filename must end with '.py': {plugin_filename}"}

            # Check for name collision
            plugin_code = plugin_data.get("code", "")
            plugin_name = extract_plugin_name_from_source(plugin_code)

            if plugin_name and plugin_name in reserved_names:
                return {"success": False, "error": f"Plugin name '{plugin_name}' already exists"}

            plugins_dir = project_root / "tests" / "llm" / "plugins"
            plugins_dir.mkdir(parents=True, exist_ok=True)

            plugin_path = plugins_dir / plugin_filename
            plugin_content = plugin_code

            if plugin_path.exists():
                return {"success": False, "error": f"Plugin file already exists: {plugin_path}"}

            files_to_write.append((plugin_path, plugin_content))

        # Problem #5: Atomic write - first write to temp files
        for target_path, content in files_to_write:
            temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
            temp_path.write_text(content)
            temp_files.append((temp_path, target_path))

        # Then rename all temp files to final paths (atomic on same filesystem)
        for temp_path, target_path in temp_files:
            temp_path.rename(target_path)

        return {
            "success": True,
            "test_path": str(test_path),
            "test_content": test_content,
            "plugin_path": str(plugin_path) if plugin_path else None,
            "plugin_content": plugin_content,
        }

    except Exception as e:
        # Problem #5: Rollback on failure - clean up any written files
        for temp_path, target_path in temp_files:
            try:
                # Remove temp file if it still exists
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                # Remove target file if it was renamed
                target_path.unlink(missing_ok=True)
            except Exception:
                pass

        return {"success": False, "error": f"Failed to write files: {e}"}


async def _call_claude_code(
    system_prompt: str,
    user_prompt: str,
    project_root: Path,
    timeout: int,
) -> dict[str, Any]:
    """Call Claude Code subprocess.

    Problem #10 Solution: Configurable timeout parameter.

    Following patterns from runner.py:
    - Uses asyncio.create_subprocess_exec
    - stdin=DEVNULL (critical to prevent hang!)
    - JSON output format

    Args:
        system_prompt: The system prompt with context
        user_prompt: The user's description
        project_root: Project root directory
        timeout: Timeout in seconds

    Returns:
        Dict with "output" key or "error" key
    """
    full_prompt = f"{system_prompt}\n\n---\n\n## User Request\n\n{user_prompt}"

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            full_prompt,
            "--output-format",
            "json",
            stdin=asyncio.subprocess.DEVNULL,  # CRITICAL: prevents CLI hang
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_root,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )

        if proc.returncode != 0:
            stderr_text = stderr.decode() if stderr else "Unknown error"
            return {
                "error": f"Claude exited with code {proc.returncode}",
                "stderr": stderr_text[:500],
            }

        return {"output": stdout.decode()}

    except asyncio.TimeoutError:
        return {"error": f"Claude timeout after {timeout}s"}
    except FileNotFoundError:
        return {"error": "Claude CLI not found. Is 'claude' installed and in PATH?"}
    except Exception as e:
        return {"error": f"Unexpected error: {e}"}


def _generate_schema_docs() -> str:
    """Generate schema documentation from Pydantic models.

    Problem #9 Solution: Dynamic schema generation instead of static docs.

    Returns:
        Markdown documentation of the YAML schema
    """
    lines = ["### TestSpec Fields", ""]

    # TestSpec top-level fields
    for field_name, field_info in TestSpec.model_fields.items():
        required = field_info.is_required()
        annotation = field_info.annotation
        type_str = _annotation_to_str(annotation)
        status = "**REQUIRED**" if required else "optional"
        lines.append(f"- `{field_name}`: {type_str} - {status}")

    lines.extend(["", "### Step Fields", ""])

    # Step fields
    for field_name, field_info in Step.model_fields.items():
        required = field_info.is_required()
        default = field_info.default
        annotation = field_info.annotation
        type_str = _annotation_to_str(annotation)

        desc = f"- `{field_name}`: {type_str}"
        if required:
            desc += " - **REQUIRED**"
        elif default is not None and default != []:
            desc += f" - optional (default: {default!r})"
        else:
            desc += " - optional"
        lines.append(desc)

    return "\n".join(lines)


def _annotation_to_str(annotation: Any) -> str:
    """Convert a type annotation to a readable string."""
    if annotation is None:
        return "None"

    # Handle string annotations
    if isinstance(annotation, str):
        return annotation

    # Get origin and args for generic types
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())

    if origin is not None:
        origin_name = getattr(origin, "__name__", str(origin))

        # Handle Union types (including Optional)
        if origin_name == "Union":
            arg_strs = [_annotation_to_str(arg) for arg in args if arg is not type(None)]
            if len(arg_strs) == 1:
                # This was Optional[X]
                return f"{arg_strs[0]} | None"
            return " | ".join(arg_strs)

        # Handle list, dict, etc.
        if args:
            arg_strs = [_annotation_to_str(arg) for arg in args]
            return f"{origin_name}[{', '.join(arg_strs)}]"

        return origin_name

    # Handle simple types
    if hasattr(annotation, "__name__"):
        return annotation.__name__

    return str(annotation)


def _get_builtin_tools_docs() -> str:
    """Get documentation for built-in tools.

    Returns:
        Markdown documentation of built-in MCP tools
    """
    return """### Built-in Tools

These tools are always available without any plugin:

| Tool | Purpose | Arguments |
|------|---------|-----------|
| `store_value` | Store a value for later retrieval | `{name: str, value: any}` |
| `get_value` | Retrieve a stored value by name | `{name: str, default: any}` |
| `list_values` | List all stored value names | `{}` |
| `sleep` | Wait for specified seconds | `{seconds: float}` |

**Example usage:**
```yaml
- name: "Store user ID"
  tool: store_value
  args: {name: "user_id", value: 123}

- name: "Retrieve user ID"
  tool: get_value
  args: {name: "user_id"}
  expect: "Should return 123"
```
"""
