# Plugin Development Guide

This guide explains how to create plugins for llm-pytest. Plugins extend the framework with project-specific MCP tools.

## Overview

Plugins are Python classes that:
1. Extend `LLMPlugin` base class
2. Define async methods that become MCP tools
3. Are auto-discovered from `tests/llm/plugins/`

## Quick Start

### 1. Create the plugin file

Create `tests/llm/plugins/my_plugin.py`:

```python
from llm_pytest import LLMPlugin

class MyPlugin(LLMPlugin):
    """Plugin for testing my application."""

    name = "my_app"  # Tool prefix

    async def get_status(self) -> dict:
        """Get application status."""
        return {
            "running": True,
            "version": "1.0.0",
            "uptime_seconds": 3600,
        }

    async def create_item(self, name: str, value: int = 0) -> dict:
        """Create a new item.

        Args:
            name: Item name
            value: Initial value (default: 0)
        """
        # Your implementation
        return {
            "created": True,
            "item": {"name": name, "value": value},
        }

    async def cleanup(self) -> None:
        """Cleanup resources."""
        # Called when tests finish
        pass
```

### 2. Use in tests

```yaml
test:
  name: "My App Test"
  timeout: 30

steps:
  - name: "Check status"
    tool: my_app_get_status
    expect: "Application should be running"

  - name: "Create item"
    tool: my_app_create_item
    args:
      name: "test-item"
      value: 42
    expect: "Item should be created with correct name and value"

teardown:
  - tool: my_app_cleanup

verdict:
  pass_if: "Application is running and items can be created"
  fail_if: "Application is down or item creation fails"
```

---

## Plugin Lifecycle

### 1. Discovery

Plugins are discovered when the MCP server starts:
- Location: `tests/llm/plugins/*.py`
- Files starting with `_` are ignored
- Must contain a class extending `LLMPlugin`

### 2. Initialization

Each plugin is instantiated once per test session:

```python
class MyPlugin(LLMPlugin):
    def __init__(self):
        super().__init__()
        # Initialize state
        self._connections = []
        self._started = False
```

### 3. Tool Registration

All public async methods become MCP tools:
- Method name: `do_something`
- Tool name: `{plugin.name}_do_something`
- Example: `my_app_do_something`

### 4. Cleanup

The `cleanup()` method is called when tests finish:

```python
async def cleanup(self) -> None:
    """Release resources."""
    for conn in self._connections:
        await conn.close()
    self._connections = []
```

---

## LLMPlugin Base Class

Located in `llm_pytest/plugin_base.py`.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Plugin name (used as tool prefix) |
| `_state` | `dict` | Internal state dictionary |

### Methods

#### get_tools

Returns tool definitions for MCP registration.

```python
def get_tools(self) -> list[dict[str, Any]]:
    """Get all tool definitions from this plugin.

    Returns:
        List of tool definitions with name, description, and parameters
    """
```

Automatically called during registration. You typically don't need to override this.

#### call_tool

Call a tool by name.

```python
async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
    """Call a tool by name.

    Args:
        tool_name: The tool name (with or without plugin prefix)
        arguments: The tool arguments

    Returns:
        The tool result
    """
```

#### cleanup

Override to release resources.

```python
async def cleanup(self) -> None:
    """Cleanup resources. Override in subclass if needed."""
    pass
```

---

## Writing Effective Tools

### Return Rich Data

**The LLM needs data to analyze.** Return comprehensive information, not just status codes.

```python
# BAD - LLM learns nothing
async def create_user(self, email: str) -> dict:
    self._db.insert(email)
    return {"status": "ok"}

# GOOD - LLM can analyze the data
async def create_user(self, email: str) -> dict:
    user_id = self._db.insert(email)
    user = self._db.get(user_id)
    total = self._db.count()

    return {
        "created_user": {
            "id": user_id,
            "email": user["email"],
            "created_at": user["created_at"],
        },
        "validation": {
            "email_format_valid": "@" in email and "." in email,
            "email_domain": email.split("@")[-1] if "@" in email else None,
        },
        "database_state": {
            "total_users": total,
            "user_persisted": user is not None,
        },
    }
```

### Include Before/After State

For operations that modify state, return both:

```python
async def update_config(self, key: str, value: Any) -> dict:
    old_value = self._config.get(key)
    self._config[key] = value
    new_value = self._config.get(key)

    return {
        "key": key,
        "before": old_value,
        "after": new_value,
        "changed": old_value != new_value,
        "config_snapshot": dict(self._config),  # Full state
    }
```

### Add Computed Analysis

Include computed values that help the LLM analyze:

```python
async def zoom_to_range(self, factor: float) -> dict:
    old_range = self._visible_range.copy()

    # Calculate new range
    mid = (old_range["from"] + old_range["to"]) / 2
    half = (old_range["to"] - old_range["from"]) * factor / 2
    new_range = {"from": mid - half, "to": mid + half}

    self._visible_range = new_range

    return {
        "before": {
            "range": old_range,
            "duration_days": (old_range["to"] - old_range["from"]) / 86400,
        },
        "after": {
            "range": new_range,
            "duration_days": (new_range["to"] - new_range["from"]) / 86400,
        },
        "symmetry_check": {
            "expected_center": mid,
            "actual_center": (new_range["from"] + new_range["to"]) / 2,
            "center_drift_percent": abs((new_range["from"] + new_range["to"]) / 2 - mid) / (new_range["to"] - new_range["from"]) * 100,
        },
        "factor_applied": factor,
        "expected_duration_ratio": factor,
        "actual_duration_ratio": (new_range["to"] - new_range["from"]) / (old_range["to"] - old_range["from"]),
    }
```

### Sample Data for Verification

Include sample data the LLM can examine:

```python
async def load_data(self, start: str, end: str) -> dict:
    records = self._db.query(start=start, end=end)

    # Sample records for LLM to verify
    sample_size = min(5, len(records))
    samples = [
        records[0],                          # First
        records[len(records) // 2],          # Middle
        records[-1],                         # Last
    ] if records else []

    return {
        "total_records": len(records),
        "requested_range": {"start": start, "end": end},
        "actual_range": {
            "first": records[0]["timestamp"] if records else None,
            "last": records[-1]["timestamp"] if records else None,
        },
        "sample_records": samples,
        "statistics": {
            "unique_ids": len(set(r["id"] for r in records)),
            "has_duplicates": len(records) != len(set(r["id"] for r in records)),
        },
    }
```

---

## Type Hints and Schema Generation

Type hints are automatically converted to JSON schema:

```python
async def search(
    self,
    query: str,              # Required string
    limit: int = 10,         # Optional integer with default
    include_deleted: bool = False,  # Optional boolean
) -> dict:
    """Search for items.

    Args:
        query: Search query string
        limit: Maximum results (default: 10)
        include_deleted: Include deleted items
    """
```

Generates this JSON schema:
```json
{
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Parameter query"},
        "limit": {"type": "integer", "default": 10},
        "include_deleted": {"type": "boolean", "default": false}
    },
    "required": ["query"]
}
```

### Type Mapping

| Python Type | JSON Schema Type |
|-------------|-----------------|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list` | `"array"` |
| `dict` | `"object"` |
| `Optional[X]` | type of X |

---

## Complete Example: Database Plugin

```python
"""Database testing plugin for llm-pytest."""

from __future__ import annotations

import asyncio
from typing import Any
from llm_pytest import LLMPlugin


class DatabasePlugin(LLMPlugin):
    """Plugin for testing database operations."""

    name = "db"

    def __init__(self):
        super().__init__()
        self._connection = None
        self._tables: dict[str, list[dict]] = {}

    async def connect(self, database: str = "test.db") -> dict:
        """Connect to the database.

        Args:
            database: Database file path
        """
        # Simulated connection
        await asyncio.sleep(0.1)
        self._connection = {"database": database, "connected": True}

        return {
            "connected": True,
            "database": database,
            "tables": list(self._tables.keys()),
        }

    async def create_table(self, name: str, columns: list[str]) -> dict:
        """Create a new table.

        Args:
            name: Table name
            columns: Column names
        """
        if not self._connection:
            return {"error": "Not connected. Call connect() first."}

        existed = name in self._tables
        self._tables[name] = []

        return {
            "created": True,
            "table": name,
            "columns": columns,
            "already_existed": existed,
            "total_tables": len(self._tables),
        }

    async def insert(
        self,
        table: str,
        data: dict[str, Any],
    ) -> dict:
        """Insert a record into a table.

        Args:
            table: Table name
            data: Record data
        """
        if table not in self._tables:
            return {"error": f"Table '{table}' does not exist"}

        record_id = len(self._tables[table]) + 1
        record = {"id": record_id, **data}
        self._tables[table].append(record)

        return {
            "inserted": True,
            "record": record,
            "table_size": len(self._tables[table]),
        }

    async def query(
        self,
        table: str,
        where: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> dict:
        """Query records from a table.

        Args:
            table: Table name
            where: Filter conditions
            limit: Maximum records to return
        """
        if table not in self._tables:
            return {"error": f"Table '{table}' does not exist"}

        records = self._tables[table]

        # Apply filter
        if where:
            records = [
                r for r in records
                if all(r.get(k) == v for k, v in where.items())
            ]

        # Apply limit
        records = records[:limit]

        return {
            "records": records,
            "count": len(records),
            "total_in_table": len(self._tables[table]),
            "filter_applied": where,
            "limit_applied": limit,
        }

    async def get_stats(self) -> dict:
        """Get database statistics."""
        return {
            "connected": self._connection is not None,
            "tables": {
                name: len(records)
                for name, records in self._tables.items()
            },
            "total_records": sum(
                len(records) for records in self._tables.values()
            ),
        }

    async def cleanup(self) -> None:
        """Disconnect and cleanup."""
        self._connection = None
        self._tables = {}
```

**Example test using this plugin:**

```yaml
test:
  name: "Database CRUD Operations"
  description: "Test basic database operations"
  timeout: 60

setup:
  - tool: db_connect
    args:
      database: "test.db"
    expect: "Should connect successfully"

  - tool: db_create_table
    args:
      name: "users"
      columns: ["name", "email", "age"]
    expect: "Table should be created"

steps:
  - name: "Insert first user"
    tool: db_insert
    args:
      table: "users"
      data:
        name: "Alice"
        email: "alice@example.com"
        age: 30
    expect: "User should be inserted with ID 1"
    save_as: first_user

  - name: "Insert second user"
    tool: db_insert
    args:
      table: "users"
      data:
        name: "Bob"
        email: "bob@example.com"
        age: 25
    expect: "User should be inserted with ID 2"

  - name: "Query all users"
    tool: db_query
    args:
      table: "users"
    expect: "Should return both users"
    analyze: |
      Verify the query results:
      1. Count should be 2
      2. Both Alice and Bob should be present
      3. IDs should be sequential (1, 2)

  - name: "Query with filter"
    tool: db_query
    args:
      table: "users"
      where:
        name: "Alice"
    expect: "Should return only Alice"

  - name: "Get statistics"
    tool: db_get_stats
    expect: "Stats should show 1 table with 2 records"

teardown:
  - tool: db_cleanup

verdict:
  pass_if: "All CRUD operations work correctly with proper data"
  fail_if: "Any operation fails or returns incorrect data"
```

---

## Best Practices

### 1. Use descriptive docstrings

The first line of the docstring becomes the tool description:

```python
async def calculate_metrics(self, data: list) -> dict:
    """Calculate performance metrics from data."""  # This is shown in tool list
    ...
```

### 2. Handle errors gracefully

Return error information instead of raising exceptions:

```python
async def fetch_data(self, url: str) -> dict:
    try:
        response = await self._client.get(url)
        return {"status": response.status, "data": response.json()}
    except Exception as e:
        return {"error": str(e), "url": url}
```

### 3. Track state for debugging

Maintain state that helps debug failures:

```python
def __init__(self):
    super().__init__()
    self._operation_history = []

async def do_operation(self, op: str) -> dict:
    result = await self._execute(op)
    self._operation_history.append({
        "operation": op,
        "result": result,
        "timestamp": time.time(),
    })
    return result

async def get_history(self) -> dict:
    """Get operation history for debugging."""
    return {"history": self._operation_history}
```

### 4. Implement cleanup properly

Always clean up resources:

```python
async def cleanup(self) -> None:
    """Release all resources."""
    errors = []

    if self._browser:
        try:
            await self._browser.close()
        except Exception as e:
            errors.append(f"Browser: {e}")
        self._browser = None

    if self._server:
        try:
            self._server.terminate()
        except Exception as e:
            errors.append(f"Server: {e}")
        self._server = None

    # Don't raise - just log errors
    if errors:
        print(f"Cleanup warnings: {errors}")
```

---

## File Locations

| Purpose | Path |
|---------|------|
| Plugin base class | `llm_pytest/plugin_base.py` |
| MCP server (loads plugins) | `llm_pytest/mcp_server.py` |
| Example plugins | `tests/llm/plugins/` |
