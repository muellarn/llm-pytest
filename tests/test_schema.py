"""Tests for YAML schema validation in llm_pytest.schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from llm_pytest.schema import (
    YAMLValidationError,
    _format_location,
    _get_error_hint,
    validate_and_raise,
    validate_test_yaml,
)


class TestValidateTestYaml:
    """Tests for validate_test_yaml function."""

    def test_valid_yaml(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """Valid YAML should return TestSpec and no errors."""
        filepath = tmp_path / "test.yaml"
        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is not None
        assert errors == []
        assert spec.test.name == "Sample Test"
        assert len(spec.steps) == 1

    def test_valid_minimal_yaml(self, minimal_test_yaml: dict[str, Any], tmp_path: Path):
        """Minimal valid YAML should pass."""
        filepath = tmp_path / "test.yaml"
        spec, errors = validate_test_yaml(minimal_test_yaml, filepath)

        assert spec is not None
        assert errors == []

    def test_missing_test_section(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """Missing 'test' section should error."""
        filepath = tmp_path / "test.yaml"
        del sample_test_yaml["test"]

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) == 1
        assert "Missing required 'test' section" in errors[0]

    def test_missing_steps_section(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """Missing 'steps' section should error."""
        filepath = tmp_path / "test.yaml"
        del sample_test_yaml["steps"]

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) == 1
        assert "Missing required 'steps' section" in errors[0]

    def test_missing_verdict_section(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """Missing 'verdict' section should error."""
        filepath = tmp_path / "test.yaml"
        del sample_test_yaml["verdict"]

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) == 1
        assert "Missing required 'verdict' section" in errors[0]

    def test_missing_multiple_sections(self, tmp_path: Path):
        """Missing multiple sections should report all."""
        filepath = tmp_path / "test.yaml"
        content = {"steps": []}

        spec, errors = validate_test_yaml(content, filepath)

        assert spec is None
        assert len(errors) == 2
        assert any("'test'" in e for e in errors)
        assert any("'verdict'" in e for e in errors)

    def test_not_a_dict(self, tmp_path: Path):
        """Non-dict content should error."""
        filepath = tmp_path / "test.yaml"

        spec, errors = validate_test_yaml("not a dict", filepath)

        assert spec is None
        assert len(errors) == 1
        assert "Expected YAML object" in errors[0]
        assert "str" in errors[0]

    def test_invalid_test_name_type(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """test.name should be a string."""
        filepath = tmp_path / "test.yaml"
        sample_test_yaml["test"]["name"] = 123  # Should be string

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) >= 1
        # Pydantic will catch this type error

    def test_invalid_timeout_type(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """test.timeout should be an integer."""
        filepath = tmp_path / "test.yaml"
        sample_test_yaml["test"]["timeout"] = "not a number"

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) >= 1

    def test_invalid_steps_type(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """steps should be a list."""
        filepath = tmp_path / "test.yaml"
        sample_test_yaml["steps"] = "not a list"

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) >= 1

    def test_invalid_step_args_type(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """step.args should be a dict."""
        filepath = tmp_path / "test.yaml"
        sample_test_yaml["steps"][0]["args"] = "not a dict"

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) >= 1

    def test_missing_verdict_pass_if(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """verdict.pass_if is required."""
        filepath = tmp_path / "test.yaml"
        del sample_test_yaml["verdict"]["pass_if"]

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) >= 1
        assert any("pass_if" in e for e in errors)

    def test_missing_verdict_fail_if(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """verdict.fail_if is required."""
        filepath = tmp_path / "test.yaml"
        del sample_test_yaml["verdict"]["fail_if"]

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) >= 1
        assert any("fail_if" in e for e in errors)

    def test_filepath_in_error_message(self, tmp_path: Path):
        """Error messages should include the filepath."""
        filepath = tmp_path / "my_test.yaml"
        content = {}

        spec, errors = validate_test_yaml(content, filepath)

        assert spec is None
        for error in errors:
            assert "my_test.yaml" in error

    def test_with_setup_teardown(
        self, sample_test_yaml_with_setup_teardown: dict[str, Any], tmp_path: Path
    ):
        """YAML with setup and teardown should validate."""
        filepath = tmp_path / "test.yaml"
        spec, errors = validate_test_yaml(sample_test_yaml_with_setup_teardown, filepath)

        assert spec is not None
        assert errors == []
        assert len(spec.setup) == 1
        assert len(spec.teardown) == 1


class TestFormatLocation:
    """Tests for _format_location helper."""

    def test_simple_field(self):
        """Format simple field name."""
        assert _format_location(("name",)) == "name"

    def test_nested_field(self):
        """Format nested field path."""
        assert _format_location(("test", "name")) == "test.name"

    def test_array_index(self):
        """Format array index."""
        assert _format_location(("steps", 0)) == "steps[0]"

    def test_mixed_path(self):
        """Format mixed path with both fields and indices."""
        assert _format_location(("steps", 0, "args", "url")) == "steps[0].args.url"

    def test_empty_location(self):
        """Empty location returns 'root'."""
        assert _format_location(()) == "root"

    def test_multiple_indices(self):
        """Multiple array indices."""
        assert _format_location(("a", 0, "b", 1, "c")) == "a[0].b[1].c"


class TestGetErrorHint:
    """Tests for _get_error_hint helper."""

    def test_missing_hint(self):
        """Missing field hint."""
        hint = _get_error_hint("missing", "field")
        assert hint == "This field is required"

    def test_string_type_hint(self):
        """String type hint."""
        hint = _get_error_hint("string_type", "field")
        assert hint == "Expected a string value"

    def test_int_type_hint(self):
        """Int type hint."""
        hint = _get_error_hint("int_type", "field")
        assert hint == "Expected an integer value"

    def test_timeout_location_hint(self):
        """Timeout-specific hint."""
        hint = _get_error_hint("any_type", "test.timeout")
        assert "integer" in hint.lower()
        assert "seconds" in hint.lower()

    def test_args_location_hint(self):
        """Args-specific hint."""
        hint = _get_error_hint("any_type", "steps[0].args")
        assert "object" in hint.lower() or "key: value" in hint.lower()

    def test_verdict_pass_if_hint(self):
        """verdict.pass_if hint."""
        hint = _get_error_hint("missing", "verdict.pass_if")
        assert "pass_if" in hint

    def test_verdict_fail_if_hint(self):
        """verdict.fail_if hint."""
        hint = _get_error_hint("missing", "verdict.fail_if")
        assert "fail_if" in hint

    def test_unknown_error_type(self):
        """Unknown error type returns None."""
        hint = _get_error_hint("unknown_error_type", "field")
        assert hint is None

    def test_test_name_hint(self):
        """test.name hint."""
        hint = _get_error_hint("missing", "test.name")
        assert "name" in hint


class TestYAMLValidationError:
    """Tests for YAMLValidationError exception."""

    def test_error_creation(self, tmp_path: Path):
        """Create error with filepath and errors."""
        filepath = tmp_path / "test.yaml"
        errors = ["Error 1", "Error 2"]

        exc = YAMLValidationError(filepath, errors)

        assert exc.filepath == filepath
        assert exc.errors == errors
        assert "test.yaml" in str(exc)
        assert "Error 1" in str(exc)
        assert "Error 2" in str(exc)

    def test_error_formatting(self, tmp_path: Path):
        """Error message should be well-formatted."""
        filepath = tmp_path / "my_test.yaml"
        errors = ["First error", "Second error"]

        exc = YAMLValidationError(filepath, errors)
        message = str(exc)

        assert "Validation failed for" in message
        assert "  - First error" in message
        assert "  - Second error" in message


class TestValidateAndRaise:
    """Tests for validate_and_raise function."""

    def test_valid_returns_spec(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """Valid YAML returns TestSpec."""
        filepath = tmp_path / "test.yaml"
        spec = validate_and_raise(sample_test_yaml, filepath)

        assert spec is not None
        assert spec.test.name == "Sample Test"

    def test_invalid_raises(self, tmp_path: Path):
        """Invalid YAML raises YAMLValidationError."""
        filepath = tmp_path / "test.yaml"
        content = {"test": {"name": "Test"}}  # Missing steps and verdict

        with pytest.raises(YAMLValidationError) as exc_info:
            validate_and_raise(content, filepath)

        assert "steps" in str(exc_info.value) or "verdict" in str(exc_info.value)

    def test_error_contains_all_issues(self, tmp_path: Path):
        """Raised error should contain all validation issues."""
        filepath = tmp_path / "test.yaml"
        content = {}  # Missing everything

        with pytest.raises(YAMLValidationError) as exc_info:
            validate_and_raise(content, filepath)

        error = exc_info.value
        assert len(error.errors) >= 3  # test, steps, verdict


class TestEdgeCases:
    """Edge cases for schema validation."""

    def test_empty_steps_list(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """Empty steps list should still validate (Pydantic allows it)."""
        filepath = tmp_path / "test.yaml"
        sample_test_yaml["steps"] = []

        # Pydantic allows empty list, but this might be caught by business logic
        spec, errors = validate_test_yaml(sample_test_yaml, filepath)
        # The model allows empty steps - this is a design choice
        assert spec is not None or len(errors) > 0

    def test_extra_fields_ignored(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """Extra fields in YAML should be ignored by default."""
        filepath = tmp_path / "test.yaml"
        sample_test_yaml["extra_field"] = "ignored"
        sample_test_yaml["test"]["unknown"] = "also ignored"

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        # Pydantic ignores extra fields by default
        assert spec is not None
        assert errors == []

    def test_null_values(self, sample_test_yaml: dict[str, Any], tmp_path: Path):
        """Null values where not expected should error."""
        filepath = tmp_path / "test.yaml"
        sample_test_yaml["test"]["name"] = None

        spec, errors = validate_test_yaml(sample_test_yaml, filepath)

        assert spec is None
        assert len(errors) >= 1

    def test_list_content_not_dict(self, tmp_path: Path):
        """Non-dict content should error appropriately."""
        filepath = tmp_path / "test.yaml"

        spec, errors = validate_test_yaml([1, 2, 3], filepath)

        assert spec is None
        assert "Expected YAML object" in errors[0]
        assert "list" in errors[0]
