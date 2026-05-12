import asyncio
import json
import shutil
import logging

from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gws-mcp")

GWS_BIN = shutil.which("gws")
if not GWS_BIN:
    logger.warning("gws not found on PATH. Install with: npm install -g @googleworkspace/cli")


async def run_gws(
    *args: str,
    input_data: str | None = None,
    page_all: bool = False,
    page_limit: int | None = None,
    page_delay: int | None = None,
    output_format: str | None = None,
    dry_run: bool = False,
    upload_path: str | None = None,
    output_path: str | None = None,
) -> dict | str:
    """Execute a gws CLI command and return the result."""
    cmd = [GWS_BIN or "gws", *args]
    if page_all:
        cmd.append("--page-all")
    if page_limit is not None:
        cmd.extend(["--page-limit", str(page_limit)])
    if page_delay is not None:
        cmd.extend(["--page-delay", str(page_delay)])
    if output_format:
        cmd.extend(["--format", output_format])
    if dry_run:
        cmd.append("--dry-run")
    if upload_path:
        cmd.extend(["--upload", upload_path])
    if output_path:
        cmd.extend(["-o", output_path])

    logger.info(f"Running: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE if input_data else None,
    )
    stdout, stderr = await proc.communicate(input=input_data.encode() if input_data else None)
    output = stdout.decode().strip()
    err = stderr.decode().strip()

    if proc.returncode != 0:
        return {"error": err or output or f"gws exited with code {proc.returncode}", "returncode": proc.returncode}
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output if output else {"message": "OK", "stderr": err}


mcp = FastMCP(
    name="gws-mcp",
    instructions=(
        "Google Workspace MCP Server providing Gmail tools. "
        "All responses are structured JSON from the Google Workspace APIs. "
        "Errors are returned as {\"error\": \"...\", \"returncode\": N} — check for this key before using a result. "
        "Typical read workflow: gmail_list_messages → gmail_get_message(format='metadata') → gmail_get_message(format='full') if body needed. "
        "For conversations use gmail_get_thread. "
        "Action tools: gmail_modify_messages (mark read, archive, apply/remove labels — batch up to 1000), gmail_trash_message (reversible delete)."
    ),
)

# ========================== GMAIL ==========================


async def _fetch_label_map() -> dict[str, str]:
    """Return a mapping of label ID → label name for the authenticated user."""
    result = await run_gws("gmail", "users", "labels", "list", "--params", json.dumps({"userId": "me"}))
    if not isinstance(result, dict) or "labels" not in result:
        return {}
    return {lbl["id"]: lbl["name"] for lbl in result["labels"]}


def _resolve_labels(label_ids: list, label_map: dict[str, str]) -> list[str]:
    return [label_map.get(lid, lid) for lid in label_ids]


@mcp.tool()
async def gmail_get_message(id: str, format: str = "metadata") -> dict | str:
    """Fetch a single Gmail message by ID.

    Formats:
    - "metadata": subject, from, to, cc, date, snippet, labels — no body (fast)
    - "full": all metadata plus decoded plain-text body (uses +read helper)
    - "minimal": id, threadId, labels, snippet only (fastest)

    Use "metadata" to check headers before deciding whether to fetch the full body.
    Use "full" when you need to read or summarize the message content.

    Args:
        id: The Gmail message ID (from gmail_list_messages results).
        format: One of "metadata" (default), "full", or "minimal".
    """
    if format == "full":
        raw, minimal, label_map = await asyncio.gather(
            run_gws("gmail", "+read", "--id", id, "--headers", "--format", "json"),
            run_gws("gmail", "users", "messages", "get", "--params", json.dumps({"userId": "me", "id": id, "format": "minimal"})),
            _fetch_label_map(),
        )
        if not isinstance(raw, dict) or "error" in raw:
            return raw
        label_ids = minimal.get("labelIds", []) if isinstance(minimal, dict) else []
        return {
            "id": id,
            "threadId": raw.get("thread_id", ""),
            "subject": raw.get("subject", ""),
            "from": raw.get("from", ""),
            "to": raw.get("to", ""),
            "reply_to": raw.get("reply_to", ""),
            "cc": raw.get("cc", ""),
            "date": raw.get("date", ""),
            "labels": _resolve_labels(label_ids, label_map),
            "body": raw.get("body_text", ""),
        }

    params: dict = {"userId": "me", "id": id, "format": format}
    if format == "metadata":
        params["metadataHeaders"] = ["From", "To", "Subject", "Date", "Cc"]

    result, label_map = await asyncio.gather(
        run_gws("gmail", "users", "messages", "get", "--params", json.dumps(params)),
        _fetch_label_map(),
    )

    if not isinstance(result, dict) or "error" in result:
        return result

    if format == "metadata":
        headers = {h["name"]: h["value"] for h in result.get("payload", {}).get("headers", [])}
        return {
            "id": result["id"],
            "threadId": result["threadId"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "cc": headers.get("Cc", ""),
            "date": headers.get("Date", ""),
            "snippet": result.get("snippet", ""),
            "labels": _resolve_labels(result.get("labelIds", []), label_map),
        }

    # minimal
    return {
        "id": result["id"],
        "threadId": result["threadId"],
        "snippet": result.get("snippet", ""),
        "labels": _resolve_labels(result.get("labelIds", []), label_map),
    }


@mcp.tool()
async def gmail_list_messages(
    query: str = "",
    max_results: int = 10,
    unread: bool = False,
    label: str = "",
    include_metadata: bool = True,
) -> dict | str:
    """List Gmail messages matching the given filters.

    By default fetches subject, sender, date, and snippet for each result in parallel.
    Set include_metadata=False to return IDs only — faster at high max_results.
    Filters are combined with AND — all specified conditions must match.

    Returns a list of messages with fields: id, threadId, subject, from, date, snippet, labels.
    On error returns {"error": "...", "returncode": N}.

    Args:
        query: Free-text Gmail search query (e.g. 'from:user@example.com', 'subject:hello', 'has:attachment').
        max_results: Maximum number of messages to return (1–500, default 10).
        unread: Restrict to unread messages only.
        label: Restrict to a label by name (e.g. 'inbox', 'sent', 'starred', or a custom label name).
        include_metadata: If True (default), enrich each result with subject/from/date/snippet.
    """
    parts = []
    if query:
        parts.append(query)
    if unread:
        parts.append("is:unread")
    if label:
        parts.append(f"label:{label}")

    params = {"maxResults": max_results, "userId": "me"}
    if parts:
        params["q"] = " ".join(parts)

    result, label_map = await asyncio.gather(
        run_gws("gmail", "users", "messages", "list", "--params", json.dumps(params)),
        _fetch_label_map(),
    )

    if not include_metadata or not isinstance(result, dict) or "messages" not in result:
        return result

    async def fetch_metadata(msg_id: str) -> dict:
        meta_params = {
            "userId": "me",
            "id": msg_id,
            "format": "metadata",
            "metadataHeaders": ["From", "Subject", "Date"],
        }
        return await run_gws("gmail", "users", "messages", "get", "--params", json.dumps(meta_params))

    metadata = await asyncio.gather(*[fetch_metadata(m["id"]) for m in result["messages"]])

    enriched = []
    for msg, meta in zip(result["messages"], metadata):
        if isinstance(meta, dict) and "error" not in meta:
            headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
            enriched.append({
                "id": msg["id"],
                "threadId": msg["threadId"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": meta.get("snippet", ""),
                "labels": _resolve_labels(meta.get("labelIds", []), label_map),
            })
        else:
            enriched.append(msg)

    result["messages"] = enriched
    return result


@mcp.tool()
async def gmail_get_thread(thread_id: str) -> dict | str:
    """Fetch all messages in a Gmail thread in chronological order.

    Returns the full conversation with each message shaped the same as
    gmail_get_message(format='metadata'): id, subject, from, to, date, snippet, labels.
    Use this instead of fetching individual messages when you need to understand
    a conversation in context.

    Args:
        thread_id: The thread ID (available on every message as the threadId field).
    """
    params = {
        "userId": "me",
        "id": thread_id,
        "format": "metadata",
        "metadataHeaders": ["From", "To", "Subject", "Date"],
    }
    result, label_map = await asyncio.gather(
        run_gws("gmail", "users", "threads", "get", "--params", json.dumps(params)),
        _fetch_label_map(),
    )

    if not isinstance(result, dict) or "error" in result:
        return result

    messages = []
    for msg in result.get("messages", []):
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        messages.append({
            "id": msg["id"],
            "threadId": msg["threadId"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
            "labels": _resolve_labels(msg.get("labelIds", []), label_map),
        })

    return {"threadId": thread_id, "messages": messages}


@mcp.tool()
async def gmail_modify_messages(
    ids: list[str],
    mark_read: bool = False,
    archive: bool = False,
    add_labels: list[str] = [],
    remove_labels: list[str] = [],
) -> dict | str:
    """Modify labels on one or more Gmail messages in a single batch operation.

    Common actions:
    - Mark as read: mark_read=True
    - Archive: archive=True
    - Apply a label: add_labels=["label name"]
    - Remove a label: remove_labels=["label name"]
    Multiple actions can be combined in one call.

    Args:
        ids: List of message IDs to modify (1–1000).
        mark_read: If True, remove the UNREAD label.
        archive: If True, remove the INBOX label.
        add_labels: Label names to add (e.g. ['Action Required', 'starred']).
        remove_labels: Label names to remove.
    """
    label_map = await _fetch_label_map()
    name_to_id = {v: k for k, v in label_map.items()}

    def resolve_to_ids(names: list[str]) -> list[str]:
        return [name_to_id.get(n, n) for n in names]

    add_ids = resolve_to_ids(add_labels)
    remove_ids = resolve_to_ids(remove_labels)

    if mark_read:
        remove_ids.append("UNREAD")
    if archive:
        remove_ids.append("INBOX")

    body: dict = {"ids": ids}
    if add_ids:
        body["addLabelIds"] = add_ids
    if remove_ids:
        body["removeLabelIds"] = remove_ids

    result = await run_gws(
        "gmail", "users", "messages", "batchModify",
        "--params", json.dumps({"userId": "me"}),
        "--json", json.dumps(body),
    )

    if isinstance(result, dict) and "error" in result:
        return result
    return {"ok": True, "modified": len(ids)}


@mcp.tool()
async def gmail_trash_message(id: str) -> dict | str:
    """Move a Gmail message to the trash (recoverable from Trash for 30 days).

    Prefer this over permanent deletion — trashed messages can be restored.
    To mark as read or archive instead, use gmail_modify_messages.

    Args:
        id: The message ID to trash.
    """
    result = await run_gws(
        "gmail", "users", "messages", "trash",
        "--params", json.dumps({"userId": "me", "id": id}),
    )

    if not isinstance(result, dict) or "error" in result:
        return result
    return {"ok": True, "id": id, "labels": _resolve_labels(result.get("labelIds", []), await _fetch_label_map())}


if __name__ == "__main__":
    mcp.run()
