"""Shared test fixtures for llm-pytest tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# Configure pytest-asyncio mode
pytest_plugins = ["anyio"]


@pytest.fixture
def sample_test_yaml() -> dict[str, Any]:
    """A valid test YAML structure."""
    return {
        "test": {
            "name": "Sample Test",
            "description": "A test for testing",
            "timeout": 60,
            "tags": ["unit", "sample"],
        },
        "steps": [
            {
                "name": "Step 1",
                "tool": "http_get",
                "args": {"url": "http://example.com"},
                "expect": "Should return 200",
            }
        ],
        "verdict": {
            "pass_if": "All steps pass",
            "fail_if": "Any step fails",
        },
    }


@pytest.fixture
def sample_test_yaml_with_setup_teardown() -> dict[str, Any]:
    """A valid test YAML structure with setup and teardown."""
    return {
        "test": {
            "name": "Full Test",
            "description": "A test with setup and teardown",
            "timeout": 120,
            "tags": ["integration"],
        },
        "setup": [
            {
                "name": "Initialize",
                "tool": "db.connect",
                "args": {"connection_string": "sqlite:///:memory:"},
            }
        ],
        "steps": [
            {
                "name": "Query Data",
                "tool": "db.query",
                "args": {"sql": "SELECT 1"},
                "expect": "Should return result",
                "save_as": "query_result",
            }
        ],
        "teardown": [
            {
                "name": "Cleanup",
                "tool": "db.disconnect",
                "args": {},
            }
        ],
        "verdict": {
            "pass_if": "Query returns expected result",
            "fail_if": "Query fails or returns unexpected result",
        },
    }


@pytest.fixture
def tmp_yaml_file(tmp_path: Path, sample_test_yaml: dict[str, Any]) -> Path:
    """Create a temporary YAML file."""
    filepath = tmp_path / "test_sample.yaml"
    filepath.write_text(yaml.dump(sample_test_yaml))
    return filepath


@pytest.fixture
def minimal_test_yaml() -> dict[str, Any]:
    """Minimal valid test YAML with only required fields."""
    return {
        "test": {
            "name": "Minimal Test",
        },
        "steps": [
            {
                "tool": "noop",
            }
        ],
        "verdict": {
            "pass_if": "Always pass",
            "fail_if": "Never fail",
        },
    }


@pytest.fixture
def step_with_retry_yaml() -> dict[str, Any]:
    """Test YAML with retry configuration."""
    return {
        "test": {
            "name": "Retry Test",
        },
        "steps": [
            {
                "name": "Flaky Step",
                "tool": "http_get",
                "args": {"url": "http://flaky.example.com"},
                "expect": "Should eventually succeed",
                "retry": 3,
                "retry_delay": 2.0,
                "timeout": 10,
            }
        ],
        "verdict": {
            "pass_if": "Request eventually succeeds",
            "fail_if": "All retries exhausted",
        },
    }


@pytest.fixture
def interpolation_context() -> dict[str, Any]:
    """Sample context for variable interpolation tests."""
    return {
        "stored": {
            "auth_token": "secret123",
            "api_key": "key456",
        },
        "created_user": {
            "id": 42,
            "name": "Alice",
            "email": "alice@example.com",
            "address": {
                "city": "New York",
                "country": "USA",
            },
        },
        "simple_value": "hello",
        "numeric_value": 100,
    }
