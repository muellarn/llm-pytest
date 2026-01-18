"""Claude Code subprocess runner with automatic MCP server management."""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from jinja2 import Environment, PackageLoader

from .models import TestSpec, Verdict

# Initialize Jinja2 environment
env = Environment(
    loader=PackageLoader("llm_pytest", "templates"),
    autoescape=False,
)

# Global temp config file
_mcp_config_file: Path | None = None


def _find_project_root(yaml_path: Path) -> Path:
    """Find project root by looking for common markers."""
    current = yaml_path.parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        if (current / "setup.py").exists():
            return current
        if (current / ".git").exists():
            return current
        current = current.parent
    return yaml_path.parent


def _create_mcp_config(project_root: Path) -> Path:
    """Create a temporary MCP configuration file.

    This config tells Claude which MCP server to use for the tests.
    The server is started automatically by Claude when it processes the config.

    Args:
        project_root: Project root directory

    Returns:
        Path to the config file
    """
    global _mcp_config_file

    # Reuse existing config if available
    if _mcp_config_file and _mcp_config_file.exists():
        return _mcp_config_file

    config = {
        "mcpServers": {
            "llm_pytest": {
                "command": sys.executable,
                "args": ["-m", "llm_pytest.mcp_server", "--project-root", str(project_root)],
                "cwd": str(project_root),
            }
        }
    }

    # Create temp file that persists for the session
    _mcp_config_file = Path(tempfile.gettempdir()) / "llm_pytest_mcp_config.json"
    _mcp_config_file.write_text(json.dumps(config, indent=2))

    return _mcp_config_file


def _cleanup_mcp_config():
    """Cleanup temp config file on exit."""
    global _mcp_config_file
    if _mcp_config_file and _mcp_config_file.exists():
        try:
            _mcp_config_file.unlink()
        except Exception:
            pass
        _mcp_config_file = None


# Register cleanup on exit
atexit.register(_cleanup_mcp_config)


def run_llm_test(
    spec: TestSpec,
    yaml_path: Path,
    timeout: int | None = None,
    verbose: bool = False,
) -> Verdict:
    """Run a test via Claude Code subprocess.

    The framework automatically:
    1. Finds project root
    2. Discovers plugins in tests/llm/plugins/
    3. Creates MCP config with all tools
    4. Passes config to Claude via --mcp-config

    Args:
        spec: The parsed test specification
        yaml_path: Path to the YAML test file
        timeout: Timeout in seconds (overrides spec.test.timeout)
        verbose: Whether to print verbose output

    Returns:
        Verdict object with test results
    """
    effective_timeout = timeout if timeout else spec.test.timeout
    project_root = _find_project_root(yaml_path)

    # Create MCP config for Claude
    mcp_config = _create_mcp_config(project_root)

    # Render prompt from template
    try:
        template = env.get_template("test_prompt.jinja2")
        prompt = template.render(
            yaml_content=yaml_path.read_text(),
            spec=spec,
        )
    except Exception as e:
        return Verdict(
            verdict="FAIL",
            reason=f"Failed to render prompt template: {e}",
            steps=[],
            issues=[str(e)],
        )

    if verbose:
        print(f"\n[llm-pytest] Running test: {spec.test.name}", flush=True)
        print(f"[llm-pytest] Timeout: {effective_timeout}s", flush=True)
        print(f"[llm-pytest] Project root: {project_root}", flush=True)
        print(f"[llm-pytest] MCP config: {mcp_config}", flush=True)

    # Check if plugins exist
    plugins_dir = project_root / "tests" / "llm" / "plugins"
    if plugins_dir.exists():
        plugins = list(plugins_dir.glob("*.py"))
        plugins = [p for p in plugins if not p.name.startswith("_")]
        if verbose and plugins:
            print(f"[llm-pytest] Found plugins: {[p.stem for p in plugins]}", flush=True)

    if verbose:
        print(f"[llm-pytest] Starting Claude Code...", flush=True)
        print("-" * 60, flush=True)

    # Build Claude command with MCP config
    # Allow all MCP tools from llm_pytest server
    base_cmd = [
        "claude",
        "-p", prompt,
        "--mcp-config", str(mcp_config),
        "--allowedTools", "mcp__llm_pytest__*",  # Allow all llm_pytest MCP tools
    ]

    # Call Claude Code
    try:
        if verbose:
            # Use stream-json for real-time output
            # IMPORTANT: stdin must be closed or from /dev/null, otherwise claude hangs
            process = subprocess.Popen(
                base_cmd + ["--output-format", "stream-json", "--verbose"],
                stdin=subprocess.DEVNULL,  # Critical: close stdin
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=project_root,  # Run from project root so plugins are found
                bufsize=1,  # Line buffered
            )

            final_result = None
            assistant_text = []

            # Read NDJSON lines in real-time
            try:
                for line in process.stdout:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                        event_type = event.get("type", "")

                        if event_type == "system" and event.get("subtype") == "init":
                            print(f"[llm-pytest] Session started", flush=True)

                        elif event_type == "assistant":
                            # Extract text and tool_use from assistant message
                            msg = event.get("message", {})
                            content = msg.get("content", [])
                            for block in content:
                                block_type = block.get("type")
                                if block_type == "text":
                                    text = block.get("text", "")
                                    if text:
                                        # Print a preview of the response
                                        preview = text[:200] + "..." if len(text) > 200 else text
                                        print(f"[claude] {preview}", flush=True)
                                        assistant_text.append(text)
                                elif block_type == "tool_use":
                                    tool_name = block.get("name", "unknown")
                                    tool_input = block.get("input", {})
                                    # Show tool call with truncated input
                                    input_str = json.dumps(tool_input, ensure_ascii=False)
                                    if len(input_str) > 100:
                                        input_str = input_str[:100] + "..."
                                    print(f"[tool] {tool_name}({input_str})", flush=True)

                        elif event_type == "tool_result":
                            # Show tool result status
                            is_error = event.get("is_error", False)
                            content = event.get("content", "")
                            if isinstance(content, str):
                                preview = content[:150] + "..." if len(content) > 150 else content
                            else:
                                preview = str(content)[:150]
                            status = "ERROR" if is_error else "OK"
                            print(f"[tool result] {status}: {preview}", flush=True)

                        elif event_type == "result":
                            final_result = event.get("result", "")
                            duration = event.get("duration_ms", 0) / 1000
                            print(f"[llm-pytest] Completed in {duration:.1f}s", flush=True)

                    except json.JSONDecodeError:
                        # Not JSON, print as-is
                        print(f"[claude] {line}", flush=True)

                returncode = process.wait(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                return Verdict(
                    verdict="FAIL",
                    reason=f"Test timed out after {effective_timeout} seconds",
                    steps=[],
                    issues=[f"Timeout: {effective_timeout}s exceeded"],
                )

            print("-" * 60, flush=True)
            print(f"[llm-pytest] Claude exit code: {returncode}", flush=True)

            # Create result-like object
            class Result:
                pass

            result = Result()
            result.returncode = returncode
            # Use final_result if available, otherwise join assistant text
            result.stdout = final_result if final_result else "\n".join(assistant_text)
            result.stderr = ""
        else:
            # Non-verbose: capture output silently with JSON format
            result = subprocess.run(
                base_cmd + ["--output-format", "json"],
                stdin=subprocess.DEVNULL,  # Critical: close stdin
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=project_root,
            )
    except subprocess.TimeoutExpired:
        return Verdict(
            verdict="FAIL",
            reason=f"Test timed out after {effective_timeout} seconds",
            steps=[],
            issues=[f"Timeout: {effective_timeout}s exceeded"],
        )
    except FileNotFoundError:
        return Verdict(
            verdict="FAIL",
            reason="Claude Code CLI not found. Is 'claude' installed and in PATH?",
            steps=[],
            issues=["claude command not found"],
        )
    except Exception as e:
        return Verdict(
            verdict="FAIL",
            reason=f"Failed to run Claude Code: {e}",
            steps=[],
            issues=[str(e)],
        )

    if verbose:
        print(f"[llm-pytest] Claude exit code: {result.returncode}")
        if result.stderr:
            print(f"[llm-pytest] stderr: {result.stderr[:500]}")

    if result.returncode != 0:
        return Verdict(
            verdict="FAIL",
            reason=f"Claude Code failed with exit code {result.returncode}",
            steps=[],
            issues=[result.stderr or "Unknown error"],
        )

    # Parse JSON output
    try:
        # Claude's JSON output may have the result wrapped
        output = json.loads(result.stdout)

        # Handle different output formats
        if isinstance(output, dict):
            # Check if it's already a verdict
            if "verdict" in output:
                return Verdict.model_validate(output)
            # Check if result is nested under a key
            if "result" in output and isinstance(output["result"], dict):
                return Verdict.model_validate(output["result"])

        return Verdict(
            verdict="UNCLEAR",
            reason=f"Unexpected output format: {type(output)}",
            steps=[],
            issues=["Could not parse verdict from output"],
        )

    except json.JSONDecodeError as e:
        # Try to extract JSON from the output (Claude might include text)
        import re

        json_match = re.search(r"\{[\s\S]*\"verdict\"[\s\S]*\}", result.stdout)
        if json_match:
            try:
                output = json.loads(json_match.group())
                return Verdict.model_validate(output)
            except Exception:
                pass

        return Verdict(
            verdict="UNCLEAR",
            reason=f"Could not parse Claude output as JSON: {e}",
            steps=[],
            issues=[str(e), f"Raw output: {result.stdout[:500]}..."],
        )
    except Exception as e:
        return Verdict(
            verdict="UNCLEAR",
            reason=f"Could not validate verdict: {e}",
            steps=[],
            issues=[str(e)],
        )
