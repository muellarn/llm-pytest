"""Output formatter for llm-pytest verbose mode.

This module provides structured, readable output for LLM test execution.
Key features:
- Tool calls matched with their results (via queue)
- Compact, informative result summaries
- Clear verdict display
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallBuffer:
    """Buffer for pending tool calls awaiting results."""

    name: str
    args: dict
    args_short: str


@dataclass
class OutputFormatter:
    """Formats llm-pytest output with structure and compaction.

    Usage:
        formatter = OutputFormatter()

        # When tool_use event arrives:
        formatter.tool_call(tool_name, tool_input)

        # When tool_result event arrives:
        line = formatter.tool_result(content, is_error)
        print(line)

        # For Claude's text output:
        line = formatter.claude_text(text)
        print(line)

        # At the end:
        for line in formatter.verdict(verdict, reason):
            print(line)
    """

    pending_calls: list[ToolCallBuffer] = field(default_factory=list)

    def tool_call(self, name: str, args: dict) -> None:
        """Record tool call, wait for result before printing.

        Args:
            name: Tool name (e.g., 'mcp__llm_pytest__zoom_in')
            args: Tool arguments dictionary
        """
        args_str = json.dumps(args, ensure_ascii=False)
        short = args_str[:80] + "..." if len(args_str) > 80 else args_str
        self.pending_calls.append(ToolCallBuffer(name, args, short))

    def tool_result(self, content: Any, is_error: bool) -> str:
        """Match result with pending call, return formatted line.

        Args:
            content: Tool result content (string or dict)
            is_error: Whether the tool returned an error

        Returns:
            Formatted line combining call and result
        """
        if not self.pending_calls:
            # Orphan result (shouldn't happen normally)
            return f"[orphan result] {self._compact(content)}"

        call = self.pending_calls.pop(0)
        status = "✗" if is_error else "✓"
        compact_result = self._compact_result(call.name, content)

        # Strip mcp__llm_pytest__ prefix for cleaner output
        display_name = call.name
        if display_name.startswith("mcp__llm_pytest__"):
            display_name = display_name[17:]

        return f"  {status} {display_name}({call.args_short}) → {compact_result}"

    def _compact(self, content: Any, max_len: int = 100) -> str:
        """Generic compaction for any content."""
        if isinstance(content, str):
            if len(content) > max_len:
                return content[:max_len] + "..."
            return content
        return str(content)[:max_len]

    def _compact_result(self, tool_name: str, content: Any) -> str:
        """Extract key info from tool result based on known patterns.

        Args:
            tool_name: Name of the tool (for context-specific formatting)
            content: Tool result content

        Returns:
            Compact, informative summary of the result
        """
        # Parse content if string
        if isinstance(content, str):
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Plain text result
                return content[:100] + "..." if len(content) > 100 else content
        else:
            data = content

        if not isinstance(data, dict):
            return str(data)[:100]

        # Build compact summary from known patterns
        parts = []

        # Status field
        if "status" in data:
            parts.append(data["status"])

        # Duration/range changes (before/after pattern)
        if "before" in data and "after" in data:
            before = data["before"]
            after = data["after"]
            if isinstance(before, dict) and isinstance(after, dict):
                # Visible duration days
                if "visible_duration_days" in before:
                    b_days = before.get("visible_duration_days", 0)
                    a_days = after.get("visible_duration_days", 0)
                    parts.append(f"{b_days:.0f}d→{a_days:.0f}d")

        # Resolution changes
        if data.get("resolution_changed"):
            old = data.get("old_resolution", "?")
            new = data.get("new_resolution", "?")
            parts.append(f"resolution: {old}→{new}")

        # Symmetry/drift check
        if "symmetry_check" in data:
            sym = data["symmetry_check"]
            drift = sym.get("center_drift_percent", 0)
            parts.append(f"drift: {drift:.2f}%")

        # Validation results
        if "valid" in data:
            if data["valid"]:
                parts.append("valid")
            else:
                issues = data.get("issues", [])
                parts.append(f"invalid({len(issues)} issues)")

        # Cache info
        if "cache" in data and isinstance(data["cache"], dict):
            cache = data["cache"]
            if "entries" in cache:
                parts.append(f"cache: {cache['entries']} entries")

        # Range info
        if "visible_range" in data:
            vr = data["visible_range"]
            if isinstance(vr, dict):
                start = vr.get("start", "")[:10] if vr.get("start") else ""
                end = vr.get("end", "")[:10] if vr.get("end") else ""
                if start and end:
                    parts.append(f"range: {start}..{end}")

        if parts:
            return ", ".join(parts)

        # Fallback: show first few keys
        keys = list(data.keys())[:3]
        preview = {k: data[k] for k in keys}
        result = str(preview)
        return result[:100] + "..." if len(result) > 100 else result

    def claude_text(self, text: str, max_len: int = 500) -> str | None:
        """Format Claude's analysis text.

        Args:
            text: Claude's text output
            max_len: Maximum length before truncation

        Returns:
            Formatted text line, or None if text should be skipped
        """
        stripped = text.strip()

        # Skip JSON code blocks - verdict is displayed separately
        if stripped.startswith("```json"):
            return None

        # Skip empty text
        if not stripped:
            return None

        # Get first meaningful line or truncate
        lines = stripped.split("\n")
        first_line = lines[0] if lines else ""

        # If first line is very short, include more
        if len(first_line) < 50 and len(lines) > 1:
            first_line = " ".join(lines[:3])

        if len(first_line) > max_len:
            first_line = first_line[:max_len] + "..."

        return f"[claude] {first_line}"

    def verdict(self, verdict_str: str, reason: str) -> list[str]:
        """Format final verdict.

        Args:
            verdict_str: "PASS", "FAIL", or "UNCLEAR"
            reason: Explanation of the verdict

        Returns:
            List of lines to print
        """
        icon = "✅" if verdict_str == "PASS" else "❌" if verdict_str == "FAIL" else "❓"

        lines = [
            "",
            "=" * 60,
            f"  {icon} VERDICT: {verdict_str}",
            "=" * 60,
            "",
            reason,
            "",
        ]
        return lines
