"""Tests for variable interpolation in llm_pytest.interpolation."""

from __future__ import annotations

import pytest

from llm_pytest.interpolation import (
    VARIABLE_PATTERN,
    _interpolate_string,
    _resolve_path,
    interpolate_step_args,
    interpolate_value,
)


class TestVariablePattern:
    """Tests for the VARIABLE_PATTERN regex."""

    def test_simple_variable(self):
        """Match simple ${variable} pattern."""
        match = VARIABLE_PATTERN.search("${foo}")
        assert match is not None
        assert match.group(1) == "foo"

    def test_nested_path(self):
        """Match nested ${foo.bar.baz} pattern."""
        match = VARIABLE_PATTERN.search("${foo.bar.baz}")
        assert match is not None
        assert match.group(1) == "foo.bar.baz"

    def test_in_text(self):
        """Match variable embedded in text."""
        matches = VARIABLE_PATTERN.findall("Hello ${name}, your id is ${user.id}")
        assert matches == ["name", "user.id"]

    def test_no_match_incomplete(self):
        """Should not match incomplete patterns."""
        assert VARIABLE_PATTERN.search("${") is None
        assert VARIABLE_PATTERN.search("$foo") is None
        assert VARIABLE_PATTERN.search("{foo}") is None

    def test_multiple_variables(self):
        """Find all variables in a string."""
        text = "${a} and ${b.c} and ${d.e.f}"
        matches = VARIABLE_PATTERN.findall(text)
        assert matches == ["a", "b.c", "d.e.f"]


class TestResolvePath:
    """Tests for _resolve_path function."""

    def test_simple_key(self, interpolation_context):
        """Resolve a simple top-level key."""
        result = _resolve_path("simple_value", interpolation_context)
        assert result == "hello"

    def test_nested_one_level(self, interpolation_context):
        """Resolve one level of nesting."""
        result = _resolve_path("stored.auth_token", interpolation_context)
        assert result == "secret123"

    def test_nested_two_levels(self, interpolation_context):
        """Resolve two levels of nesting."""
        result = _resolve_path("created_user.address.city", interpolation_context)
        assert result == "New York"

    def test_missing_key(self, interpolation_context):
        """Return None for missing top-level key."""
        result = _resolve_path("nonexistent", interpolation_context)
        assert result is None

    def test_missing_nested_key(self, interpolation_context):
        """Return None for missing nested key."""
        result = _resolve_path("created_user.missing", interpolation_context)
        assert result is None

    def test_partial_path_missing(self, interpolation_context):
        """Return None when intermediate path is missing."""
        result = _resolve_path("created_user.address.zipcode", interpolation_context)
        assert result is None

    def test_numeric_value(self, interpolation_context):
        """Resolve numeric values."""
        result = _resolve_path("numeric_value", interpolation_context)
        assert result == 100

    def test_object_value(self, interpolation_context):
        """Resolve object/dict values."""
        result = _resolve_path("created_user.address", interpolation_context)
        assert result == {"city": "New York", "country": "USA"}

    def test_empty_path(self, interpolation_context):
        """Empty path should return None."""
        result = _resolve_path("", interpolation_context)
        assert result is None

    def test_path_through_non_dict(self, interpolation_context):
        """Path through non-dict value should return None."""
        result = _resolve_path("simple_value.something", interpolation_context)
        assert result is None


class TestInterpolateString:
    """Tests for _interpolate_string function."""

    def test_simple_variable(self, interpolation_context):
        """Interpolate a simple variable."""
        result = _interpolate_string("Token: ${stored.auth_token}", interpolation_context)
        assert result == "Token: secret123"

    def test_multiple_variables(self, interpolation_context):
        """Interpolate multiple variables."""
        result = _interpolate_string(
            "User ${created_user.name} (id=${created_user.id})",
            interpolation_context,
        )
        assert result == "User Alice (id=42)"

    def test_missing_variable_unchanged(self, interpolation_context):
        """Missing variable should remain as-is."""
        result = _interpolate_string("Value: ${nonexistent}", interpolation_context)
        assert result == "Value: ${nonexistent}"

    def test_mixed_found_and_missing(self, interpolation_context):
        """Mix of found and missing variables."""
        result = _interpolate_string(
            "${created_user.name} and ${missing}",
            interpolation_context,
        )
        assert result == "Alice and ${missing}"

    def test_no_variables(self, interpolation_context):
        """String without variables unchanged."""
        result = _interpolate_string("No variables here", interpolation_context)
        assert result == "No variables here"

    def test_numeric_converted_to_string(self, interpolation_context):
        """Numeric values should be converted to strings."""
        result = _interpolate_string("ID: ${created_user.id}", interpolation_context)
        assert result == "ID: 42"


class TestInterpolateValue:
    """Tests for interpolate_value function."""

    def test_string_value(self, interpolation_context):
        """Interpolate a string value."""
        result = interpolate_value("Hello ${created_user.name}", interpolation_context)
        assert result == "Hello Alice"

    def test_dict_value(self, interpolation_context):
        """Interpolate values within a dict."""
        value = {
            "user": "${created_user.name}",
            "token": "${stored.auth_token}",
        }
        result = interpolate_value(value, interpolation_context)
        assert result == {"user": "Alice", "token": "secret123"}

    def test_nested_dict(self, interpolation_context):
        """Interpolate values in nested dicts."""
        value = {
            "outer": {
                "inner": "${created_user.email}",
            },
        }
        result = interpolate_value(value, interpolation_context)
        assert result == {"outer": {"inner": "alice@example.com"}}

    def test_list_value(self, interpolation_context):
        """Interpolate values within a list."""
        value = ["${stored.auth_token}", "${stored.api_key}"]
        result = interpolate_value(value, interpolation_context)
        assert result == ["secret123", "key456"]

    def test_mixed_list_and_dict(self, interpolation_context):
        """Interpolate mixed structures."""
        value = {
            "items": [
                {"name": "${created_user.name}"},
                {"id": "${created_user.id}"},
            ],
        }
        result = interpolate_value(value, interpolation_context)
        assert result == {
            "items": [
                {"name": "Alice"},
                {"id": "42"},
            ],
        }

    def test_non_string_passthrough(self, interpolation_context):
        """Non-string primitives pass through unchanged."""
        assert interpolate_value(42, interpolation_context) == 42
        assert interpolate_value(3.14, interpolation_context) == 3.14
        assert interpolate_value(True, interpolation_context) is True
        assert interpolate_value(None, interpolation_context) is None

    def test_empty_dict(self, interpolation_context):
        """Empty dict returns empty dict."""
        result = interpolate_value({}, interpolation_context)
        assert result == {}

    def test_empty_list(self, interpolation_context):
        """Empty list returns empty list."""
        result = interpolate_value([], interpolation_context)
        assert result == []

    def test_dict_with_non_string_keys(self, interpolation_context):
        """Dict keys are not interpolated (only values)."""
        # This is expected behavior - keys remain as-is
        value = {"${key}": "${created_user.name}"}
        result = interpolate_value(value, interpolation_context)
        assert result == {"${key}": "Alice"}


class TestInterpolateStepArgs:
    """Tests for interpolate_step_args function."""

    def test_basic_interpolation(self, interpolation_context):
        """Basic args interpolation."""
        args = {
            "user_id": "${created_user.id}",
            "token": "${stored.auth_token}",
        }
        result = interpolate_step_args(args, interpolation_context)
        assert result == {"user_id": "42", "token": "secret123"}

    def test_empty_args(self, interpolation_context):
        """Empty args returns empty dict."""
        result = interpolate_step_args({}, interpolation_context)
        assert result == {}

    def test_no_variables(self, interpolation_context):
        """Args without variables unchanged."""
        args = {"url": "http://example.com", "timeout": 30}
        result = interpolate_step_args(args, interpolation_context)
        assert result == {"url": "http://example.com", "timeout": 30}

    def test_partial_interpolation(self, interpolation_context):
        """Mix of variables and literals."""
        args = {
            "name": "${created_user.name}",
            "fixed": "constant",
            "missing": "${does.not.exist}",
        }
        result = interpolate_step_args(args, interpolation_context)
        assert result == {
            "name": "Alice",
            "fixed": "constant",
            "missing": "${does.not.exist}",
        }

    def test_nested_args(self, interpolation_context):
        """Nested argument structures."""
        args = {
            "headers": {
                "Authorization": "Bearer ${stored.auth_token}",
                "X-User-Id": "${created_user.id}",
            },
            "body": {
                "user": "${created_user.name}",
            },
        }
        result = interpolate_step_args(args, interpolation_context)
        assert result == {
            "headers": {
                "Authorization": "Bearer secret123",
                "X-User-Id": "42",
            },
            "body": {
                "user": "Alice",
            },
        }

    def test_list_in_args(self, interpolation_context):
        """Lists within args are interpolated."""
        args = {
            "users": ["${created_user.name}"],
            "tokens": ["${stored.auth_token}", "${stored.api_key}"],
        }
        result = interpolate_step_args(args, interpolation_context)
        assert result == {
            "users": ["Alice"],
            "tokens": ["secret123", "key456"],
        }


class TestEdgeCases:
    """Edge cases and unusual inputs."""

    def test_empty_context(self):
        """Interpolation with empty context."""
        result = interpolate_value("${anything}", {})
        assert result == "${anything}"

    def test_deeply_nested_path(self):
        """Deeply nested context path."""
        context = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        result = interpolate_value("${a.b.c.d.e}", context)
        assert result == "deep"

    def test_variable_only_string(self):
        """String that is only a variable reference."""
        context = {"value": "result"}
        result = interpolate_value("${value}", context)
        assert result == "result"

    def test_adjacent_variables(self):
        """Two variables directly next to each other."""
        context = {"a": "Hello", "b": "World"}
        result = interpolate_value("${a}${b}", context)
        assert result == "HelloWorld"

    def test_unicode_values(self):
        """Unicode values in context."""
        context = {"greeting": "Bonjour", "emoji": "Hello 🌍"}
        result = interpolate_value("${greeting} - ${emoji}", context)
        assert result == "Bonjour - Hello 🌍"

    def test_special_characters_in_value(self):
        """Special characters in resolved values."""
        context = {"special": "a$b{c}d"}
        result = interpolate_value("Value: ${special}", context)
        assert result == "Value: a$b{c}d"

    def test_boolean_context_value(self):
        """Boolean values in context are stringified."""
        context = {"flag": True, "other": False}
        result = interpolate_value("Flag is ${flag}", context)
        assert result == "Flag is True"
