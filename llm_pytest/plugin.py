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
    """Add LLM test options to pytest."""
    group = parser.getgroup("llm", "LLM-orchestrated testing")
    group.addoption(
        "--llm-timeout",
        type=int,
        default=None,
        help="Override default timeout for LLM tests (seconds)",
    )


def _is_llm_test_file(file_path: Path) -> bool:
    """Check if a YAML file is an llm-pytest test by validating its structure.

    An llm-pytest test file must have:
    - 'test' key with 'name' subkey
    - 'steps' key (list)
    - 'verdict' key with 'pass_if' and 'fail_if' subkeys
    """
    if file_path.suffix != ".yaml":
        return False

    try:
        content = yaml.safe_load(file_path.read_text())
        if not isinstance(content, dict):
            return False

        # Check required top-level keys
        if "test" not in content or "steps" not in content or "verdict" not in content:
            return False

        # Check 'test' has 'name'
        test = content.get("test", {})
        if not isinstance(test, dict) or "name" not in test:
            return False

        # Check 'verdict' has required keys
        verdict = content.get("verdict", {})
        if not isinstance(verdict, dict):
            return False
        if "pass_if" not in verdict or "fail_if" not in verdict:
            return False

        return True
    except Exception:
        return False


def pytest_collect_file(parent: pytest.Collector, file_path: Path) -> LLMTestFile | None:
    """Collect YAML files that match llm-pytest test format."""
    if _is_llm_test_file(file_path):
        return LLMTestFile.from_parent(parent, path=file_path)
    return None


def pytest_configure(config: Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "llm: mark test as LLM-orchestrated",
    )
    # Register common tags as markers to prevent warnings
    # These are dynamically registered from YAML test files
    common_tags = [
        "zoom",
        "cache",
        "dataloader",
        "no-browser",
        "resolution",
        "symmetry",
        "validation",
        "data",
        "chart",
    ]
    for tag in common_tags:
        config.addinivalue_line("markers", f"{tag}: LLM test tag")




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
        # Store tags for filtering but don't add as pytest markers
        # to avoid warnings for unregistered markers
        self._tags = spec.test.tags

    def runtest(self) -> None:
        """Execute test via Claude Code subprocess."""
        # Get timeout override if specified
        timeout_override = self.config.getoption("--llm-timeout")

        timeout = timeout_override if timeout_override else self.spec.test.timeout

        # Always suspend capture for real-time output
        capman = self.config.pluginmanager.getplugin("capturemanager")
        if capman:
            capman.suspend_global_capture(in_=True)

        try:
            verdict = run_llm_test(
                self.spec,
                self.path,
                timeout=timeout,
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
