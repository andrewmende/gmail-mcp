# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A [FastMCP](https://github.com/jlowin/fastmcp) server that wraps the Google Workspace CLI (`gws`) to expose Gmail (and potentially other Google Workspace services) as MCP tools consumable by Claude and other AI models.

## Setup

Install the Python dependency:
```bash
.venv/bin/pip install fastmcp
```

Install the Google Workspace CLI globally (requires Node.js):
```bash
npm install -g @googleworkspace/cli
```

Run the server:
```bash
.venv/bin/python server.py
```

Run the end-to-end test suite (requires valid `gws` credentials):
```bash
.venv/bin/pytest tests/ -v
```

## Architecture

Everything lives in `server.py`. The pattern is:

1. **`run_gws(*args, **options)`** — async helper that shells out to the `gws` CLI via `asyncio.create_subprocess_exec`. It appends CLI flags (pagination, format, dry-run, upload/output paths) from keyword args, then parses stdout as JSON. On failure it returns `{"error": ..., "returncode": ...}`.

2. **`mcp = FastMCP(...)`** — the MCP server instance. Tools are registered by decorating async functions with `@mcp.tool()`.

3. **Tool functions** — each calls `run_gws()` with the appropriate `gws` subcommand and a `--params` JSON blob matching the Google API method signature.

## Backlog Task Checklist

When working on any item from BACKLOG.md, follow these steps in order:

1. **Do the task** — implement the change in `server.py`
2. **Update MCP documentation** — revise the tool docstring, `Args:` section, and `FastMCP(instructions=...)` if the server's capabilities changed (see _MCP Documentation_ section below)
3. **Update tests** — add or update tests in `tests/test_gmail.py` to cover the new or changed behavior
4. **Run tests** — confirm all tests pass before marking the item done in BACKLOG.md

```bash
.venv/bin/pytest tests/ -v
```

5. **Mark done** — check off the item in BACKLOG.md (`- [ ]` → `- [x]`)

## MCP Documentation — Keep It Current

The docstring and `Args:` section of every `@mcp.tool()` function are the sole documentation an agent has when deciding whether and how to call a tool. **Whenever you add or modify a tool, you must update:**

1. **The function docstring** — describe what the tool returns, not just what it does. Mention the shape of the response and any important caveats (e.g. "returns IDs only").
2. **The `Args:` section** — every parameter needs a description with valid values or examples.
3. **`FastMCP(instructions=...)`** — update if the server's overall capability set changes (new service areas, new error patterns, new usage guidance).

Treat these the same as code — a tool with a stale or vague docstring is broken for the agent using it.

## Adding New Tools

Follow the existing `gmail_list_messages` pattern:

```python
@mcp.tool()
async def gmail_<action>(arg: type = default) -> dict | str:
    """Docstring shown to the model as the tool description."""
    params = {"userId": "me", ...}
    return await run_gws("gmail", "<resource>", "<method>", "--params", json.dumps(params))
```

Use `gws gmail --help` or `gws_schema` (not yet implemented) to discover available subcommands and their accepted params.

## Key Dependency: `gws` CLI

The server is a thin wrapper — almost all logic lives in the `gws` binary. `GWS_BIN = shutil.which("gws")` resolves the path at import time; the server logs a warning but does not crash if `gws` is absent (calls will fail at runtime).

**Before implementing any new tool**, run the relevant help command to see exact params:

```bash
gws gmail --help                        # available subcommands and helpers
gws gmail users messages <method> --help  # params for a specific method
gws schema gmail.users.messages.get     # full API schema for a method
```

Notable `gws gmail` features to be aware of:
- **Helper commands** (`+send`, `+read`, `+reply`, `+reply-all`, `+forward`, `+triage`, `+watch`) — high-level wrappers that handle threading, body extraction, etc. Prefer these over raw API calls where they fit.
- **`gws schema <service.resource.method>`** — prints the full JSON schema for any API method, useful for discovering available params and response shapes.