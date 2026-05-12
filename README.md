# gmail-mcp

A Gmail MCP server built for agent usage. Tools are designed so an agent can triage, read, and act on email with minimal round-trips — metadata fetches run in parallel, labels are resolved to human-readable names, and actions accept batches of up to 1000 messages.

## Tools

### Reading

| Tool | What it returns |
|------|----------------|
| `gmail_list_messages` | List of messages with subject, sender, date, snippet, and labels — all fetched in parallel |
| `gmail_get_message` | Single message in `metadata` (headers + snippet), `full` (+ decoded plain-text body), or `minimal` format |
| `gmail_get_thread` | Full conversation in chronological order, each message shaped like `metadata` |

### Acting

| Tool | What it does |
|------|-------------|
| `gmail_modify_messages` | Mark as read, archive, add/remove labels — batch up to 1000 messages in one call |
| `gmail_trash_message` | Move to trash (recoverable for 30 days) |

All tools return structured JSON. Errors come back as `{"error": "...", "returncode": N}` so an agent can check and recover without parsing strings.

## Agent workflow examples

**Triage unread inbox:**
```
1. gmail_list_messages(unread=True, label="inbox", max_results=20)
   → returns subject/sender/snippet for all 20 in one call

2. gmail_modify_messages(ids=[...newsletters...], mark_read=True, archive=True)
   → batch-archives in one call
```

**Read and respond to a support thread:**
```
1. gmail_list_messages(query="from:support@example.com", unread=True)
   → find the message ID

2. gmail_get_thread(thread_id)
   → read the full conversation in order before replying

3. gmail_get_message(id, format="full")
   → get the plain-text body of the latest message
```

## Setup

### Prerequisites

**Python 3.11+** and the [Google Workspace CLI](https://github.com/googleworkspace/cli):

```bash
npm install -g @googleworkspace/cli
gws auth login
```

### Install

```bash
git clone <repo>
cd gmail-mcp
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Add to Claude Code

Add to `~/.claude/mcp.json` (global) or `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "/path/to/gmail-mcp/.venv/bin/python",
      "args": ["/path/to/gmail-mcp/server.py"]
    }
  }
}
```

### Run tests

Update `KNOWN_MESSAGE_ID` and `KNOWN_THREAD_ID` in `tests/test_gmail.py` with IDs from your own inbox (see the comment in that file for a one-liner), then:

```bash
.venv/bin/pytest tests/ -v
```

## Architecture

A thin [FastMCP](https://github.com/jlowin/fastmcp) wrapper around the `gws` CLI. Each tool shells out to `gws` via `asyncio.create_subprocess_exec`, parses the JSON response, and shapes it for agent consumption. Parallel requests use `asyncio.gather` — listing 10 messages with metadata fires 10 concurrent `gws` calls rather than 10 sequential ones.
