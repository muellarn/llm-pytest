"""Claude Code CLI provider.

This provider executes prompts via the Claude Code CLI as a subprocess.

IMPORTANT: Claude Code CLI stdin behavior
=========================================
The Claude Code CLI hangs indefinitely if stdin is not closed.
Always use stdin=subprocess.DEVNULL when spawning the process.
See: https://github.com/anthropics/claude-code/issues/1292
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import AsyncIterator

from ..models import Verdict
from .base import LLMClient, StreamEvent
from .registry import register_provider


@register_provider("claude_code")
class ClaudeCodeClient(LLMClient):
    """Claude Code CLI as an LLM provider.

    This provider wraps the Claude Code CLI, executing prompts as subprocesses.
    It supports both synchronous (blocking) and streaming execution modes.

    CRITICAL: stdin handling
    ------------------------
    The Claude Code CLI will hang indefinitely if stdin is not explicitly
    closed or redirected from /dev/null. This implementation uses
    stdin=subprocess.DEVNULL to prevent this issue.

    See: https://github.com/anthropics/claude-code/issues/1292
    """

    def __init__(self, mcp_config_path: Path, cwd: Path):
        """Initialize the Claude Code client.

        Args:
            mcp_config_path: Path to the MCP configuration file
            cwd: Working directory for the subprocess
        """
        self.mcp_config_path = mcp_config_path
        self.cwd = cwd

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "claude_code"

    def _build_command(self, prompt: str, stream: bool) -> list[str]:
        """Build the Claude CLI command.

        Args:
            prompt: The prompt to send to Claude
            stream: Whether to use streaming output format

        Returns:
            List of command arguments
        """
        cmd = [
            "claude",
            "-p",
            prompt,
            "--mcp-config",
            str(self.mcp_config_path),
            "--allowedTools",
            "mcp__llm_pytest__*",
            "--output-format",
            "stream-json" if stream else "json",
        ]
        if stream:
            cmd.append("--verbose")
        return cmd

    async def execute(
        self,
        prompt: str,
        *,
        timeout: int = 120,
        stream: bool = False,
    ) -> str | AsyncIterator[StreamEvent]:
        """Execute prompt via Claude Code CLI.

        Args:
            prompt: The prompt to execute
            timeout: Timeout in seconds
            stream: If True, return an async iterator of StreamEvents

        Returns:
            If stream=False: The final result as a string
            If stream=True: An async iterator yielding StreamEvents

        Raises:
            TimeoutError: If execution exceeds the timeout
            RuntimeError: If Claude Code CLI fails
            FileNotFoundError: If Claude CLI is not installed
        """
        cmd = self._build_command(prompt, stream)

        if stream:
            return self._execute_streaming(cmd, timeout)
        else:
            return await self._execute_sync(cmd, timeout)

    async def _execute_sync(self, cmd: list[str], timeout: int) -> str:
        """Execute and return final result.

        Args:
            cmd: Command to execute
            timeout: Timeout in seconds

        Returns:
            The stdout output from the command

        Raises:
            TimeoutError: If execution exceeds the timeout
            RuntimeError: If the command returns non-zero exit code
        """
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    stdin=subprocess.DEVNULL,  # CRITICAL: prevents CLI hang
                    capture_output=True,
                    text=True,
                    cwd=self.cwd,
                ),
                timeout=timeout,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Claude Code failed with exit code {result.returncode}: "
                    f"{result.stderr}"
                )

            return result.stdout

        except asyncio.TimeoutError:
            raise TimeoutError(f"Claude Code timed out after {timeout}s")

    async def _execute_streaming(
        self, cmd: list[str], timeout: int
    ) -> AsyncIterator[StreamEvent]:
        """Execute and yield streaming events.

        Args:
            cmd: Command to execute
            timeout: Timeout in seconds

        Yields:
            StreamEvent objects parsed from Claude's NDJSON output

        Raises:
            TimeoutError: If execution exceeds the timeout
        """
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=subprocess.DEVNULL,  # CRITICAL: prevents CLI hang
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
        )

        try:
            async for line in process.stdout:
                line = line.decode().strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    yield self._parse_stream_event(event)
                except json.JSONDecodeError:
                    yield StreamEvent(type="text", data={"text": line})

            await asyncio.wait_for(process.wait(), timeout=timeout)

        except asyncio.TimeoutError:
            process.kill()
            raise TimeoutError(f"Claude Code timed out after {timeout}s")

    def _parse_stream_event(self, event: dict) -> StreamEvent:
        """Parse Claude's NDJSON event into StreamEvent.

        Args:
            event: Raw JSON event from Claude's stream output

        Returns:
            Parsed StreamEvent object
        """
        event_type = event.get("type", "")

        if event_type == "system" and event.get("subtype") == "init":
            return StreamEvent(type="init", data={})

        elif event_type == "assistant":
            msg = event.get("message", {})
            content = msg.get("content", [])
            for block in content:
                if block.get("type") == "text":
                    return StreamEvent(
                        type="text", data={"text": block.get("text", "")}
                    )
                elif block.get("type") == "tool_use":
                    return StreamEvent(
                        type="tool_call",
                        data={
                            "name": block.get("name"),
                            "input": block.get("input", {}),
                        },
                    )
            return StreamEvent(type="text", data={})

        elif event_type == "tool_result":
            return StreamEvent(
                type="tool_result",
                data={
                    "is_error": event.get("is_error", False),
                    "content": event.get("content", ""),
                },
            )

        elif event_type == "result":
            return StreamEvent(
                type="done",
                data={
                    "result": event.get("result", ""),
                    "duration_ms": event.get("duration_ms", 0),
                },
            )

        return StreamEvent(type="unknown", data=event)

    def parse_verdict(self, output: str) -> Verdict:
        """Parse Claude's output into a Verdict.

        This method handles various output formats from Claude:
        - Direct verdict JSON
        - Nested result with verdict
        - Text with embedded JSON

        Args:
            output: Raw output from Claude Code CLI

        Returns:
            Parsed Verdict object
        """
        try:
            data = json.loads(output)

            if isinstance(data, dict):
                # Check if it's already a verdict
                if "verdict" in data:
                    return Verdict.model_validate(data)
                # Check if result is nested under a key
                if "result" in data and isinstance(data["result"], dict):
                    return Verdict.model_validate(data["result"])

            return Verdict(
                verdict="UNCLEAR",
                reason=f"Unexpected output format: {type(data)}",
                steps=[],
                issues=["Could not parse verdict from output"],
            )

        except json.JSONDecodeError as e:
            # Try regex extraction for embedded JSON
            json_match = re.search(r'\{[\s\S]*"verdict"[\s\S]*\}', output)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                    return Verdict.model_validate(data)
                except Exception:
                    pass

            return Verdict(
                verdict="UNCLEAR",
                reason=f"Could not parse output as JSON: {e}",
                steps=[],
                issues=[str(e), f"Raw output: {output[:500]}..."],
            )
