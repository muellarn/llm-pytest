"""Tests for create_test tool."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from llm_pytest.tools.create_test import (
    JSON_EXTRACT_PATTERN,
    SAFE_FILENAME_PATTERN,
    _annotation_to_str,
    _atomic_write_files,
    _call_claude_code,
    _generate_schema_docs,
    _parse_claude_output,
    _render_system_prompt,
    _validate_generated_content,
    create_test_tool,
)


class TestFilenamePattern:
    """Tests for filename validation pattern (Problem #6)."""

    def test_valid_test_filenames(self):
        """Valid test filenames should match."""
        valid_names = [
            "test_user.yaml",
            "test_user_api.yaml",
            "test-user-api.yaml",  # Problem #6: hyphens allowed
            "test_a.yaml",
            "test_123.yaml",
            "test_user-registration.yaml",
        ]
        for name in valid_names:
            assert SAFE_FILENAME_PATTERN.match(name), f"Should match: {name}"

    def test_valid_plugin_filenames(self):
        """Valid plugin filenames should match."""
        valid_names = [
            "user_api.py",
            "database.py",
            "my-plugin.py",  # Problem #6: hyphens allowed
            "plugin123.py",
        ]
        for name in valid_names:
            assert SAFE_FILENAME_PATTERN.match(name), f"Should match: {name}"

    def test_invalid_filenames(self):
        """Invalid filenames should not match."""
        invalid_names = [
            "../test.yaml",  # Path traversal
            "Test_user.yaml",  # Uppercase
            "test user.yaml",  # Space
            ".hidden.yaml",  # Starts with dot
            "test.yml",  # Wrong extension
            "1test.yaml",  # Starts with number
        ]
        for name in invalid_names:
            assert not SAFE_FILENAME_PATTERN.match(name), f"Should not match: {name}"


class TestJsonExtractPattern:
    """Tests for JSON extraction regex (Problem #4)."""

    def test_extracts_from_markdown_json_block(self):
        text = '''Here's the test:
```json
{"test": {"filename": "test.yaml", "code": "..."}}
```
Done!'''
        match = JSON_EXTRACT_PATTERN.search(text)
        assert match is not None
        json_str = match.group(1) or match.group(2)
        data = json.loads(json_str)
        assert "test" in data

    def test_extracts_from_plain_markdown_block(self):
        text = '''```
{"plugin": null, "test": {"filename": "test.yaml", "code": "..."}}
```'''
        match = JSON_EXTRACT_PATTERN.search(text)
        assert match is not None

    def test_extracts_raw_json(self):
        text = '{"test": {"filename": "test_example.yaml", "code": "test: ..."}}'
        match = JSON_EXTRACT_PATTERN.search(text)
        assert match is not None

    def test_handles_multiline_json(self):
        text = '''```json
{
  "plugin": null,
  "test": {
    "filename": "test_api.yaml",
    "code": "test:\\n  name: Test"
  }
}
```'''
        match = JSON_EXTRACT_PATTERN.search(text)
        assert match is not None


class TestParseClaudeOutput:
    """Tests for robust JSON parsing (Problem #4)."""

    def test_parses_direct_json(self):
        output = '{"test": {"filename": "test.yaml", "code": "..."}}'
        result = _parse_claude_output(output)
        assert "test" in result
        assert result["test"]["filename"] == "test.yaml"

    def test_parses_claude_wrapper_format(self):
        """Claude's --output-format json wraps result."""
        inner = '{"test": {"filename": "test.yaml", "code": "..."}}'
        output = json.dumps({"result": inner})
        result = _parse_claude_output(output)
        assert "test" in result

    def test_parses_markdown_code_block(self):
        output = '''I've created the test for you:

```json
{"plugin": null, "test": {"filename": "test_api.yaml", "code": "test: ..."}}
```

Let me know if you need changes.'''
        result = _parse_claude_output(output)
        assert "test" in result
        assert result["plugin"] is None

    def test_returns_error_for_invalid_json(self):
        output = "This is not JSON at all"
        result = _parse_claude_output(output)
        assert "error" in result

    def test_returns_error_for_malformed_json(self):
        output = '{"test": {"filename": "test.yaml", "code": }}'  # Missing value
        result = _parse_claude_output(output)
        assert "error" in result


class TestValidateGeneratedContent:
    """Tests for content validation (Problem #3)."""

    def test_validates_valid_yaml(self, tmp_path: Path):
        parsed = {
            "test": {
                "filename": "test_example.yaml",
                "code": """
test:
  name: "Example Test"
steps:
  - tool: store_value
    args: {name: "x", value: 1}
verdict:
  pass_if: "Value stored"
  fail_if: "Error occurred"
""",
            },
            "plugin": None,
        }
        result = _validate_generated_content(parsed, tmp_path)
        assert "error" not in result
        assert result.get("valid") is True

    def test_rejects_invalid_yaml_syntax(self, tmp_path: Path):
        parsed = {
            "test": {
                "filename": "test.yaml",
                "code": "this: is: not: valid: yaml: {{{{",
            }
        }
        result = _validate_generated_content(parsed, tmp_path)
        assert "error" in result

    def test_rejects_invalid_yaml_schema(self, tmp_path: Path):
        """Missing required fields should fail validation."""
        parsed = {
            "test": {
                "filename": "test.yaml",
                "code": """
test:
  name: "Test"
# Missing steps and verdict
""",
            }
        }
        result = _validate_generated_content(parsed, tmp_path)
        assert "error" in result

    def test_validates_plugin_python_syntax(self, tmp_path: Path):
        parsed = {
            "test": {
                "filename": "test.yaml",
                "code": """
test:
  name: "Test"
steps:
  - tool: foo
verdict:
  pass_if: "pass"
  fail_if: "fail"
""",
            },
            "plugin": {
                "filename": "plugin.py",
                "code": "def invalid syntax here {{{{",
            },
        }
        result = _validate_generated_content(parsed, tmp_path)
        assert "error" in result
        assert "Python syntax" in str(result.get("details", []))

    def test_rejects_missing_test_content(self, tmp_path: Path):
        parsed = {"plugin": None}  # No test
        result = _validate_generated_content(parsed, tmp_path)
        assert "error" in result
        assert "No test content" in result["error"]


class TestAtomicWriteFiles:
    """Tests for atomic file writing (Problem #5)."""

    @pytest.mark.anyio
    async def test_writes_test_file(self, tmp_path: Path):
        parsed = {
            "test": {
                "filename": "test_example.yaml",
                "code": "test:\n  name: Example\nsteps: []\nverdict:\n  pass_if: x\n  fail_if: y",
            },
            "plugin": None,
        }
        # Create required directory structure
        (tmp_path / "tests" / "llm").mkdir(parents=True)

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is True
        assert "test_path" in result
        test_path = Path(result["test_path"])
        assert test_path.exists()
        assert test_path.read_text() == parsed["test"]["code"]

    @pytest.mark.anyio
    async def test_writes_plugin_and_test(self, tmp_path: Path):
        parsed = {
            "test": {
                "filename": "test_api.yaml",
                "code": "test:\n  name: API\nsteps: []\nverdict:\n  pass_if: x\n  fail_if: y",
            },
            "plugin": {
                "filename": "api_plugin.py",
                "code": 'from llm_pytest import LLMPlugin\n\nclass APIPlugin(LLMPlugin):\n    name = "api"\n',
            },
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is True
        assert result["plugin_path"] is not None
        plugin_path = Path(result["plugin_path"])
        assert plugin_path.exists()

    @pytest.mark.anyio
    async def test_rejects_existing_test_file(self, tmp_path: Path):
        """Should not overwrite existing files."""
        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        existing_file = tests_dir / "test_existing.yaml"
        existing_file.write_text("existing content")

        parsed = {
            "test": {"filename": "test_existing.yaml", "code": "new content"},
            "plugin": None,
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is False
        assert "already exists" in result["error"]
        assert existing_file.read_text() == "existing content"

    @pytest.mark.anyio
    async def test_rejects_reserved_plugin_name(self, tmp_path: Path):
        parsed = {
            "test": {"filename": "test_api.yaml", "code": "..."},
            "plugin": {
                "filename": "api.py",
                "code": 'from llm_pytest import LLMPlugin\n\nclass P(LLMPlugin):\n    name = "existing"\n',
            },
        }

        result = await _atomic_write_files(
            parsed, tmp_path, reserved_names={"existing"}, filename_override=None
        )

        assert result["success"] is False
        assert "already exists" in result["error"]

    @pytest.mark.anyio
    async def test_uses_filename_override(self, tmp_path: Path):
        parsed = {
            "test": {"filename": "test_generated.yaml", "code": "test content"},
            "plugin": None,
        }
        (tmp_path / "tests" / "llm").mkdir(parents=True)

        result = await _atomic_write_files(
            parsed, tmp_path, set(), filename_override="test_override.yaml"
        )

        assert result["success"] is True
        assert "test_override.yaml" in result["test_path"]

    @pytest.mark.anyio
    async def test_validates_filename_format(self, tmp_path: Path):
        """Problem #6 & #7: Filename validation."""
        parsed = {
            "test": {"filename": "../escape.yaml", "code": "..."},
            "plugin": None,
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is False
        assert "Invalid test filename" in result["error"]

    @pytest.mark.anyio
    async def test_requires_test_prefix(self, tmp_path: Path):
        parsed = {
            "test": {"filename": "not_a_test.yaml", "code": "..."},
            "plugin": None,
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is False
        assert "must start with 'test_'" in result["error"]


class TestRenderSystemPrompt:
    """Tests for system prompt rendering (Problems #1, #9)."""

    def test_renders_without_error(self):
        """Problem #1: Should use Jinja2 safely."""
        prompt = _render_system_prompt(
            plugins_info=[],
            reserved_names=set(),
            extend_plugin=None,
        )
        assert "LLM-Pytest" in prompt
        assert "YAML Test Schema" in prompt

    def test_includes_plugin_info(self):
        plugins_info = [
            {
                "filename": "api.py",
                "name": "api",
                "tools": [
                    {
                        "name": "api_get",
                        "description": "Get data",
                        "parameters": [{"name": "url", "type": "str", "required": True}],
                    }
                ],
            }
        ]
        prompt = _render_system_prompt(
            plugins_info=plugins_info,
            reserved_names={"api"},
            extend_plugin=None,
        )
        assert "api_get" in prompt
        assert "api" in prompt

    def test_includes_reserved_names(self):
        prompt = _render_system_prompt(
            plugins_info=[],
            reserved_names={"plugin_a", "plugin_b"},
            extend_plugin=None,
        )
        assert "plugin_a" in prompt
        assert "plugin_b" in prompt

    def test_includes_extend_plugin_mode(self):
        """Problem #8: Plugin extension support."""
        prompt = _render_system_prompt(
            plugins_info=[],
            reserved_names=set(),
            extend_plugin="existing_plugin",
        )
        assert "existing_plugin" in prompt
        assert "extend" in prompt.lower()

    def test_handles_special_characters_safely(self):
        """Problem #1: User input with special chars should not break."""
        plugins_info = [
            {
                "filename": "test.py",
                "name": "test",
                "tools": [
                    {
                        "name": "test_method",
                        "description": "Description with {braces} and $pecial chars",
                        "parameters": [],
                    }
                ],
            }
        ]
        # Should not raise an exception
        prompt = _render_system_prompt(
            plugins_info=plugins_info,
            reserved_names=set(),
            extend_plugin=None,
        )
        assert "{braces}" in prompt


class TestGenerateSchemaDocs:
    """Tests for dynamic schema generation (Problem #9)."""

    def test_generates_schema_docs(self):
        docs = _generate_schema_docs()
        assert "TestSpec Fields" in docs
        assert "Step Fields" in docs
        assert "test" in docs
        assert "steps" in docs
        assert "verdict" in docs

    def test_includes_field_requirements(self):
        docs = _generate_schema_docs()
        assert "REQUIRED" in docs

    def test_includes_step_fields(self):
        docs = _generate_schema_docs()
        # Check some Step fields are documented
        assert "tool" in docs
        assert "args" in docs
        assert "expect" in docs
        assert "retry" in docs


class TestCallClaudeCode:
    """Tests for _call_claude_code subprocess handling."""

    @pytest.mark.anyio
    async def test_returns_output_on_success(self, tmp_path: Path):
        """Test successful Claude Code call."""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(
            return_value=(b'{"test": "output"}', b"")
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await _call_claude_code(
                system_prompt="system",
                user_prompt="user",
                project_root=tmp_path,
                timeout=30,
            )

        assert "output" in result
        assert result["output"] == '{"test": "output"}'

    @pytest.mark.anyio
    async def test_returns_error_on_nonzero_exit(self, tmp_path: Path):
        """Test error handling for non-zero exit code."""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(
            return_value=(b"", b"Error message")
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await _call_claude_code(
                system_prompt="system",
                user_prompt="user",
                project_root=tmp_path,
                timeout=30,
            )

        assert "error" in result
        assert "exited with code 1" in result["error"]
        assert "stderr" in result

    @pytest.mark.anyio
    async def test_returns_error_on_timeout(self, tmp_path: Path):
        """Test timeout handling."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await _call_claude_code(
                system_prompt="system",
                user_prompt="user",
                project_root=tmp_path,
                timeout=30,
            )

        assert "error" in result
        assert "timeout" in result["error"].lower()

    @pytest.mark.anyio
    async def test_returns_error_when_claude_not_found(self, tmp_path: Path):
        """Test error when claude CLI is not installed."""
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("claude not found"),
        ):
            result = await _call_claude_code(
                system_prompt="system",
                user_prompt="user",
                project_root=tmp_path,
                timeout=30,
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.anyio
    async def test_returns_error_on_unexpected_exception(self, tmp_path: Path):
        """Test handling of unexpected exceptions."""
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=RuntimeError("Unexpected error"),
        ):
            result = await _call_claude_code(
                system_prompt="system",
                user_prompt="user",
                project_root=tmp_path,
                timeout=30,
            )

        assert "error" in result
        assert "Unexpected" in result["error"]


class TestCreateTestTool:
    """Tests for the main create_test_tool function with mocking."""

    @pytest.mark.anyio
    async def test_returns_error_when_claude_fails(self, tmp_path: Path):
        """Test that Claude errors are propagated."""
        with patch(
            "llm_pytest.tools.create_test._call_claude_code",
            return_value={"error": "Claude failed"},
        ):
            result = await create_test_tool(
                description="Test something",
                project_root=tmp_path,
            )

        assert result["success"] is False
        assert "Claude failed" in result["error"]

    @pytest.mark.anyio
    async def test_returns_error_when_json_parsing_fails(self, tmp_path: Path):
        """Test that JSON parsing errors are propagated."""
        with patch(
            "llm_pytest.tools.create_test._call_claude_code",
            return_value={"output": "not valid json at all"},
        ):
            result = await create_test_tool(
                description="Test something",
                project_root=tmp_path,
            )

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.anyio
    async def test_returns_error_when_validation_fails(self, tmp_path: Path):
        """Test that validation errors are propagated."""
        invalid_yaml = '{"test": {"filename": "test_x.yaml", "code": "invalid: yaml: {{"}}'
        with patch(
            "llm_pytest.tools.create_test._call_claude_code",
            return_value={"output": invalid_yaml},
        ):
            result = await create_test_tool(
                description="Test something",
                project_root=tmp_path,
            )

        assert result["success"] is False

    @pytest.mark.anyio
    async def test_successful_test_creation(self, tmp_path: Path):
        """Test successful end-to-end test creation."""
        valid_output = json.dumps({
            "plugin": None,
            "test": {
                "filename": "test_example.yaml",
                "code": """test:
  name: "Example"
steps:
  - tool: store_value
    args: {name: x, value: 1}
verdict:
  pass_if: "stored"
  fail_if: "error"
""",
            },
        })

        with patch(
            "llm_pytest.tools.create_test._call_claude_code",
            return_value={"output": valid_output},
        ):
            result = await create_test_tool(
                description="Test something",
                project_root=tmp_path,
            )

        assert result["success"] is True
        assert "test_path" in result
        assert Path(result["test_path"]).exists()

    @pytest.mark.anyio
    async def test_creates_plugin_and_test(self, tmp_path: Path):
        """Test creation of both plugin and test files."""
        valid_output = json.dumps({
            "plugin": {
                "filename": "my_plugin.py",
                "code": '''from llm_pytest import LLMPlugin

class MyPlugin(LLMPlugin):
    name = "my"

    async def action(self, x: str) -> dict:
        return {"x": x}
''',
            },
            "test": {
                "filename": "test_my.yaml",
                "code": """test:
  name: "My Test"
steps:
  - tool: my_action
    args: {x: "hello"}
verdict:
  pass_if: "success"
  fail_if: "error"
""",
            },
        })

        with patch(
            "llm_pytest.tools.create_test._call_claude_code",
            return_value={"output": valid_output},
        ):
            result = await create_test_tool(
                description="Test something",
                project_root=tmp_path,
            )

        assert result["success"] is True
        assert result["plugin_path"] is not None
        assert Path(result["plugin_path"]).exists()
        assert Path(result["test_path"]).exists()


class TestAnnotationToStr:
    """Tests for _annotation_to_str helper function."""

    def test_simple_types(self):
        assert _annotation_to_str(str) == "str"
        assert _annotation_to_str(int) == "int"
        assert _annotation_to_str(bool) == "bool"
        assert _annotation_to_str(float) == "float"

    def test_none_type(self):
        assert _annotation_to_str(None) == "None"
        # type(None) returns NoneType
        assert "None" in _annotation_to_str(type(None))

    def test_string_annotation(self):
        assert _annotation_to_str("str") == "str"
        assert _annotation_to_str("CustomType") == "CustomType"

    def test_list_and_dict(self):
        from typing import List, Dict
        result = _annotation_to_str(List[str])
        assert "str" in result
        result = _annotation_to_str(Dict[str, int])
        assert "str" in result

    def test_optional_type(self):
        from typing import Optional
        result = _annotation_to_str(Optional[str])
        assert "str" in result
        assert "None" in result


class TestAtomicWriteRollback:
    """Tests for rollback behavior in _atomic_write_files."""

    @pytest.mark.anyio
    async def test_no_files_created_on_invalid_plugin_filename(self, tmp_path: Path):
        """Ensure no files are created when plugin filename is invalid."""
        parsed = {
            "test": {
                "filename": "test_example.yaml",
                "code": "test:\n  name: X\nsteps: []\nverdict:\n  pass_if: x\n  fail_if: y",
            },
            "plugin": {
                "filename": "../escape.py",  # Invalid
                "code": "print('hello')",
            },
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is False
        # Ensure no files were created
        tests_dir = tmp_path / "tests" / "llm"
        if tests_dir.exists():
            assert not (tests_dir / "test_example.yaml").exists()

    @pytest.mark.anyio
    async def test_rejects_plugin_without_filename(self, tmp_path: Path):
        """Test error when plugin has no filename."""
        parsed = {
            "test": {
                "filename": "test_x.yaml",
                "code": "test:\n  name: X\nsteps: []\nverdict:\n  pass_if: x\n  fail_if: y",
            },
            "plugin": {
                "filename": "",  # Empty filename
                "code": "print('hello')",
            },
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is False
        assert "filename" in result["error"].lower()

    @pytest.mark.anyio
    async def test_rejects_invalid_plugin_extension(self, tmp_path: Path):
        """Test error when plugin doesn't end with .py."""
        parsed = {
            "test": {
                "filename": "test_x.yaml",
                "code": "test:\n  name: X\nsteps: []\nverdict:\n  pass_if: x\n  fail_if: y",
            },
            "plugin": {
                "filename": "plugin.txt",  # Wrong extension
                "code": "print('hello')",
            },
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is False
        assert "Invalid plugin filename" in result["error"] or ".py" in result["error"]

    @pytest.mark.anyio
    async def test_rejects_existing_plugin_file(self, tmp_path: Path):
        """Test error when plugin file already exists."""
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)
        existing = plugins_dir / "existing.py"
        existing.write_text("# existing plugin")

        parsed = {
            "test": {
                "filename": "test_x.yaml",
                "code": "test:\n  name: X\nsteps: []\nverdict:\n  pass_if: x\n  fail_if: y",
            },
            "plugin": {
                "filename": "existing.py",
                "code": 'class P:\n    name = "new"\n',
            },
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is False
        assert "already exists" in result["error"]

    @pytest.mark.anyio
    async def test_rejects_missing_test_filename(self, tmp_path: Path):
        """Test error when test has no filename."""
        parsed = {
            "test": {
                "filename": "",  # Empty
                "code": "test content",
            },
            "plugin": None,
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is False
        assert "filename" in result["error"].lower()

    @pytest.mark.anyio
    async def test_rejects_test_without_yaml_extension(self, tmp_path: Path):
        """Test error when test doesn't end with .yaml."""
        parsed = {
            "test": {
                "filename": "test_example.txt",  # Wrong extension
                "code": "test content",
            },
            "plugin": None,
        }

        result = await _atomic_write_files(parsed, tmp_path, set(), None)

        assert result["success"] is False
        assert "Invalid test filename" in result["error"] or ".yaml" in result["error"]


class TestParseClaudeOutputEdgeCases:
    """Additional edge case tests for _parse_claude_output."""

    def test_parses_result_as_dict(self):
        """Test when result field is already a dict."""
        output = json.dumps({
            "result": {
                "test": {"filename": "test.yaml", "code": "..."},
                "plugin": None,
            }
        })
        result = _parse_claude_output(output)
        assert "test" in result

    def test_handles_empty_output(self):
        """Test handling of empty output."""
        result = _parse_claude_output("")
        assert "error" in result

    def test_handles_non_dict_json(self):
        """Test handling of valid JSON that's not a dict."""
        result = _parse_claude_output('["not", "a", "dict"]')
        assert "error" in result


class TestValidateGeneratedContentEdgeCases:
    """Additional edge case tests for _validate_generated_content."""

    def test_rejects_empty_test_code(self, tmp_path: Path):
        """Test that empty test code is rejected."""
        parsed = {
            "test": {
                "filename": "test.yaml",
                "code": "",  # Empty
            }
        }
        result = _validate_generated_content(parsed, tmp_path)
        assert "error" in result

    def test_accepts_valid_plugin_without_code(self, tmp_path: Path):
        """Test validation when plugin has no code field."""
        parsed = {
            "test": {
                "filename": "test.yaml",
                "code": """test:
  name: Test
steps:
  - tool: x
verdict:
  pass_if: y
  fail_if: z
""",
            },
            "plugin": {
                "filename": "p.py",
                # No code field
            },
        }
        # Should not crash, just validate what's there
        result = _validate_generated_content(parsed, tmp_path)
        # Should pass since empty plugin code doesn't need syntax check
        assert result.get("valid") is True or "error" not in result
