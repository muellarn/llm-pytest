# llm-pytest

LLM-orchestrated testing framework for pytest. Write tests in YAML with natural language expectations - an LLM executes and evaluates them.

## Philosophy: Data-Driven Analysis, Not Just Pass/Fail

**This is NOT a traditional testing framework.** The key difference:

| Traditional Tests | LLM-Pytest |
|------------------|------------|
| Hard assertions (`assertEqual`) | LLM analyzes actual data |
| Binary pass/fail | Nuanced evaluation with reasoning |
| Fixed expectations | Adaptive understanding of context |
| Fails on first mismatch | Considers overall correctness |

### The Core Idea

Instead of writing:
```python
assert response.status == 200
assert len(data) > 0
```

You write:
```yaml
expect: "Response should contain user records with valid email addresses"
analyze: |
  Look at the actual data returned. Are all emails properly formatted?
  Are there any duplicates? Is the pagination working correctly?
```

**The LLM sees the actual data** and uses its intelligence to determine if it's correct. This catches issues that traditional tests miss:
- Data that's technically valid but semantically wrong
- Edge cases the test author didn't anticipate
- Subtle inconsistencies across multiple fields

### Writing Effective Tests

**BAD - Just checking for success (LLM learns nothing):**
```yaml
- name: "Fetch users"
  tool: api_get_users
  args: {limit: 10}
  expect: "Request should complete"
```

**GOOD - LLM analyzes the actual output:**
```yaml
- name: "Fetch users"
  tool: api_get_users
  args: {limit: 10}
  expect: "Response should contain exactly 10 users with valid data"
  analyze: |
    Check the returned user data:
    1. Does the response contain exactly 10 users?
    2. Does each user have required fields (id, email, name)?
    3. Are all email addresses properly formatted?
    4. Are the IDs unique?

    Report any anomalies you observe in the data.
```

### Plugin Design Guidelines

When writing MCP plugins for llm-pytest, **return rich data for analysis**:

```python
# BAD - Returns minimal info, LLM can't verify anything
async def create_user(self, name: str, email: str) -> dict:
    self._db.insert({"name": name, "email": email})
    return {"status": "ok"}

# GOOD - Returns data for LLM to analyze
async def create_user(self, name: str, email: str) -> dict:
    user_id = self._db.insert({"name": name, "email": email})
    created_user = self._db.get(user_id)
    total_users = self._db.count()

    return {
        "created_user": {
            "id": user_id,
            "name": created_user["name"],
            "email": created_user["email"],
            "created_at": created_user["created_at"],
        },
        "validation": {
            "email_valid": "@" in email and "." in email,
            "name_not_empty": len(name.strip()) > 0,
        },
        "database_state": {
            "total_users": total_users,
            "user_exists": created_user is not None,
        },
    }
```

The LLM then analyzes this data and can spot issues like:
- User created but with invalid email format
- Missing required fields in the response
- Database state inconsistencies
- Timestamps not being set correctly

## Features

- **LLM-agnostic architecture** - pluggable LLM providers (Claude Code is default)
- **Data-driven analysis** - LLM examines actual output values
- **Natural language expectations** instead of hard assertions
- **Variable interpolation** - reference previous results with `${variable}` syntax
- **State persistence** - store and retrieve values across steps
- **Per-step timeout and retry** - fine-grained control over step execution
- **Iterative problem detection** - LLM can identify patterns across steps
- **Automatic MCP configuration** - no manual `claude mcp add` required
- **Plugin system** for project-specific tools
- **Thread-safe** - supports parallel execution with pytest-xdist
- **No API costs** - Claude Code calls itself as subprocess
- **pytest-compatible** - integrates with standard pytest workflow

## Installation

```bash
pip install llm-pytest

# Or for development
pip install -e llm-pytest
```

## Quick Start

### 1. Create a test file

Create `tests/llm/test_example.yaml`:

```yaml
test:
  name: "User Creation Test"
  description: "Verify user creation works correctly"
  timeout: 30

steps:
  - name: "Create a user"
    tool: my_api_create_user
    args:
      name: "Alice"
      email: "alice@example.com"
    save_as: created_user
    expect: "User should be created with valid ID and timestamp"

verdict:
  pass_if: "User was created with correct data"
  fail_if: "User creation failed or data is invalid"
```

### 2. Run the test

```bash
# Run all LLM tests
pytest tests/llm/ --llm -v

# With verbose output (shows tool calls)
pytest tests/llm/ --llm --llm-verbose

# Override timeout
pytest tests/llm/ --llm --llm-timeout 300
```

**Note:** No manual MCP server registration required! The framework automatically creates a temporary MCP config and passes it to Claude.

## Test Format

### Basic Structure

```yaml
test:
  name: "Test Name"
  description: "What this test verifies"
  tags: ["api", "health"]
  timeout: 120  # seconds (test-level default)

setup:
  - tool: tool_name
    args: {key: value}
    expect: "Expected outcome"

steps:
  - name: "Step description"
    tool: tool_name
    args: {key: value}
    expect: "What should happen"
    save_as: result_name
    analyze: "Additional analysis instructions"
    timeout: 30        # Per-step timeout (overrides test-level)
    retry: 3           # Retry attempts on failure
    retry_delay: 2.0   # Delay between retries (seconds)

teardown:
  - tool: tool_name
    args: {}

verdict:
  pass_if: "Conditions for passing"
  fail_if: "Conditions for failing"
```

### Step Fields Reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | No | Human-readable step description |
| `tool` | Yes | Tool to invoke (e.g., `my_plugin_action`, `store_value`) |
| `args` | No | Arguments to pass to the tool |
| `expect` | No | Natural language expectation |
| `analyze` | No | Additional analysis instructions for the LLM |
| `save_as` | No | Save result under this name for later reference |
| `timeout` | No | Per-step timeout in seconds (overrides test-level) |
| `retry` | No | Number of retry attempts on failure |
| `retry_delay` | No | Delay between retries in seconds (default: 1.0) |

### Nested Steps with Repeat

For loops and repeated operations:

```yaml
steps:
  - name: "Create 5 test users"
    repeat: 5
    steps:
      - tool: database_create_user
        args: {name: "Test User", email: "test@example.com"}
        expect: "User created successfully each time"
        save_as: created_user
```

## Variable Interpolation

The framework supports variable interpolation using `${variable}` syntax. This allows you to reference values from previous steps or stored values.

### Syntax

| Pattern | Description |
|---------|-------------|
| `${step_name.field}` | Access a field from a previous step's result |
| `${step_name.nested.field}` | Access nested fields with dot notation |
| `${stored.name}` | Access a value saved with `store_value` |

### Examples

**Referencing previous step results:**

```yaml
steps:
  - name: "Create user"
    tool: api_create_user
    args:
      name: "John Doe"
      email: "john@example.com"
    save_as: new_user
    expect: "User should be created"

  - name: "Fetch created user"
    tool: api_get_user
    args:
      user_id: ${new_user.id}  # Use the ID from the previous step
    expect: "Should return the same user"

  - name: "Update user email"
    tool: api_update_user
    args:
      user_id: ${new_user.id}
      email: ${new_user.email}_updated  # String concatenation
    expect: "Email should be updated"
```

**Using stored values:**

```yaml
steps:
  - name: "Store test config"
    tool: store_value
    args:
      name: "base_url"
      value: "http://localhost:8000"

  - name: "Make API call"
    tool: my_api_fetch_users
    args:
      base_url: ${stored.base_url}
    expect: "Should fetch users"
```

**Accessing nested fields:**

```yaml
steps:
  - name: "Get user details"
    tool: api_get_user
    args: {user_id: 123}
    save_as: user_response

  - name: "Check user address"
    tool: validate_address
    args:
      city: ${user_response.data.address.city}
      zip: ${user_response.data.address.zip_code}
    expect: "Address should be valid"
```

## State Persistence

The framework provides tools for storing and retrieving values across test steps. This is useful for:
- Sharing computed values between steps
- Building up test state incrementally
- Storing configuration values

### Built-in State Tools

| Tool | Description |
|------|-------------|
| `store_value` | Store a value with a name |
| `get_value` | Retrieve a stored value (with optional default) |
| `list_values` | List all stored values |

### Examples

**Store and retrieve values:**

```yaml
steps:
  - name: "Store API token"
    tool: store_value
    args:
      name: "auth_token"
      value: "Bearer abc123"

  - name: "Make authenticated request"
    tool: my_api_fetch_protected
    args:
      token: ${stored.auth_token}
    expect: "Should access protected resource"

  - name: "Verify stored values"
    tool: list_values
    expect: "Should show auth_token in the list"
```

**Using get_value with default:**

```yaml
steps:
  - name: "Get optional config"
    tool: get_value
    args:
      name: "retry_count"
      default: 3
    save_as: config
    expect: "Should return default if not set"
```

## Per-Step Timeout and Retry

### Per-Step Timeout

Override the test-level timeout for specific steps that need more or less time:

```yaml
test:
  name: "Mixed timing test"
  timeout: 60  # Default for all steps

steps:
  - name: "Quick health check"
    tool: my_api_health
    args: {}
    timeout: 5  # Fast timeout for simple check
    expect: "Should respond quickly"

  - name: "Long running operation"
    tool: data_processor_run
    args: {size: 10000}
    timeout: 300  # 5 minutes for heavy operation
    expect: "Should complete processing"
```

### Retry Logic

Automatically retry failed steps with configurable delay:

```yaml
steps:
  - name: "Wait for service to be ready"
    tool: my_api_check_ready
    args: {}
    retry: 5        # Try up to 5 times
    retry_delay: 2.0  # Wait 2 seconds between attempts
    expect: "Service should become ready"

  - name: "Flaky external API"
    tool: external_api_call
    args: {endpoint: "/data"}
    retry: 3
    retry_delay: 1.0
    expect: "Should eventually succeed"
```

**Retry behavior:**
- The step is executed up to `retry + 1` times (initial attempt + retries)
- After each failure, the framework waits `retry_delay` seconds
- If all attempts fail, the step is marked as failed
- The LLM sees the final result (success or last failure)

## Built-in Tools

The framework provides minimal built-in tools focused on orchestration.
All other functionality should be provided by project-specific plugins.

| Tool | Description |
|------|-------------|
| `store_value` | Store a value: `{name: "key", value: ...}` |
| `get_value` | Retrieve a stored value: `{name: "key"}` |
| `list_values` | List all stored keys |
| `sleep` | Wait for seconds: `{seconds: 1.5}` |

**Why so minimal?** The framework's philosophy is that the LLM analyzes
actual data returned by tools. Utility functions like HTTP or assertions
don't fit this model - they belong in project-specific plugins where they
can return rich, analyzable data tailored to your use case.

## Project-Specific Plugins

For project-specific tools (like browser automation), create plugins in `tests/llm/plugins/`.

### 1. Create a plugin

Create `tests/llm/plugins/my_plugin.py`:

```python
from llm_pytest import LLMPlugin

class MyPlugin(LLMPlugin):
    name = "my_plugin"

    async def my_tool(self, arg1: str, arg2: int = 10) -> dict:
        """Description of what this tool does."""
        # Implementation
        return {"result": "value"}

    async def cleanup(self) -> None:
        """Cleanup resources when tests finish."""
        pass
```

### 2. Use in tests

```yaml
steps:
  - name: "Use my tool"
    tool: my_plugin_my_tool
    args:
      arg1: "hello"
      arg2: 42
    expect: "Should return result"
```

The plugin is automatically discovered and loaded from `tests/llm/plugins/`.

## Browser Testing Example

Create `tests/llm/plugins/browser.py`:

```python
from llm_pytest import LLMPlugin
from playwright.async_api import async_playwright

class BrowserPlugin(LLMPlugin):
    name = "browser"

    def __init__(self):
        super().__init__()
        self._playwright = None
        self._browser = None
        self._page = None

    async def open_page(self, url: str) -> dict:
        """Open a URL in the browser."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch()
        self._page = await self._browser.new_page()
        await self._page.goto(url)
        return {"status": "opened", "url": url}

    async def get_title(self) -> dict:
        """Get the page title."""
        title = await self._page.title()
        return {"title": title}

    async def cleanup(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
```

Test file:

```yaml
test:
  name: "Homepage Test"
  timeout: 60

steps:
  - name: "Open homepage"
    tool: browser_open_page
    args:
      url: "http://localhost:8000"
    expect: "Page should open"

  - name: "Check title"
    tool: browser_get_title
    expect: "Title should contain 'Dashboard'"

teardown:
  - tool: browser_cleanup

verdict:
  pass_if: "Homepage loads with correct title"
  fail_if: "Page fails to load or title is wrong"
```

## CLI Options

| Option | Description |
|--------|-------------|
| `--llm` | Enable LLM test collection |
| `--llm-verbose` | Show detailed output during test execution |
| `--llm-timeout N` | Override default timeout (seconds) |

## Architecture

### LLM Provider Abstraction

The framework is LLM-agnostic with a pluggable provider architecture:

```
┌─────────────────────────────────────────────────────────────┐
│ LLMProvider (Abstract Base)                                  │
│ ├── execute(prompt, tools, timeout) -> LLMResponse          │
│ └── cleanup()                                                │
└──────────────────────────────┬──────────────────────────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
           ▼                   ▼                   ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ ClaudeCodeProvider│ │ Future: OpenAI  │ │ Future: Others  │
│ (Default)         │ │ Provider        │ │                  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

**Claude Code** is the default provider. The architecture allows adding new LLM providers without changing the core framework.

### Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│ pytest --llm tests/llm/                                      │
│ Discovers tests/llm/*.yaml files                             │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ llm-pytest Framework                                         │
│ ├── plugin.py      (pytest collector for YAML)              │
│ ├── runner.py      (orchestrates LLM execution)             │
│ ├── providers/     (LLM provider implementations)           │
│ ├── mcp_server.py  (unified MCP server, loads plugins)      │
│ └── plugin_base.py (LLMPlugin base class)                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ LLM Provider (e.g., Claude Code)                             │
│ claude -p "<prompt>" --mcp-config /tmp/...json               │
│ - Reads test definition from prompt                         │
│ - Executes each step via MCP tools                          │
│ - Analyzes results with natural language                    │
│ - Returns JSON verdict                                       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ MCP Server (started by LLM)                                  │
│ Built-in: store_value, get_value, list_values, sleep        │
│ Plugins:  <project>_* (auto-discovered from tests/llm/plugins/)│
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ pytest reports results                                       │
│ PASS → test passes                                           │
│ FAIL → shows reason, steps, and issues                      │
│ UNCLEAR → test marked as skipped                            │
└─────────────────────────────────────────────────────────────┘
```

### Thread Safety

The framework is designed for parallel test execution with pytest-xdist:

- **Unique MCP configs**: Each test gets a unique temporary MCP configuration file
- **Isolated state**: State persistence is scoped to individual test runs
- **No shared resources**: Plugins are instantiated per-test

```bash
# Run tests in parallel
pytest tests/llm/ --llm -n auto
```

## How It Works (Detailed)

1. **pytest discovers YAML files** when `--llm` flag is used
2. **YAML schema validation** ensures test files are correctly formatted
3. **For each test file**, llm-pytest:
   - Parses YAML into `TestSpec` model with validation
   - Discovers plugins from `tests/llm/plugins/`
   - Creates unique temporary MCP config file
   - Applies variable interpolation to step arguments
   - Renders prompt from Jinja2 template
4. **Calls LLM provider** (default: Claude Code) with:
   ```bash
   claude -p "<prompt>" \
     --mcp-config /tmp/llm_pytest_mcp_config_<unique>.json \
     --allowedTools "mcp__llm_pytest__*" \
     --output-format stream-json
   ```
5. **LLM executes test steps** using MCP tools
   - Per-step timeouts are enforced
   - Failed steps are retried according to `retry` setting
   - Results are saved for variable interpolation
6. **LLM returns JSON verdict** with pass/fail and explanation
7. **pytest reports** based on verdict

## Framework Tests

The llm-pytest framework includes comprehensive tests for its core modules:

```bash
# Run all framework tests
pytest llm-pytest/tests/ -v

# Run with coverage
pytest llm-pytest/tests/ --cov=llm_pytest --cov-report=term-missing

# Run specific test module
pytest llm-pytest/tests/test_runner.py -v
```

The test suite covers:
- YAML parsing and schema validation
- Variable interpolation
- State persistence
- Retry logic
- Timeout handling
- Plugin discovery and loading
- LLM provider abstraction

## YAML Schema Validation

The framework validates YAML test files and provides helpful error messages:

**Common validation errors:**

```yaml
# ERROR: Missing required 'tool' field
steps:
  - name: "Bad step"
    args: {foo: bar}
# Fix: Add 'tool' field

# ERROR: Invalid timeout type
steps:
  - name: "Bad timeout"
    tool: my_plugin_action
    timeout: "thirty"  # Must be a number
# Fix: Use timeout: 30

# ERROR: Unknown field
steps:
  - name: "Unknown field"
    tool: my_plugin_action
    wait_for: ready  # 'wait_for' is not a valid field
# Fix: Remove unknown field or check spelling
```

**Validation provides:**
- Clear error messages pointing to the problem
- Suggestions for common mistakes
- Line numbers when available

## Troubleshooting

### "claude command not found"

Ensure Claude Code CLI is installed and in PATH:
```bash
which claude
claude --version
```

### "MCP tools not found"

The framework auto-creates MCP config. If tools still not found:
- Check that `llm-pytest` is installed: `pip install -e llm-pytest`
- Check plugin syntax: must extend `LLMPlugin` and have `name` attribute

### Tests timing out

Increase timeout in the test YAML or via CLI:
```bash
pytest tests/llm/ --llm --llm-timeout 300
```

Or use per-step timeouts for specific slow steps:
```yaml
steps:
  - name: "Slow operation"
    tool: slow_tool
    timeout: 120  # This step gets more time
```

### Tests hang forever (no output)

**This is likely the stdin bug.** When running Claude Code CLI as a subprocess, it hangs indefinitely if stdin is not closed. The framework handles this automatically, but if you're implementing a custom LLM client or debugging:

**Symptoms:**
- Test hangs with no output
- Process doesn't respond to timeout
- Works fine when running `claude` manually in terminal

**Cause:** Claude Code CLI waits for user input even in non-interactive mode.

**Solution:** Always use `stdin=subprocess.DEVNULL` when spawning Claude:
```python
subprocess.run(
    ["claude", "-p", prompt, ...],
    stdin=subprocess.DEVNULL,  # CRITICAL!
    ...
)
```

See: https://github.com/anthropics/claude-code/issues/1292

### Variable interpolation not working

Check that:
1. The referenced step has `save_as` defined
2. The variable name matches exactly (case-sensitive)
3. The field path is correct for nested access

```yaml
# Correct
- name: "Step A"
  tool: some_tool
  save_as: step_a_result  # Define save_as

- name: "Step B"
  tool: other_tool
  args:
    value: ${step_a_result.field}  # Reference correctly
```

### Retry not working as expected

- Retries only happen on step failure (tool returns error)
- `retry: 3` means 3 retry attempts (4 total attempts)
- Check that `retry_delay` is a number, not a string

### Verbose debugging

Use `--llm-verbose` to see all tool calls and results:
```bash
pytest tests/llm/test_example.yaml --llm -v --llm-verbose
```

Output shows:
```
[tool] mcp__llm_pytest__my_api_create_user({"name": "Alice", "email": "alice@example.com"})
[tool result] OK: {"id": 42, "name": "Alice", "email": "alice@example.com"}
[tool] mcp__llm_pytest__store_value({"name": "user_id", "value": 42})
[interpolate] ${stored.user_id} -> 42
```

## Advantages

- **LLM-agnostic** - pluggable provider architecture
- **No API costs** - Claude Code calls itself as subprocess
- **Natural language** - Tests read like documentation
- **Flexible** - LLM handles unexpected situations gracefully
- **Explainable** - LLM explains why tests fail in detail
- **No mocking** - Tests run against real services
- **pytest-compatible** - Standard pytest workflow
- **Auto-discovery** - Plugins loaded automatically from `tests/llm/plugins/`
- **Auto MCP config** - No manual `claude mcp add` required
- **Thread-safe** - Works with pytest-xdist parallel execution
- **Rich interpolation** - Reference previous results easily
- **Retry support** - Handle flaky tests gracefully

## License

MIT
