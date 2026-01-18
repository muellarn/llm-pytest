# API Reference

This document provides a comprehensive reference for the llm-pytest API.

## Models

All models are Pydantic-based and defined in `llm_pytest/models.py`.

### TestSpec

The root model for a complete test definition. Parsed from YAML test files.

```python
class TestSpec(BaseModel):
    test: TestMeta          # Required: Test metadata
    setup: list[Step]       # Optional: Setup steps (run before main steps)
    steps: list[Step]       # Required: Main test steps
    teardown: list[Step]    # Optional: Teardown steps (always run)
    verdict: VerdictSpec    # Required: Pass/fail criteria
```

**Example YAML:**
```yaml
test:
  name: "API Health Check"
  description: "Verify the API is responding"
  timeout: 30

setup:
  - tool: server_start
    args: {port: 8080}

steps:
  - name: "Check health"
    tool: http_get
    args: {url: "http://localhost:8080/health"}
    expect: "Status should be 200"

teardown:
  - tool: server_stop

verdict:
  pass_if: "Health endpoint returns 200"
  fail_if: "Health endpoint is unreachable"
```

### TestMeta

Metadata about a test.

```python
class TestMeta(BaseModel):
    name: str               # Required: Test name (shown in pytest output)
    description: str = ""   # Optional: Detailed description
    tags: list[str] = []    # Optional: Tags for filtering/marking
    timeout: int = 120      # Timeout in seconds (default: 2 minutes)
```

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | Required | Human-readable test name |
| `description` | `str` | `""` | Detailed description of what the test verifies |
| `tags` | `list[str]` | `[]` | Tags for categorization (e.g., `["smoke", "api"]`) |
| `timeout` | `int` | `120` | Maximum execution time in seconds |

### Step

Represents a single test step.

```python
class Step(BaseModel):
    name: str = ""                    # Step description
    tool: str = ""                    # MCP tool to call
    args: dict[str, Any] = {}         # Arguments for the tool
    expect: str = ""                  # Expected outcome (for LLM)
    analyze: str = ""                 # Analysis instructions (for LLM)
    save_as: str = ""                 # Save result under this name
    repeat: int = 1                   # Repeat count
    steps: list[Step] = []            # Nested steps (for repeat)
```

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `""` | Human-readable step description |
| `tool` | `str` | `""` | MCP tool name (e.g., `http_get`, `chart_test_zoom_in`) |
| `args` | `dict` | `{}` | Arguments passed to the tool |
| `expect` | `str` | `""` | Natural language expectation for LLM |
| `analyze` | `str` | `""` | Detailed analysis instructions for LLM |
| `save_as` | `str` | `""` | Variable name to store result for later comparison |
| `repeat` | `int` | `1` | Number of times to repeat this step |
| `steps` | `list[Step]` | `[]` | Nested steps (used with `repeat`) |

**Methods:**

```python
def is_nested(self) -> bool:
    """Check if this step contains nested steps."""
```

**Example - Simple step:**
```yaml
- name: "Fetch users"
  tool: http_get
  args:
    url: "http://localhost:8000/users"
  expect: "Should return user list"
```

**Example - Step with analysis:**
```yaml
- name: "Verify pagination"
  tool: api_get_users
  args:
    page: 1
    limit: 10
  expect: "Should return exactly 10 users"
  analyze: |
    Check the response:
    1. Does `data.length` equal 10?
    2. Is `meta.page` equal to 1?
    3. Is `meta.total` greater than 10?
```

**Example - Nested steps with repeat:**
```yaml
- name: "Zoom cycle test"
  repeat: 3
  steps:
    - tool: chart_test_zoom_in
      args: {factor: 0.5}
      save_as: zoom_state
    - tool: chart_test_zoom_out
      args: {factor: 2.0}
```

### VerdictSpec

Specification for pass/fail criteria.

```python
class VerdictSpec(BaseModel):
    pass_if: str    # Conditions for PASS
    fail_if: str    # Conditions for FAIL
```

The LLM evaluates these criteria after all steps complete.

**Example:**
```yaml
verdict:
  pass_if: "All API endpoints return valid responses with correct data types"
  fail_if: "Any endpoint returns 500, times out, or returns malformed data"
```

### StepResult

Result of a single step execution (returned by LLM).

```python
class StepResult(BaseModel):
    name: str                                      # Step name
    status: Literal["pass", "fail", "skip"]        # Result status
    details: str = ""                              # Details about execution
    tool_output: Any = None                        # Raw tool output
```

### Verdict

Final test verdict from LLM.

```python
class Verdict(BaseModel):
    verdict: Literal["PASS", "FAIL", "UNCLEAR"]   # Final result
    reason: str                                    # Explanation
    steps: list[StepResult] = []                   # Step-by-step results
    issues: list[str] = []                         # Issues found (if FAIL)
```

**Verdict values:**

| Value | Meaning | pytest Result |
|-------|---------|---------------|
| `PASS` | Test passed | Test passes |
| `FAIL` | Test failed | Test fails with details |
| `UNCLEAR` | Cannot determine | Test skipped |

---

## Built-in Tools

Built-in tools are registered in `llm_pytest/mcp_server.py` and available in all tests.

### http_get

Make an HTTP GET request.

```python
async def http_get(url: str, headers: dict | None = None) -> dict
```

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | `str` | Yes | URL to fetch |
| `headers` | `dict` | No | HTTP headers |

**Returns:**
```python
{
    "status_code": int,      # HTTP status code
    "body": str,             # Response body (max 10KB)
    "headers": dict          # Response headers
}
```

**Example:**
```yaml
- tool: http_get
  args:
    url: "http://localhost:8000/api/users"
    headers:
      Authorization: "Bearer token123"
  expect: "Status code should be 200"
```

### http_post

Make an HTTP POST request with JSON body.

```python
async def http_post(
    url: str,
    data: dict | None = None,
    headers: dict | None = None
) -> dict
```

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | `str` | Yes | URL to post to |
| `data` | `dict` | No | JSON data to send |
| `headers` | `dict` | No | HTTP headers |

**Returns:**
```python
{
    "status_code": int,
    "body": str,
    "headers": dict
}
```

**Example:**
```yaml
- tool: http_post
  args:
    url: "http://localhost:8000/api/users"
    data:
      name: "John Doe"
      email: "john@example.com"
  expect: "Should create user and return 201"
```

### sleep

Wait for specified duration.

```python
async def sleep(seconds: float) -> dict
```

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `seconds` | `float` | Yes | Seconds to wait |

**Returns:**
```python
{
    "slept": float  # Actual seconds waited
}
```

**Example:**
```yaml
- tool: sleep
  args:
    seconds: 2.5
  expect: "Should wait 2.5 seconds"
```

### assert_equals

Assert that two values are equal.

```python
async def assert_equals(
    actual: Any,
    expected: Any,
    message: str = ""
) -> dict
```

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `actual` | `Any` | Yes | Actual value |
| `expected` | `Any` | Yes | Expected value |
| `message` | `str` | No | Custom failure message |

**Returns:**
```python
{
    "passed": bool,
    "actual": Any,
    "expected": Any,
    "message": str
}
```

### assert_true

Assert that a condition is true.

```python
async def assert_true(condition: bool, message: str = "") -> dict
```

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `condition` | `bool` | Yes | Condition to check |
| `message` | `str` | No | Custom failure message |

**Returns:**
```python
{
    "passed": bool,
    "message": str
}
```

### compare_values

Compare two values with optional tolerance for numeric comparisons.

```python
async def compare_values(
    value1: Any,
    value2: Any,
    tolerance: float = 0.0
) -> dict
```

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `value1` | `Any` | Yes | First value |
| `value2` | `Any` | Yes | Second value |
| `tolerance` | `float` | No | Tolerance as percentage (e.g., 0.05 = 5%) |

**Returns (numeric with tolerance):**
```python
{
    "equal": bool,
    "value1": float,
    "value2": float,
    "difference_percent": float,
    "tolerance_percent": float
}
```

**Returns (non-numeric):**
```python
{
    "equal": bool,
    "value1": Any,
    "value2": Any
}
```

**Example:**
```yaml
- tool: compare_values
  args:
    value1: 100.5
    value2: 100.0
    tolerance: 0.01  # 1% tolerance
  expect: "Values should be within 1% of each other"
```

---

## Runner API

The runner executes tests via Claude Code subprocess.

### run_llm_test

Main entry point for test execution.

```python
def run_llm_test(
    spec: TestSpec,
    yaml_path: Path,
    timeout: int | None = None,
    verbose: bool = False,
) -> Verdict
```

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `spec` | `TestSpec` | Yes | Parsed test specification |
| `yaml_path` | `Path` | Yes | Path to the YAML test file |
| `timeout` | `int` | No | Override spec timeout |
| `verbose` | `bool` | No | Enable verbose output |

**Returns:** `Verdict` object with test results.

**Behavior:**
1. Finds project root (looks for `pyproject.toml`, `setup.py`, or `.git`)
2. Discovers plugins from `tests/llm/plugins/`
3. Creates temporary MCP config
4. Renders prompt from Jinja2 template
5. Calls Claude Code CLI as subprocess
6. Parses JSON verdict from output

**Warning - stdin behavior:**

The Claude Code CLI hangs indefinitely if stdin is not closed. The runner handles this automatically with `stdin=subprocess.DEVNULL`. See the [LLM Providers Guide](llm-providers.md) for details.

---

## pytest Integration

### Command Line Options

| Option | Description |
|--------|-------------|
| `--llm` | Enable LLM test collection |
| `--llm-verbose` | Show detailed output during execution |
| `--llm-timeout N` | Override default timeout (seconds) |

### Markers

Tests are automatically marked with `@pytest.mark.llm`. Tags from `test.tags` become additional markers.

```yaml
test:
  name: "Slow Test"
  tags: ["slow", "integration"]
```

Can be filtered with:
```bash
pytest tests/llm/ --llm -m "not slow"
```

### Classes

#### LLMTestFile

Represents a YAML test file in pytest.

```python
class LLMTestFile(pytest.File):
    def collect(self) -> Generator[LLMTestItem, None, None]:
        """Parse YAML and yield test items."""
```

#### LLMTestItem

A single LLM test item.

```python
class LLMTestItem(pytest.Item):
    spec: TestSpec

    def runtest(self) -> None:
        """Execute test via Claude Code subprocess."""

    def repr_failure(self, excinfo) -> str:
        """Format failure message."""
```

#### LLMTestFailed

Exception raised when an LLM test fails.

```python
class LLMTestFailed(Exception):
    verdict: Verdict
```

---

## File Locations

| Purpose | Path |
|---------|------|
| Models | `llm_pytest/models.py` |
| Plugin base class | `llm_pytest/plugin_base.py` |
| MCP server | `llm_pytest/mcp_server.py` |
| Test runner | `llm_pytest/runner.py` |
| pytest plugin | `llm_pytest/plugin.py` |
| Prompt template | `llm_pytest/templates/test_prompt.jinja2` |
