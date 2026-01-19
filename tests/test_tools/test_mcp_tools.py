"""Tests for MCP built-in tools: validate_test, list_plugins, run_test."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from llm_pytest.models import Verdict


class TestValidateTestTool:
    """Tests for validate_test MCP tool."""

    @pytest.fixture
    def valid_yaml_content(self) -> str:
        return """
test:
  name: "Sample Test"
  description: "A sample test for validation"

steps:
  - name: "Store a value"
    tool: store_value
    args:
      name: "test_key"
      value: 42
    expect: "Value should be stored"

verdict:
  pass_if: |
    - Value was stored successfully
  fail_if: |
    - Storage failed
"""

    @pytest.fixture
    def invalid_yaml_content(self) -> str:
        return """
test:
  name: "Invalid Test"
# Missing steps and verdict
"""

    def test_validates_valid_yaml(self, tmp_path: Path, valid_yaml_content: str):
        """Test that valid YAML passes validation."""
        import yaml

        from llm_pytest.schema import validate_test_yaml

        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_sample.yaml"
        test_file.write_text(valid_yaml_content)

        content = yaml.safe_load(valid_yaml_content)
        spec, errors = validate_test_yaml(content, test_file)

        assert errors == []
        assert spec is not None
        assert spec.test.name == "Sample Test"

    def test_rejects_invalid_yaml(self, tmp_path: Path, invalid_yaml_content: str):
        """Test that invalid YAML fails validation."""
        import yaml

        from llm_pytest.schema import validate_test_yaml

        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_invalid.yaml"
        test_file.write_text(invalid_yaml_content)

        content = yaml.safe_load(invalid_yaml_content)
        spec, errors = validate_test_yaml(content, test_file)

        assert len(errors) > 0
        assert spec is None

    def test_file_not_found(self, tmp_path: Path):
        """Test handling of non-existent file."""
        from llm_pytest.mcp_server import UnifiedMCPServer

        server = UnifiedMCPServer(project_root=tmp_path)
        mcp = server.create_mcp_server()

        # Find the validate_test tool
        validate_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "validate_test":
                validate_tool = tool
                break

        assert validate_tool is not None

        result = asyncio.run(validate_tool.fn(test_path="nonexistent.yaml"))

        assert result["valid"] is False
        assert "File not found" in result["errors"][0]

    def test_extracts_tools_used(self, tmp_path: Path):
        """Test that tools_used is correctly extracted."""
        from llm_pytest.mcp_server import UnifiedMCPServer

        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_tools.yaml"
        test_file.write_text("""
test:
  name: "Multi-tool Test"

steps:
  - name: "Step 1"
    tool: store_value
    args: {name: "a", value: 1}
  - name: "Step 2"
    tool: get_value
    args: {name: "a"}
  - name: "Step 3"
    tool: store_value
    args: {name: "b", value: 2}

verdict:
  pass_if: "All steps complete"
  fail_if: "Any step fails"
""")

        server = UnifiedMCPServer(project_root=tmp_path)
        mcp = server.create_mcp_server()

        validate_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "validate_test":
                validate_tool = tool
                break

        result = asyncio.run(validate_tool.fn(test_path=str(test_file)))

        assert result["valid"] is True
        assert result["step_count"] == 3
        assert set(result["tools_used"]) == {"store_value", "get_value"}

    def test_non_yaml_file_rejected(self, tmp_path: Path):
        """Test that non-yaml files are rejected."""
        from llm_pytest.mcp_server import UnifiedMCPServer

        test_file = tmp_path / "test.txt"
        test_file.write_text("not yaml")

        server = UnifiedMCPServer(project_root=tmp_path)
        mcp = server.create_mcp_server()

        validate_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "validate_test":
                validate_tool = tool
                break

        result = asyncio.run(validate_tool.fn(test_path=str(test_file)))

        assert result["valid"] is False
        assert "Expected .yaml file" in result["errors"][0]


class TestListPluginsTool:
    """Tests for list_plugins MCP tool."""

    def test_lists_builtin_tools(self, tmp_path: Path):
        """Test that built-in tools are listed."""
        from llm_pytest.mcp_server import UnifiedMCPServer

        server = UnifiedMCPServer(project_root=tmp_path)
        mcp = server.create_mcp_server()

        list_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_plugins":
                list_tool = tool
                break

        assert list_tool is not None

        result = asyncio.run(list_tool.fn())

        assert "builtin_tools" in result
        assert "store_value" in result["builtin_tools"]
        assert "get_value" in result["builtin_tools"]
        assert "sleep" in result["builtin_tools"]
        assert "create_test" in result["builtin_tools"]
        assert "validate_test" in result["builtin_tools"]
        assert "list_plugins" in result["builtin_tools"]
        assert "run_test" in result["builtin_tools"]

    def test_lists_plugins(self, tmp_path: Path):
        """Test that discovered plugins are listed."""
        from llm_pytest.mcp_server import UnifiedMCPServer

        # Create a plugin
        plugins_dir = tmp_path / "tests" / "llm" / "plugins"
        plugins_dir.mkdir(parents=True)

        plugin_code = '''
from llm_pytest import LLMPlugin

class SamplePlugin(LLMPlugin):
    name = "sample"

    async def do_action(self, param: str) -> dict:
        """Perform an action."""
        return {"result": param}
'''
        (plugins_dir / "sample_plugin.py").write_text(plugin_code)

        server = UnifiedMCPServer(project_root=tmp_path)
        mcp = server.create_mcp_server()

        list_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_plugins":
                list_tool = tool
                break

        result = asyncio.run(list_tool.fn())

        assert len(result["plugins"]) == 1
        assert result["plugins"][0]["name"] == "sample"
        assert len(result["plugins"][0]["tools"]) == 1

    def test_returns_total_tools_count(self, tmp_path: Path):
        """Test that total_tools count is correct."""
        from llm_pytest.mcp_server import UnifiedMCPServer

        server = UnifiedMCPServer(project_root=tmp_path)
        mcp = server.create_mcp_server()

        list_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_plugins":
                list_tool = tool
                break

        result = asyncio.run(list_tool.fn())

        # Should have at least the built-in tools
        assert result["total_tools"] >= len(result["builtin_tools"])

    def test_no_plugins_directory(self, tmp_path: Path):
        """Test handling when plugins directory doesn't exist."""
        from llm_pytest.mcp_server import UnifiedMCPServer

        # No plugins directory created
        server = UnifiedMCPServer(project_root=tmp_path)
        mcp = server.create_mcp_server()

        list_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "list_plugins":
                list_tool = tool
                break

        result = asyncio.run(list_tool.fn())

        assert result["plugins"] == []
        assert len(result["builtin_tools"]) > 0


class TestRunTestTool:
    """Tests for run_test MCP tool."""

    def test_file_not_found(self, tmp_path: Path):
        """Test handling of non-existent test file."""
        from llm_pytest.mcp_server import UnifiedMCPServer

        server = UnifiedMCPServer(project_root=tmp_path)
        mcp = server.create_mcp_server()

        run_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "run_test":
                run_tool = tool
                break

        assert run_tool is not None

        result = asyncio.run(run_tool.fn(test_path="nonexistent.yaml"))

        assert result["success"] is False
        assert "File not found" in result["error"]

    def test_invalid_yaml_rejected(self, tmp_path: Path):
        """Test that invalid YAML is rejected before running."""
        from llm_pytest.mcp_server import UnifiedMCPServer

        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_invalid.yaml"
        test_file.write_text("""
test:
  name: "Invalid"
# Missing steps and verdict
""")

        server = UnifiedMCPServer(project_root=tmp_path)
        mcp = server.create_mcp_server()

        run_tool = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "run_test":
                run_tool = tool
                break

        result = asyncio.run(run_tool.fn(test_path=str(test_file)))

        assert result["success"] is False
        assert "Validation failed" in result["error"]

    def test_runs_valid_test(self, tmp_path: Path):
        """Test running a valid test (mocked runner)."""
        import llm_pytest.mcp_server as mcp_server_module
        from llm_pytest.mcp_server import UnifiedMCPServer

        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_sample.yaml"
        test_file.write_text("""
test:
  name: "Sample Test"

steps:
  - name: "Store value"
    tool: store_value
    args: {name: "x", value: 1}

verdict:
  pass_if: "Value stored"
  fail_if: "Storage fails"
""")

        # Mock the run_llm_test function BEFORE creating the server
        mock_verdict = Verdict(verdict="PASS", reason="Test passed successfully")
        original_run_llm_test = mcp_server_module.run_llm_test

        async def mock_run_llm_test(*args, **kwargs):
            return mock_verdict

        mcp_server_module.run_llm_test = mock_run_llm_test

        try:
            server = UnifiedMCPServer(project_root=tmp_path)
            mcp = server.create_mcp_server()

            run_tool = None
            for tool in mcp._tool_manager._tools.values():
                if tool.name == "run_test":
                    run_tool = tool
                    break

            result = asyncio.run(run_tool.fn(test_path=str(test_file)))

            assert result["success"] is True
            assert result["verdict"] == "PASS"
            assert result["reason"] == "Test passed successfully"
            assert "duration_seconds" in result
        finally:
            mcp_server_module.run_llm_test = original_run_llm_test

    def test_handles_runner_exception(self, tmp_path: Path):
        """Test handling of runner exceptions."""
        import llm_pytest.mcp_server as mcp_server_module
        from llm_pytest.mcp_server import UnifiedMCPServer

        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_sample.yaml"
        test_file.write_text("""
test:
  name: "Sample Test"

steps:
  - name: "Store value"
    tool: store_value
    args: {name: "x", value: 1}

verdict:
  pass_if: "Value stored"
  fail_if: "Storage fails"
""")

        original_run_llm_test = mcp_server_module.run_llm_test

        async def mock_run_llm_test(*args, **kwargs):
            raise RuntimeError("Claude CLI not found")

        mcp_server_module.run_llm_test = mock_run_llm_test

        try:
            server = UnifiedMCPServer(project_root=tmp_path)
            mcp = server.create_mcp_server()

            run_tool = None
            for tool in mcp._tool_manager._tools.values():
                if tool.name == "run_test":
                    run_tool = tool
                    break

            result = asyncio.run(run_tool.fn(test_path=str(test_file)))

            assert result["success"] is False
            assert "Claude CLI not found" in result["error"]
            assert result["verdict"] is None
        finally:
            mcp_server_module.run_llm_test = original_run_llm_test

    def test_respects_timeout_parameter(self, tmp_path: Path):
        """Test that timeout parameter is passed to runner."""
        import llm_pytest.mcp_server as mcp_server_module
        from llm_pytest.mcp_server import UnifiedMCPServer

        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_sample.yaml"
        test_file.write_text("""
test:
  name: "Sample Test"
  timeout: 60

steps:
  - name: "Store value"
    tool: store_value
    args: {name: "x", value: 1}

verdict:
  pass_if: "Value stored"
  fail_if: "Storage fails"
""")

        original_run_llm_test = mcp_server_module.run_llm_test
        captured_timeout = None

        async def mock_run_llm_test(spec, path, timeout):
            nonlocal captured_timeout
            captured_timeout = timeout
            return Verdict(verdict="PASS", reason="OK")

        mcp_server_module.run_llm_test = mock_run_llm_test

        try:
            server = UnifiedMCPServer(project_root=tmp_path)
            mcp = server.create_mcp_server()

            run_tool = None
            for tool in mcp._tool_manager._tools.values():
                if tool.name == "run_test":
                    run_tool = tool
                    break

            # Call with custom timeout
            asyncio.run(run_tool.fn(test_path=str(test_file), timeout=300))

            # Verify timeout was passed
            assert captured_timeout == 300
        finally:
            mcp_server_module.run_llm_test = original_run_llm_test

    def test_uses_spec_timeout_when_not_overridden(self, tmp_path: Path):
        """Test that spec timeout is used when not overridden."""
        import llm_pytest.mcp_server as mcp_server_module
        from llm_pytest.mcp_server import UnifiedMCPServer

        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_sample.yaml"
        test_file.write_text("""
test:
  name: "Sample Test"
  timeout: 45

steps:
  - name: "Store value"
    tool: store_value
    args: {name: "x", value: 1}

verdict:
  pass_if: "Value stored"
  fail_if: "Storage fails"
""")

        original_run_llm_test = mcp_server_module.run_llm_test
        captured_timeout = None

        async def mock_run_llm_test(spec, path, timeout):
            nonlocal captured_timeout
            captured_timeout = timeout
            return Verdict(verdict="PASS", reason="OK")

        mcp_server_module.run_llm_test = mock_run_llm_test

        try:
            server = UnifiedMCPServer(project_root=tmp_path)
            mcp = server.create_mcp_server()

            run_tool = None
            for tool in mcp._tool_manager._tools.values():
                if tool.name == "run_test":
                    run_tool = tool
                    break

            # Call without timeout override
            asyncio.run(run_tool.fn(test_path=str(test_file)))

            # Verify spec timeout was used
            assert captured_timeout == 45
        finally:
            mcp_server_module.run_llm_test = original_run_llm_test

    def test_returns_fail_verdict(self, tmp_path: Path):
        """Test that FAIL verdict is correctly returned."""
        import llm_pytest.mcp_server as mcp_server_module
        from llm_pytest.mcp_server import UnifiedMCPServer

        tests_dir = tmp_path / "tests" / "llm"
        tests_dir.mkdir(parents=True)
        test_file = tests_dir / "test_sample.yaml"
        test_file.write_text("""
test:
  name: "Failing Test"

steps:
  - name: "Store value"
    tool: store_value
    args: {name: "x", value: 1}

verdict:
  pass_if: "Value stored"
  fail_if: "Storage fails"
""")

        original_run_llm_test = mcp_server_module.run_llm_test

        async def mock_run_llm_test(*args, **kwargs):
            return Verdict(verdict="FAIL", reason="Expected value not found")

        mcp_server_module.run_llm_test = mock_run_llm_test

        try:
            server = UnifiedMCPServer(project_root=tmp_path)
            mcp = server.create_mcp_server()

            run_tool = None
            for tool in mcp._tool_manager._tools.values():
                if tool.name == "run_test":
                    run_tool = tool
                    break

            result = asyncio.run(run_tool.fn(test_path=str(test_file)))

            assert result["success"] is True  # Tool call succeeded
            assert result["verdict"] == "FAIL"  # But test failed
            assert result["reason"] == "Expected value not found"
        finally:
            mcp_server_module.run_llm_test = original_run_llm_test
