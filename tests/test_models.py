"""Tests for Pydantic models in llm_pytest.models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_pytest.models import (
    Step,
    StepResult,
    TestMeta,
    TestSpec,
    Verdict,
    VerdictSpec,
)


class TestTestMeta:
    """Tests for TestMeta model."""

    def test_minimal_creation(self):
        """TestMeta with only required fields."""
        meta = TestMeta(name="My Test")
        assert meta.name == "My Test"
        assert meta.description == ""
        assert meta.tags == []
        assert meta.timeout == 120

    def test_full_creation(self):
        """TestMeta with all fields."""
        meta = TestMeta(
            name="Full Test",
            description="A complete test",
            tags=["unit", "fast"],
            timeout=60,
        )
        assert meta.name == "Full Test"
        assert meta.description == "A complete test"
        assert meta.tags == ["unit", "fast"]
        assert meta.timeout == 60

    def test_default_timeout(self):
        """Default timeout should be 120 seconds."""
        meta = TestMeta(name="Test")
        assert meta.timeout == 120

    def test_name_required(self):
        """Name field is required."""
        with pytest.raises(ValidationError) as exc_info:
            TestMeta()
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("name",) for e in errors)

    def test_tags_default_factory(self):
        """Tags should use a default factory (independent lists)."""
        meta1 = TestMeta(name="Test 1")
        meta2 = TestMeta(name="Test 2")
        meta1.tags.append("modified")
        assert meta2.tags == []  # Should not be affected


class TestStep:
    """Tests for Step model."""

    def test_minimal_step(self):
        """Step with all defaults."""
        step = Step()
        assert step.name == ""
        assert step.tool == ""
        assert step.args == {}
        assert step.expect == ""
        assert step.analyze == ""
        assert step.save_as == ""
        assert step.repeat == 1
        assert step.retry == 0
        assert step.retry_delay == 1.0
        assert step.timeout is None
        assert step.steps == []

    def test_full_step(self):
        """Step with all fields specified."""
        step = Step(
            name="API Call",
            tool="http_get",
            args={"url": "http://example.com", "headers": {"X-Custom": "value"}},
            expect="Should return 200",
            analyze="Check response body contains expected data",
            save_as="api_response",
            repeat=3,
            retry=2,
            retry_delay=5.0,
            timeout=30,
        )
        assert step.name == "API Call"
        assert step.tool == "http_get"
        assert step.args == {"url": "http://example.com", "headers": {"X-Custom": "value"}}
        assert step.expect == "Should return 200"
        assert step.analyze == "Check response body contains expected data"
        assert step.save_as == "api_response"
        assert step.repeat == 3
        assert step.retry == 2
        assert step.retry_delay == 5.0
        assert step.timeout == 30

    def test_nested_steps(self):
        """Step can contain nested steps."""
        parent = Step(
            name="Parent",
            steps=[
                Step(name="Child 1", tool="tool1"),
                Step(name="Child 2", tool="tool2"),
            ],
        )
        assert len(parent.steps) == 2
        assert parent.steps[0].name == "Child 1"
        assert parent.steps[1].name == "Child 2"

    def test_is_nested_method(self):
        """is_nested() should return True when step has nested steps."""
        flat = Step(name="Flat", tool="something")
        nested = Step(name="Nested", steps=[Step(tool="inner")])

        assert flat.is_nested() is False
        assert nested.is_nested() is True

    def test_retry_defaults(self):
        """Retry should default to 0 (no retry)."""
        step = Step()
        assert step.retry == 0
        assert step.retry_delay == 1.0

    def test_per_step_timeout(self):
        """Per-step timeout should be None by default."""
        step = Step()
        assert step.timeout is None

        step_with_timeout = Step(timeout=30)
        assert step_with_timeout.timeout == 30

    def test_args_default_factory(self):
        """Args should use a default factory (independent dicts)."""
        step1 = Step()
        step2 = Step()
        step1.args["modified"] = True
        assert "modified" not in step2.args


class TestVerdictSpec:
    """Tests for VerdictSpec model."""

    def test_creation(self):
        """VerdictSpec with required fields."""
        spec = VerdictSpec(
            pass_if="All tests pass",
            fail_if="Any test fails",
        )
        assert spec.pass_if == "All tests pass"
        assert spec.fail_if == "Any test fails"

    def test_pass_if_required(self):
        """pass_if field is required."""
        with pytest.raises(ValidationError) as exc_info:
            VerdictSpec(fail_if="Something fails")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("pass_if",) for e in errors)

    def test_fail_if_required(self):
        """fail_if field is required."""
        with pytest.raises(ValidationError) as exc_info:
            VerdictSpec(pass_if="Something passes")
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("fail_if",) for e in errors)


class TestTestSpec:
    """Tests for TestSpec model."""

    def test_minimal_creation(self, minimal_test_yaml):
        """TestSpec from minimal YAML."""
        spec = TestSpec.model_validate(minimal_test_yaml)
        assert spec.test.name == "Minimal Test"
        assert len(spec.steps) == 1
        assert spec.setup == []
        assert spec.teardown == []

    def test_full_creation(self, sample_test_yaml_with_setup_teardown):
        """TestSpec from full YAML with setup/teardown."""
        spec = TestSpec.model_validate(sample_test_yaml_with_setup_teardown)
        assert spec.test.name == "Full Test"
        assert len(spec.setup) == 1
        assert len(spec.steps) == 1
        assert len(spec.teardown) == 1
        assert spec.setup[0].tool == "db.connect"
        assert spec.teardown[0].tool == "db.disconnect"

    def test_test_required(self):
        """test section is required."""
        with pytest.raises(ValidationError):
            TestSpec(
                steps=[Step(tool="something")],
                verdict=VerdictSpec(pass_if="pass", fail_if="fail"),
            )

    def test_steps_required(self):
        """steps section is required."""
        with pytest.raises(ValidationError):
            TestSpec(
                test=TestMeta(name="Test"),
                verdict=VerdictSpec(pass_if="pass", fail_if="fail"),
            )

    def test_verdict_required(self):
        """verdict section is required."""
        with pytest.raises(ValidationError):
            TestSpec(
                test=TestMeta(name="Test"),
                steps=[Step(tool="something")],
            )


class TestStepResult:
    """Tests for StepResult model."""

    def test_pass_result(self):
        """StepResult with pass status."""
        result = StepResult(
            name="Test Step",
            status="pass",
            details="Everything worked",
            tool_output={"data": [1, 2, 3]},
        )
        assert result.name == "Test Step"
        assert result.status == "pass"
        assert result.details == "Everything worked"
        assert result.tool_output == {"data": [1, 2, 3]}

    def test_fail_result(self):
        """StepResult with fail status."""
        result = StepResult(
            name="Failing Step",
            status="fail",
            details="Connection refused",
        )
        assert result.status == "fail"
        assert result.tool_output is None

    def test_skip_result(self):
        """StepResult with skip status."""
        result = StepResult(
            name="Skipped Step",
            status="skip",
        )
        assert result.status == "skip"
        assert result.details == ""

    def test_invalid_status(self):
        """Status must be one of pass, fail, skip."""
        with pytest.raises(ValidationError):
            StepResult(name="Test", status="unknown")

    def test_status_literal_values(self):
        """All valid status values should work."""
        for status in ["pass", "fail", "skip"]:
            result = StepResult(name="Test", status=status)
            assert result.status == status


class TestVerdict:
    """Tests for Verdict model."""

    def test_pass_verdict(self):
        """Verdict with PASS status."""
        verdict = Verdict(
            verdict="PASS",
            reason="All tests passed successfully",
            steps=[
                StepResult(name="Step 1", status="pass"),
                StepResult(name="Step 2", status="pass"),
            ],
        )
        assert verdict.verdict == "PASS"
        assert verdict.reason == "All tests passed successfully"
        assert len(verdict.steps) == 2
        assert verdict.issues == []

    def test_fail_verdict(self):
        """Verdict with FAIL status."""
        verdict = Verdict(
            verdict="FAIL",
            reason="Step 2 failed",
            steps=[
                StepResult(name="Step 1", status="pass"),
                StepResult(name="Step 2", status="fail"),
            ],
            issues=["API returned 500", "Timeout after 30s"],
        )
        assert verdict.verdict == "FAIL"
        assert len(verdict.issues) == 2

    def test_unclear_verdict(self):
        """Verdict with UNCLEAR status."""
        verdict = Verdict(
            verdict="UNCLEAR",
            reason="Unable to determine test outcome",
        )
        assert verdict.verdict == "UNCLEAR"

    def test_invalid_verdict(self):
        """Verdict must be one of PASS, FAIL, UNCLEAR."""
        with pytest.raises(ValidationError):
            Verdict(verdict="MAYBE", reason="Uncertain")

    def test_verdict_literal_values(self):
        """All valid verdict values should work."""
        for v in ["PASS", "FAIL", "UNCLEAR"]:
            verdict = Verdict(verdict=v, reason="Test reason")
            assert verdict.verdict == v

    def test_defaults(self):
        """Verdict should have sensible defaults for optional fields."""
        verdict = Verdict(verdict="PASS", reason="OK")
        assert verdict.steps == []
        assert verdict.issues == []
