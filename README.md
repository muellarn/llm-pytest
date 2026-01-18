# llm-pytest

LLM-orchestrated testing framework for pytest. Write tests in YAML with natural language expectations - Claude Code executes and evaluates them.

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
expect: "Response should contain candle data with timestamps in ascending order"
analyze: |
  Look at the actual timestamps returned. Are they sequential?
  Are there any gaps? Is the data range what we requested?
```

**The LLM sees the actual data** and uses its intelligence to determine if it's correct. This catches issues that traditional tests miss:
- Data that's technically valid but semantically wrong
- Edge cases the test author didn't anticipate
- Subtle inconsistencies across multiple fields

### Writing Effective Tests

**BAD - Just checking for success (LLM learns nothing):**
```yaml
- name: "Zoom in"
  tool: chart.zoom_in
  args: {factor: 0.5}
  expect: "Zoom should complete"
```

**GOOD - LLM analyzes the actual output:**
```yaml
- name: "Zoom in"
  tool: chart.zoom_in
  args: {factor: 0.5}
  expect: "Visible range should be halved, centered on the same point"
  analyze: |
    Check the before/after ranges in the output:
    1. Is the new duration approximately 50% of the old duration?
    2. Is the center point the same (within 1% tolerance)?
    3. Did the resolution change if we crossed a threshold?
    4. Are the cached candles covering the new visible range?

    Report any anomalies you observe in the data.
```

### Plugin Design Guidelines

When writing MCP plugins for llm-pytest, **return rich data for analysis**:

```python
# BAD - Returns minimal info, LLM can't verify anything
async def zoom_in(self, factor: float) -> dict:
    self._do_zoom(factor)
    return {"status": "ok"}

# GOOD - Returns data for LLM to analyze
async def zoom_in(self, factor: float) -> dict:
    old_range = self._visible_range.copy()
    self._do_zoom(factor)
    new_range = self._visible_range

    return {
        "before": {
            "range_start": old_range["from"],
            "range_end": old_range["to"],
            "duration_days": (old_range["to"] - old_range["from"]) / 86400,
        },
        "after": {
            "range_start": new_range["from"],
            "range_end": new_range["to"],
            "duration_days": (new_range["to"] - new_range["from"]) / 86400,
        },
        "expected_center": (old_range["from"] + old_range["to"]) / 2,
        "actual_center": (new_range["from"] + new_range["to"]) / 2,
        "cache_state": self._get_cache_summary(),
        "sample_candles": [...],  # Actual data points for verification
    }
```

The LLM then analyzes this data and can spot issues like:
- Center drift that accumulates over multiple zooms
- Cache not covering the visible range
- Duration not matching the expected factor
- Timestamps out of order in the cache

## Features

- **Data-driven analysis** - LLM examines actual output values
- **Natural language expectations** instead of hard assertions
- **Iterative problem detection** - LLM can identify patterns across steps
- **Automatic MCP configuration** - no manual `claude mcp add` required
- **Plugin system** for project-specific tools
- **No API costs** - Claude Code calls itself as subprocess
- **pytest-compatible** - integrates with standard pytest workflow

## Installation

```bash
pip install -e llm-pytest

# For browser tests (optional)
pip install playwright
playwright install chromium
```

## Quick Start

### 1. Create a test file

Create `tests/llm/test_example.yaml`:

```yaml
test:
  name: "API Health Check"
  description: "Verify the API is responding"
  timeout: 30

steps:
  - name: "Check health endpoint"
    tool: http_get
    args:
      url: "http://localhost:8000/health"
    expect: "status_code should be 200"

verdict:
  pass_if: "Health endpoint returns 200"
  fail_if: "Health endpoint is unreachable or returns error"
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
  timeout: 120  # seconds

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

teardown:
  - tool: tool_name
    args: {}

verdict:
  pass_if: "Conditions for passing"
  fail_if: "Conditions for failing"
```

### Nested Steps with Repeat

For loops and repeated operations:

```yaml
steps:
  - name: "Zoom in 5 times"
    repeat: 5
    steps:
      - tool: chart_test_zoom_in
        args: {factor: 0.5}
        expect: "Range halves each time"
        save_as: zoom_step
```

## Built-in Tools

| Tool | Description |
|------|-------------|
| `http_get` | Make HTTP GET request |
| `http_post` | Make HTTP POST request |
| `sleep` | Wait for seconds |
| `assert_equals` | Compare two values |
| `assert_true` | Check condition |
| `compare_values` | Compare with tolerance |

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
│ ├── runner.py      (calls claude -p with --mcp-config)      │
│ ├── mcp_server.py  (unified MCP server, loads plugins)      │
│ └── plugin_base.py (LLMPlugin base class)                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ claude -p "<prompt>" --mcp-config /tmp/...json               │
│ Claude Code executes as subprocess                           │
│ - Reads test definition from prompt                         │
│ - Executes each step via MCP tools                          │
│ - Analyzes results with natural language                    │
│ - Returns JSON verdict                                       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ MCP Server (started by Claude)                               │
│ Built-in: http_get, http_post, sleep, assert_*              │
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

## How It Works (Detailed)

1. **pytest discovers YAML files** when `--llm` flag is used
2. **For each test file**, llm-pytest:
   - Parses YAML into `TestSpec` model
   - Discovers plugins from `tests/llm/plugins/`
   - Creates temporary MCP config file pointing to unified server
   - Renders prompt from Jinja2 template
3. **Calls Claude Code** with:
   ```bash
   claude -p "<prompt>" \
     --mcp-config /tmp/llm_pytest_mcp_config.json \
     --allowedTools "mcp__llm_pytest__*" \
     --output-format stream-json
   ```
4. **Claude executes test steps** using MCP tools
5. **Claude returns JSON verdict** with pass/fail and explanation
6. **pytest reports** based on verdict

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

### Verbose debugging

Use `--llm-verbose` to see all tool calls and results:
```bash
pytest tests/llm/test_example.yaml --llm -v --llm-verbose
```

Output shows:
```
[tool] mcp__llm_pytest__http_get({"url": "http://localhost:8000/health"})
[tool result] OK: {"status_code": 200, "body": "..."}
```

## Advantages

- **No API costs** - Claude Code calls itself as subprocess
- **Natural language** - Tests read like documentation
- **Flexible** - LLM handles unexpected situations gracefully
- **Explainable** - LLM explains why tests fail in detail
- **No mocking** - Tests run against real services
- **pytest-compatible** - Standard pytest workflow
- **Auto-discovery** - Plugins loaded automatically from `tests/llm/plugins/`
- **Auto MCP config** - No manual `claude mcp add` required

## License

MIT
