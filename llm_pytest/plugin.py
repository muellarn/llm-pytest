"""pytest plugin for LLM-orchestrated tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from .models import TestSpec, Verdict
from .runner import run_llm_test

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.config.argparsing import Parser


def pytest_addoption(parser: Parser) -> None:
    """Add --llm option to pytest."""
    group = parser.getgroup("llm", "LLM-orchestrated testing")
    group.addoption(
        "--llm",
        action="store_true",
        default=False,
        help="Run LLM-orchestrated tests (tests/llm/*.yaml)",
    )
    group.addoption(
        "--llm-verbose",
        action="store_true",
        default=False,
        help="Show detailed LLM output during test execution",
    )
    group.addoption(
        "--llm-timeout",
        type=int,
        default=None,
        help="Override default timeout for LLM tests (seconds)",
    )


def pytest_collect_file(parent: pytest.Collector, file_path: Path) -> LLMTestFile | None:
    """Collect YAML files from tests/llm/ directory."""
    if file_path.suffix == ".yaml" and "llm" in file_path.parts:
        if parent.config.getoption("--llm"):
            return LLMTestFile.from_parent(parent, path=file_path)
    return None


def pytest_configure(config: Config) -> None:
    """Register custom markers and configure output capture."""
    config.addinivalue_line(
        "markers",
        "llm: mark test as LLM-orchestrated (requires --llm flag)",
    )




class LLMTestFile(pytest.File):
    """Represents a YAML test file."""

    def collect(self):
        """Collect test items from YAML file."""
        try:
            content = yaml.safe_load(self.path.read_text())
            spec = TestSpec.model_validate(content)
            yield LLMTestItem.from_parent(
                self,
                name=spec.test.name,
                spec=spec,
            )
        except yaml.YAMLError as e:
            raise pytest.CollectError(f"Failed to parse YAML: {e}") from e
        except Exception as e:
            raise pytest.CollectError(f"Failed to validate test spec: {e}") from e


class LLMTestItem(pytest.Item):
    """A single LLM test."""

    def __init__(self, name: str, parent: pytest.Collector, spec: TestSpec) -> None:
        super().__init__(name, parent)
        self.spec = spec
        self.add_marker(pytest.mark.llm)

        # Add tag-based markers
        for tag in spec.test.tags:
            self.add_marker(pytest.mark.skip(reason=f"tag:{tag}") if False else getattr(pytest.mark, tag, lambda: None)())

    def runtest(self) -> None:
        """Execute test via Claude Code subprocess."""
        # Get timeout override if specified
        timeout_override = self.config.getoption("--llm-timeout")
        verbose = self.config.getoption("--llm-verbose")

        timeout = timeout_override if timeout_override else self.spec.test.timeout

        # Suspend capture if verbose mode
        capman = None
        if verbose:
            capman = self.config.pluginmanager.getplugin("capturemanager")
            if capman:
                capman.suspend_global_capture(in_=True)

        try:
            verdict = run_llm_test(
                self.spec,
                self.path,
                timeout=timeout,
                verbose=verbose,
            )
        finally:
            # Resume capture
            if capman:
                capman.resume_global_capture()

        if verdict.verdict == "FAIL":
            raise LLMTestFailed(verdict)
        elif verdict.verdict == "UNCLEAR":
            pytest.skip(f"Unclear: {verdict.reason}")

    def repr_failure(self, excinfo: pytest.ExceptionInfo) -> str:
        """Format failure message."""
        if isinstance(excinfo.value, LLMTestFailed):
            v = excinfo.value.verdict
            lines = [
                f"LLM Test Failed: {v.reason}",
                "",
            ]

            if v.steps:
                lines.append("Steps:")
                for step in v.steps:
                    status_icon = "✓" if step.status == "pass" else "✗" if step.status == "fail" else "○"
                    lines.append(f"  {status_icon} {step.name}: {step.details}")
                lines.append("")

            if v.issues:
                lines.append("Issues:")
                for issue in v.issues:
                    lines.append(f"  - {issue}")

            return "\n".join(lines)
        return str(excinfo.value)

    def reportinfo(self) -> tuple[Path, int | None, str]:
        """Report test info."""
        return self.path, None, f"llm: {self.name}"


class LLMTestFailed(Exception):
    """Exception for failed LLM tests."""

    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        super().__init__(verdict.reason)
