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
    """A single test step."""

    name: str = ""
    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    expect: str = ""
    analyze: str = ""
    save_as: str = ""
    repeat: int = 1
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
