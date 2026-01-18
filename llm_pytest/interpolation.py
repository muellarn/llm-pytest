"""Variable interpolation for test step arguments.

Supports ${variable} syntax to reference:
- ${stored.name} - Values saved via store_value tool
- ${step_name.field} - Results from previous steps (if saved with save_as)

Example:
    args:
      user_id: "${created_user.id}"
      token: "${stored.auth_token}"
"""

from __future__ import annotations

import re
from typing import Any

# Pattern matches ${...} with nested dot notation
VARIABLE_PATTERN = re.compile(r"\$\{([^}]+)\}")


def interpolate_value(value: Any, context: dict[str, Any]) -> Any:
    """Interpolate variables in a single value.

    Recursively processes strings, dicts, and lists to replace ${variable}
    references with their corresponding values from the context.

    Args:
        value: The value to interpolate (string, dict, list, or primitive)
        context: Dictionary of available variables

    Returns:
        The interpolated value with all ${...} references resolved

    Examples:
        >>> context = {"stored": {"token": "abc123"}, "user": {"id": 42}}
        >>> interpolate_value("Token: ${stored.token}", context)
        'Token: abc123'
        >>> interpolate_value({"id": "${user.id}"}, context)
        {'id': '42'}
        >>> interpolate_value(["${stored.token}", "${user.id}"], context)
        ['abc123', '42']
    """
    if isinstance(value, str):
        return _interpolate_string(value, context)
    elif isinstance(value, dict):
        return {k: interpolate_value(v, context) for k, v in value.items()}
    elif isinstance(value, list):
        return [interpolate_value(item, context) for item in value]
    return value


def _interpolate_string(text: str, context: dict[str, Any]) -> str:
    """Interpolate ${...} variables in a string.

    Args:
        text: The string containing variable references
        context: Dictionary of available variables

    Returns:
        String with all resolved variable references replaced
    """

    def replace(match: re.Match) -> str:
        path = match.group(1)
        value = _resolve_path(path, context)
        if value is None:
            # Return original if not found
            return match.group(0)
        return str(value)

    return VARIABLE_PATTERN.sub(replace, text)


def _resolve_path(path: str, context: dict[str, Any]) -> Any:
    """Resolve a dot-separated path in the context.

    Navigates through nested dictionaries using dot notation.

    Args:
        path: Dot-separated path (e.g., "stored.token" or "user.address.city")
        context: Dictionary to resolve the path against

    Returns:
        The resolved value, or None if the path cannot be resolved

    Examples:
        >>> context = {"stored": {"token": "abc"}, "user": {"address": {"city": "NYC"}}}
        >>> _resolve_path("stored.token", context)
        'abc'
        >>> _resolve_path("user.address.city", context)
        'NYC'
        >>> _resolve_path("nonexistent.path", context)
        None
    """
    parts = path.split(".")
    value = context

    for part in parts:
        if isinstance(value, dict):
            if part not in value:
                return None
            value = value[part]
        else:
            return None

    return value


def interpolate_step_args(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Interpolate all variables in step arguments.

    Convenience function for interpolating step arguments, which are always
    dictionaries.

    Args:
        args: The step arguments dictionary
        context: Available variables (stored values, previous results)

    Returns:
        New args dict with all ${...} references resolved

    Examples:
        >>> context = {
        ...     "stored": {"auth_token": "secret123"},
        ...     "created_user": {"id": 42, "name": "Alice"}
        ... }
        >>> args = {
        ...     "user_id": "${created_user.id}",
        ...     "token": "${stored.auth_token}",
        ...     "name": "${created_user.name}"
        ... }
        >>> interpolate_step_args(args, context)
        {'user_id': '42', 'token': 'secret123', 'name': 'Alice'}
    """
    result = interpolate_value(args, context)
    # Type assertion: interpolate_value on a dict returns a dict
    if not isinstance(result, dict):
        # This should never happen when passing a dict
        return args
    return result
