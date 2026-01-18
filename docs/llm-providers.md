# LLM Provider Guide

This guide explains the LLM provider architecture in llm-pytest and how to add new providers.

## Architecture Overview

llm-pytest uses an LLM to execute and evaluate tests. The current implementation uses Claude Code CLI as a subprocess.

```
┌─────────────────────────────────────────────────────────────┐
│ pytest --llm tests/llm/                                      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ llm_pytest/runner.py                                         │
│ run_llm_test() - orchestrates test execution                 │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Claude Code CLI (subprocess)                                 │
│ claude -p "<prompt>" --mcp-config /tmp/...json               │
│                                                              │
│ - Receives test definition in prompt                         │
│ - Executes steps via MCP tools                              │
│ - Returns JSON verdict                                       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ llm_pytest/mcp_server.py (started by Claude)                 │
│ Provides tools: http_*, assert_*, plugin_*                   │
└─────────────────────────────────────────────────────────────┘
```

## Current Implementation: Claude Code Provider

The current provider uses Claude Code CLI as a subprocess. Key implementation details are in `llm_pytest/runner.py`.

### How It Works

1. **MCP Configuration**

   A temporary MCP config file is created:
   ```python
   config = {
       "mcpServers": {
           "llm_pytest": {
               "command": sys.executable,
               "args": ["-m", "llm_pytest.mcp_server", "--project-root", str(project_root)],
               "cwd": str(project_root),
           }
       }
   }
   ```

2. **Prompt Generation**

   The test spec is rendered into a prompt using Jinja2:
   ```python
   template = env.get_template("test_prompt.jinja2")
   prompt = template.render(yaml_content=yaml_path.read_text(), spec=spec)
   ```

3. **Claude CLI Invocation**

   ```python
   base_cmd = [
       "claude",
       "-p", prompt,
       "--mcp-config", str(mcp_config),
       "--allowedTools", "mcp__llm_pytest__*",
   ]
   ```

4. **Output Parsing**

   Claude returns JSON which is parsed into a `Verdict` object.

### Verbose vs Non-Verbose Mode

**Non-verbose mode:**
```python
result = subprocess.run(
    base_cmd + ["--output-format", "json"],
    stdin=subprocess.DEVNULL,
    capture_output=True,
    text=True,
    timeout=effective_timeout,
)
```

**Verbose mode:**
```python
process = subprocess.Popen(
    base_cmd + ["--output-format", "stream-json", "--verbose"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1,
)

# Stream NDJSON events in real-time
for line in process.stdout:
    event = json.loads(line)
    # Handle different event types: assistant, tool_use, tool_result, etc.
```

---

## Critical: stdin Quirk

**The Claude Code CLI hangs indefinitely if stdin is not explicitly closed.**

### Symptoms

- Test hangs forever with no output
- Process doesn't respond to timeout
- Works fine when running `claude` manually in terminal
- Affects both verbose and non-verbose modes

### Cause

The Claude Code CLI waits for potential user input even when running non-interactively with `-p`. This is a known behavior.

### Solution

**Always use `stdin=subprocess.DEVNULL`:**

```python
# For subprocess.run()
result = subprocess.run(
    ["claude", "-p", prompt, ...],
    stdin=subprocess.DEVNULL,  # CRITICAL!
    capture_output=True,
    ...
)

# For subprocess.Popen()
process = subprocess.Popen(
    ["claude", "-p", prompt, ...],
    stdin=subprocess.DEVNULL,  # CRITICAL!
    stdout=subprocess.PIPE,
    ...
)
```

### Reference

See: https://github.com/anthropics/claude-code/issues/1292

This quirk is documented in the code:
```python
# CRITICAL: Claude Code CLI stdin behavior
# =========================================
# The Claude Code CLI hangs indefinitely if stdin is not closed.
# This is because the CLI waits for potential user input even when
# running non-interactively. Always use stdin=subprocess.DEVNULL
# or explicitly close stdin after process creation.
```

---

## Adding a New Provider

To add a different LLM provider (e.g., OpenAI API, local Ollama), you would need to:

### 1. Define a Provider Interface

```python
# llm_pytest/providers/base.py

from abc import ABC, abstractmethod
from ..models import TestSpec, Verdict

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def execute_test(
        self,
        spec: TestSpec,
        tools: list[dict],
        timeout: int,
        verbose: bool = False,
    ) -> Verdict:
        """Execute a test using this LLM provider.

        Args:
            spec: The parsed test specification
            tools: List of available MCP tools
            timeout: Maximum execution time in seconds
            verbose: Whether to print verbose output

        Returns:
            Verdict object with test results
        """
        pass

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool.

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Tool result
        """
        pass
```

### 2. Implement the Provider

```python
# llm_pytest/providers/openai_provider.py

import json
from openai import AsyncOpenAI
from .base import LLMProvider
from ..models import TestSpec, Verdict

class OpenAIProvider(LLMProvider):
    """LLM provider using OpenAI API."""

    def __init__(self, model: str = "gpt-4"):
        self.client = AsyncOpenAI()
        self.model = model
        self._tools = []

    async def execute_test(
        self,
        spec: TestSpec,
        tools: list[dict],
        timeout: int,
        verbose: bool = False,
    ) -> Verdict:
        self._tools = tools

        # Convert tools to OpenAI format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["inputSchema"],
                }
            }
            for tool in tools
        ]

        # Build prompt
        prompt = self._build_prompt(spec)

        # Call OpenAI with tool use
        messages = [{"role": "user", "content": prompt}]

        while True:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
            )

            message = response.choices[0].message

            if message.tool_calls:
                # Handle tool calls
                messages.append(message)

                for tool_call in message.tool_calls:
                    result = await self.call_tool(
                        tool_call.function.name,
                        json.loads(tool_call.function.arguments),
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    })
            else:
                # Final response - parse verdict
                return self._parse_verdict(message.content)

    async def call_tool(self, name: str, arguments: dict) -> dict:
        # Dispatch to actual tool implementation
        # This would need access to the MCP server or direct tool calls
        pass

    def _build_prompt(self, spec: TestSpec) -> str:
        # Similar to test_prompt.jinja2
        pass

    def _parse_verdict(self, content: str) -> Verdict:
        # Parse JSON verdict from response
        pass
```

### 3. Register the Provider

```python
# llm_pytest/providers/__init__.py

from typing import Literal
from .base import LLMProvider
from .claude_code import ClaudeCodeProvider

PROVIDERS: dict[str, type[LLMProvider]] = {
    "claude-code": ClaudeCodeProvider,
    # "openai": OpenAIProvider,
    # "ollama": OllamaProvider,
}

def get_provider(name: str = "claude-code") -> LLMProvider:
    """Get an LLM provider by name."""
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Available: {list(PROVIDERS.keys())}")
    return PROVIDERS[name]()
```

### 4. Update the Runner

```python
# llm_pytest/runner.py

from .providers import get_provider

def run_llm_test(
    spec: TestSpec,
    yaml_path: Path,
    timeout: int | None = None,
    verbose: bool = False,
    provider: str = "claude-code",  # New parameter
) -> Verdict:
    """Run a test via LLM provider."""
    llm = get_provider(provider)
    # ...
```

---

## Provider Requirements

Any LLM provider must:

1. **Execute MCP tools** - Call the tools defined in the test
2. **Follow the test structure** - Execute setup, steps, teardown in order
3. **Return a Verdict** - Produce valid JSON matching the Verdict model
4. **Handle timeouts** - Respect the test timeout
5. **Support streaming (optional)** - For verbose mode

### Verdict Format

The provider must return JSON in this format:

```json
{
    "verdict": "PASS" | "FAIL" | "UNCLEAR",
    "reason": "Brief explanation of the result",
    "steps": [
        {
            "name": "Step Name",
            "status": "pass" | "fail" | "skip",
            "details": "What happened"
        }
    ],
    "issues": ["List of problems found (if FAIL)"]
}
```

---

## MCP Server Communication

The MCP server (`llm_pytest/mcp_server.py`) provides tools via the [Model Context Protocol](https://modelcontextprotocol.io/).

### Server Startup

For Claude Code, the MCP server is started automatically via the config:

```json
{
    "mcpServers": {
        "llm_pytest": {
            "command": "python",
            "args": ["-m", "llm_pytest.mcp_server", "--project-root", "/path/to/project"]
        }
    }
}
```

### Tool Discovery

Plugins are discovered from `tests/llm/plugins/`:

```python
def discover_plugins(self) -> list[LLMPlugin]:
    plugins_dir = self.project_root / "tests" / "llm" / "plugins"
    for plugin_file in plugins_dir.glob("*.py"):
        if plugin_file.name.startswith("_"):
            continue
        plugin = self._load_plugin(plugin_file)
        if plugin:
            plugins.append(plugin)
    return plugins
```

### Tool Registration

Tools are registered with FastMCP:

```python
def _register_plugin_methods(self, plugin: LLMPlugin) -> None:
    for method_name in dir(plugin):
        if method_name.startswith("_"):
            continue

        method = getattr(plugin, method_name)
        if not asyncio.iscoroutinefunction(method):
            continue

        if method_name in ("get_tools", "call_tool", "cleanup"):
            continue

        tool_name = f"{plugin.name}_{method_name}"
        self._mcp.tool(name=tool_name)(method)
```

---

## File Locations

| Purpose | Path |
|---------|------|
| Current runner (Claude Code) | `llm_pytest/runner.py` |
| MCP server | `llm_pytest/mcp_server.py` |
| Plugin base class | `llm_pytest/plugin_base.py` |
| Prompt template | `llm_pytest/templates/test_prompt.jinja2` |
| Models | `llm_pytest/models.py` |

---

## Future Considerations

### Alternative Providers

Potential providers to implement:

| Provider | Pros | Cons |
|----------|------|------|
| OpenAI API | Standard API, good tool support | Costs money, no MCP native |
| Anthropic API | Native Claude, consistent | Costs money |
| Ollama | Free, local | Less capable models |
| LiteLLM | Multi-provider | Extra dependency |

### Tool Protocol

The current implementation uses MCP, but providers could also:
- Use OpenAI function calling format
- Use Anthropic tool use format
- Implement a custom tool protocol

### Streaming Support

For better UX, providers should support streaming:
- Real-time tool call visibility
- Progress indication
- Early termination on failure
