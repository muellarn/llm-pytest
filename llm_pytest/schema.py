"""YAML schema validation with helpful error messages.

This module provides validation for test YAML files with clear,
actionable error messages that help users fix their test definitions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import TestSpec


class YAMLValidationError(Exception):
    """Raised when YAML validation fails with detailed error info."""

    def __init__(self, filepath: Path, errors: list[str]):
        self.filepath = filepath
        self.errors = errors
        message = f"Validation failed for {filepath}:\n" + "\n".join(
            f"  - {e}" for e in errors
        )
        super().__init__(message)


def validate_test_yaml(
    content: dict[str, Any],
    filepath: Path,
) -> tuple[TestSpec | None, list[str]]:
    """Validate YAML content and return TestSpec or errors.

    Args:
        content: Parsed YAML content (dict)
        filepath: Path to the YAML file (for error messages)

    Returns:
        Tuple of (TestSpec or None, list of error messages)

    Example:
        >>> content = yaml.safe_load(path.read_text())
        >>> spec, errors = validate_test_yaml(content, path)
        >>> if errors:
        ...     for e in errors:
        ...         print(e)
    """
    errors = []

    # Check for required top-level keys
    if not isinstance(content, dict):
        errors.append(
            f"{filepath}: Expected YAML object, got {type(content).__name__}"
        )
        return None, errors

    if "test" not in content:
        errors.append(f"{filepath}: Missing required 'test' section")

    if "steps" not in content:
        errors.append(f"{filepath}: Missing required 'steps' section")

    if "verdict" not in content:
        errors.append(f"{filepath}: Missing required 'verdict' section")

    if errors:
        return None, errors

    # Try Pydantic validation
    try:
        spec = TestSpec.model_validate(content)
        return spec, []
    except ValidationError as e:
        for error in e.errors():
            loc = _format_location(error["loc"])
            msg = error["msg"]
            error_type = error["type"]

            # Make error messages more helpful
            hint = _get_error_hint(error_type, loc)
            full_msg = f"{filepath}:{loc}: {msg}"
            if hint:
                full_msg += f" ({hint})"
            errors.append(full_msg)

        return None, errors


def _format_location(loc: tuple) -> str:
    """Format Pydantic error location as readable path."""
    parts = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            if parts:
                parts.append(f".{item}")
            else:
                parts.append(str(item))
    return "".join(parts) or "root"


def _get_error_hint(error_type: str, location: str) -> str | None:
    """Provide helpful hints for common errors."""
    hints = {
        "missing": "This field is required",
        "string_type": "Expected a string value",
        "int_type": "Expected an integer value",
        "dict_type": "Expected a YAML object/mapping",
        "list_type": "Expected a YAML list/array",
        "bool_type": "Expected true or false",
    }

    # Location-specific hints
    if "timeout" in location:
        return "Timeout should be an integer (seconds)"
    if "args" in location:
        return "Args should be a YAML object with key: value pairs"
    if "steps" in location and "tool" in location:
        return "Each step needs a 'tool' field specifying the MCP tool name"
    if "test" in location and "name" in location:
        return "The test section requires a 'name' field"
    if "verdict" in location and "pass_if" in location:
        return "The verdict section requires a 'pass_if' field"
    if "verdict" in location and "fail_if" in location:
        return "The verdict section requires a 'fail_if' field"

    return hints.get(error_type)


def validate_and_raise(content: dict[str, Any], filepath: Path) -> TestSpec:
    """Validate YAML and raise YAMLValidationError if invalid.

    Args:
        content: Parsed YAML content
        filepath: Path to the YAML file

    Returns:
        Valid TestSpec

    Raises:
        YAMLValidationError: If validation fails
    """
    spec, errors = validate_test_yaml(content, filepath)
    if errors:
        raise YAMLValidationError(filepath, errors)
    return spec
