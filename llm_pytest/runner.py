"""Claude Code subprocess runner with automatic MCP server management."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, PackageLoader

from .formatter import OutputFormatter
from .logging import (
    configure_logging,
    logger,
)
from .models import TestSpec, Verdict

# Initialize Jinja2 environment
env = Environment(
    loader=PackageLoader("llm_pytest", "templates"),
    autoescape=False,
)


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


@dataclass
class RunnerContext:
    """Thread-safe context for a single test run.

    Each test gets its own MCP config file, ensuring thread safety
    when running tests in parallel (e.g., with pytest-xdist).
    """

    project_root: Path
    mcp_config_path: Path = field(default=None)
    _cleanup_on_exit: bool = True

    def __post_init__(self):
        if self.mcp_config_path is None:
            # Create unique temp file per test
            unique_id = uuid.uuid4().hex[:8]
            self.mcp_config_path = Path(tempfile.gettempdir()) / f"llm_pytest_{unique_id}.json"

    @classmethod
    def create(cls, yaml_path: Path) -> "RunnerContext":
        """Create a new context for a test run."""
        project_root = _find_project_root(yaml_path)
        ctx = cls(project_root=project_root)
        ctx._write_mcp_config()
        return ctx

    def _write_mcp_config(self) -> None:
        """Write the MCP configuration file."""
        config = {
            "mcpServers": {
                "llm_pytest": {
                    "command": sys.executable,
                    "args": ["-m", "llm_pytest.mcp_server", "--project-root", str(self.project_root)],
                    "cwd": str(self.project_root),
                }
            }
        }
        self.mcp_config_path.write_text(json.dumps(config, indent=2))

    def cleanup(self) -> None:
        """Remove the temp config file."""
        if self._cleanup_on_exit and self.mcp_config_path and self.mcp_config_path.exists():
            try:
                self.mcp_config_path.unlink()
            except Exception:
                pass

    def __enter__(self) -> "RunnerContext":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()


def run_llm_test(
    spec: TestSpec,
    yaml_path: Path,
    timeout: int | None = None,
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

    Returns:
        Verdict object with test results

    Warning:
        **Claude Code CLI stdin behavior**: The Claude Code CLI will hang
        indefinitely if stdin is not explicitly closed or redirected from
        /dev/null. This is a known behavior of the CLI when run as a
        subprocess. This function handles this automatically by using
        ``stdin=subprocess.DEVNULL``, but if you're implementing a custom
        LLM client, you must ensure stdin is properly closed.

        See: https://github.com/anthropics/claude-code/issues/1292
    """
    effective_timeout = timeout if timeout else spec.test.timeout

    # Render prompt from template (can fail before context creation)
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

    # Configure logging
    configure_logging(verbose=True)

    # Use RunnerContext for thread-safe MCP config management
    with RunnerContext.create(yaml_path) as ctx:
        logger.info("Running test: %s", spec.test.name)
        logger.info("Timeout: %ss", effective_timeout)
        logger.info("Project root: %s", ctx.project_root)
        logger.info("MCP config: %s", ctx.mcp_config_path)

        # Check if plugins exist
        plugins_dir = ctx.project_root / "tests" / "llm" / "plugins"
        if plugins_dir.exists():
            plugins = list(plugins_dir.glob("*.py"))
            plugins = [p for p in plugins if not p.name.startswith("_")]
            if plugins:
                logger.info("Found plugins: %s", [p.stem for p in plugins])

        logger.info("Starting Claude Code...")
        logger.info("-" * 60)

        # Build Claude command with MCP config
        # Allow all MCP tools from llm_pytest server
        base_cmd = [
            "claude",
            "-p", prompt,
            "--mcp-config", str(ctx.mcp_config_path),
            "--allowedTools", "mcp__llm_pytest__*",  # Allow all llm_pytest MCP tools
        ]

        # Call Claude Code with stream-json for real-time output
        #
        # CRITICAL: Claude Code CLI stdin behavior
        # =========================================
        # The Claude Code CLI hangs indefinitely if stdin is not closed.
        # This is because the CLI waits for potential user input even when
        # running non-interactively. Always use stdin=subprocess.DEVNULL
        # or explicitly close stdin after process creation.
        #
        # Symptoms of this bug:
        # - Test hangs forever with no output
        # - Process doesn't respond to timeout
        # - Works fine when run manually in terminal
        #
        # See: https://github.com/anthropics/claude-code/issues/1292
        try:
            process = subprocess.Popen(
                base_cmd + ["--output-format", "stream-json", "--verbose"],
                stdin=subprocess.DEVNULL,  # CRITICAL: prevents CLI hang
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=ctx.project_root,  # Run from project root so plugins are found
                bufsize=1,  # Line buffered
            )

            final_result = None
            assistant_text = []
            formatter = OutputFormatter()

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
                            logger.info("Session started")

                        elif event_type == "assistant":
                            # Extract text and tool_use from assistant message
                            msg = event.get("message", {})
                            content = msg.get("content", [])
                            for block in content:
                                block_type = block.get("type")
                                if block_type == "text":
                                    text = block.get("text", "")
                                    if text:
                                        # Log Claude's text with formatter
                                        formatted = formatter.claude_text(text)
                                        if formatted:
                                            print(formatted, flush=True)
                                        assistant_text.append(text)
                                elif block_type == "tool_use":
                                    tool_name = block.get("name", "unknown")
                                    tool_input = block.get("input", {})
                                    # Buffer tool call - will be printed with result
                                    formatter.tool_call(tool_name, tool_input)

                        elif event_type == "user":
                            # Tool results come in "user" events with tool_use_result
                            tool_result_content = event.get("tool_use_result", "")
                            if tool_result_content:
                                # Normalize to string for error check
                                content_str = (
                                    tool_result_content
                                    if isinstance(tool_result_content, str)
                                    else json.dumps(tool_result_content)
                                )
                                is_error = "error" in content_str.lower()
                                line_out = formatter.tool_result(content_str, is_error)
                                print(line_out, flush=True)

                        elif event_type == "result":
                            final_result = event.get("result", "")
                            duration = event.get("duration_ms", 0) / 1000
                            logger.info("Completed in %.1fs", duration)

                            # Display verdict from final result
                            if final_result:
                                try:
                                    verdict_data = json.loads(final_result)
                                    if isinstance(verdict_data, dict) and "verdict" in verdict_data:
                                        v = verdict_data.get("verdict", "UNCLEAR")
                                        r = verdict_data.get("reason", "")
                                        for vline in formatter.verdict(v, r):
                                            print(vline, flush=True)
                                except (json.JSONDecodeError, TypeError):
                                    # Try to extract JSON from markdown code block
                                    json_match = re.search(
                                        r'```json\s*(\{[\s\S]*?"verdict"[\s\S]*?\})\s*```',
                                        final_result
                                    )
                                    if json_match:
                                        try:
                                            verdict_data = json.loads(json_match.group(1))
                                            v = verdict_data.get("verdict", "UNCLEAR")
                                            r = verdict_data.get("reason", "")
                                            for vline in formatter.verdict(v, r):
                                                print(vline, flush=True)
                                        except (json.JSONDecodeError, TypeError):
                                            pass

                    except json.JSONDecodeError:
                        # Not JSON, print as-is
                        print(f"[raw] {line}", flush=True)

                returncode = process.wait(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                return Verdict(
                    verdict="FAIL",
                    reason=f"Test timed out after {effective_timeout} seconds",
                    steps=[],
                    issues=[f"Timeout: {effective_timeout}s exceeded"],
                )

            logger.info("-" * 60)
            logger.info("Claude exit code: %s", returncode)

            # Create result-like object
            class Result:
                pass

            result = Result()
            result.returncode = returncode
            # Use final_result if available, otherwise join assistant text
            result.stdout = final_result if final_result else "\n".join(assistant_text)
            result.stderr = ""
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

        if result.stderr:
            logger.warning("stderr: %s", result.stderr[:500])

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
