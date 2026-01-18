"""Pydantic models for test specs and verdicts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TestMeta(BaseModel):
    """Metadata about a test."""

    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    timeout: int = 120


class Step(BaseModel):
    """A single test step.

    Attributes:
        name: Human-readable name for the step.
        tool: The tool to invoke (e.g., "plugin.method").
        args: Arguments to pass to the tool.
        expect: Expected outcome description for LLM analysis.
        analyze: Detailed analysis instructions for the LLM.
        save_as: Variable name to save the result for later steps.
        repeat: Number of times to repeat this step.
        retry: Number of retry attempts if the step fails.
        retry_delay: Wait time in seconds between retry attempts.
        timeout: Optional per-step timeout in seconds. If None, uses the
            test-level timeout from TestMeta.timeout.
        steps: Nested steps for composite operations.

    Retry behavior:
        retry: Number of retry attempts if the step fails.
            - retry=0 means no retries (fail immediately on first error)
            - retry=3 means up to 3 additional attempts after the first failure
              (so 4 total attempts maximum)
        retry_delay: Wait time in seconds between retry attempts.
            Default is 1.0 second. Use higher values for rate-limited APIs
            or services that need time to recover.

    Timeout behavior:
        timeout: Per-step timeout in seconds.
            - timeout=None means use the test-level timeout (TestMeta.timeout)
            - timeout=30 means this specific step will timeout after 30 seconds
            Useful for steps that are known to be slow (e.g., browser startup)
            or need stricter limits (e.g., quick API calls).

    Example YAML usage:
        - name: "Flaky API call"
          tool: http_get
          args: {url: "http://flaky-server/data"}
          expect: "Should eventually succeed"
          retry: 3
          retry_delay: 2.0
          timeout: 10  # Fail fast if server doesn't respond in 10s
    """

    name: str = ""
    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    expect: str = ""
    analyze: str = ""
    save_as: str = ""
    repeat: int = 1
    retry: int = 0  # Number of retry attempts (0 = no retry, fail immediately)
    retry_delay: float = 1.0  # Delay in seconds between retry attempts
    timeout: int | None = None  # Per-step timeout in seconds (None = use test-level)
    steps: list[Step] = Field(default_factory=list)

    def is_nested(self) -> bool:
        """Check if this step contains nested steps."""
        return len(self.steps) > 0


class VerdictSpec(BaseModel):
    """Specification for pass/fail criteria."""

    pass_if: str
    fail_if: str


class TestSpec(BaseModel):
    """Complete test specification from YAML."""

    test: TestMeta
    setup: list[Step] = Field(default_factory=list)
    steps: list[Step]
    teardown: list[Step] = Field(default_factory=list)
    verdict: VerdictSpec


class StepResult(BaseModel):
    """Result of a single step execution."""

    name: str
    status: Literal["pass", "fail", "skip"]
    details: str = ""
    tool_output: Any = None


class Verdict(BaseModel):
    """Final test verdict from LLM."""

    verdict: Literal["PASS", "FAIL", "UNCLEAR"]
    reason: str
    steps: list[StepResult] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
