"""End-to-end tests against the live Gmail API via the gws CLI.

Requires valid gws credentials (`gws auth login`).
Run with: .venv/bin/pytest tests/
"""
import pytest
from server import gmail_list_messages, gmail_get_message, gmail_get_thread, gmail_modify_messages, gmail_trash_message

# Replace these with real IDs from your own inbox before running tests.
# Run: python -c "import asyncio; from server import gmail_list_messages; import json; r = asyncio.run(gmail_list_messages(max_results=1, include_metadata=False)); print(r['messages'][0]['id'])"
KNOWN_MESSAGE_ID = "REPLACE_WITH_YOUR_MESSAGE_ID"
KNOWN_THREAD_ID = "REPLACE_WITH_YOUR_THREAD_ID"


@pytest.mark.asyncio
async def test_unread_inbox_with_metadata():
    result = await gmail_list_messages(unread=True, label="inbox", max_results=3)

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"
    assert "messages" in result

    for msg in result["messages"]:
        assert "id" in msg
        assert "threadId" in msg
        assert "subject" in msg
        assert "from" in msg
        assert "date" in msg
        assert "snippet" in msg
        assert "labels" in msg
        assert "UNREAD" in msg["labels"]
        assert "INBOX" in msg["labels"]
        assert not any(lbl.startswith("Label_") for lbl in msg["labels"]), "labels should be resolved names, not IDs"


@pytest.mark.asyncio
async def test_free_text_search_with_metadata():
    result = await gmail_list_messages(query="has:attachment", max_results=3)

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"
    assert "messages" in result

    for msg in result["messages"]:
        assert "id" in msg
        assert "subject" in msg
        assert "from" in msg
        assert "snippet" in msg


@pytest.mark.asyncio
async def test_ids_only_skips_metadata():
    result = await gmail_list_messages(unread=True, max_results=5, include_metadata=False)

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"
    assert "messages" in result

    for msg in result["messages"]:
        assert "id" in msg
        assert "threadId" in msg
        assert "subject" not in msg
        assert "snippet" not in msg


@pytest.mark.asyncio
async def test_filters_combine_with_and():
    """unread + label + query should all apply together."""
    result = await gmail_list_messages(unread=True, label="inbox", query="has:attachment", max_results=5)

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"

    for msg in result.get("messages", []):
        assert "UNREAD" in msg["labels"]
        assert "INBOX" in msg["labels"]
        assert not any(lbl.startswith("Label_") for lbl in msg["labels"]), "labels should be resolved names, not IDs"


@pytest.mark.asyncio
async def test_get_message_metadata():
    result = await gmail_get_message(KNOWN_MESSAGE_ID, format="metadata")

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"
    for field in ("id", "threadId", "subject", "from", "to", "date", "snippet", "labels"):
        assert field in result, f"Missing field: {field}"
    assert result["id"] == KNOWN_MESSAGE_ID


@pytest.mark.asyncio
async def test_get_message_full():
    result = await gmail_get_message(KNOWN_MESSAGE_ID, format="full")

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"
    assert result["id"] == KNOWN_MESSAGE_ID
    for field in ("id", "threadId", "subject", "from", "to", "date", "labels", "body"):
        assert field in result, f"Missing field: {field}"
    assert "body_html" not in result
    assert "references" not in result
    assert "message_id" not in result
    assert "reply_to" in result
    assert len(result["body"]) > 0


@pytest.mark.asyncio
async def test_get_message_minimal():
    result = await gmail_get_message(KNOWN_MESSAGE_ID, format="minimal")

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"
    assert result["id"] == KNOWN_MESSAGE_ID
    assert "threadId" in result
    assert "snippet" in result
    assert "payload" not in result


@pytest.mark.asyncio
async def test_empty_results_are_valid():
    """A search that returns no messages should still return a valid response."""
    result = await gmail_list_messages(query="subject:zzz_no_such_email_xqz", max_results=5)

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"


@pytest.mark.asyncio
async def test_get_thread():
    result = await gmail_get_thread(KNOWN_THREAD_ID)

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"
    assert result["threadId"] == KNOWN_THREAD_ID
    assert "messages" in result
    assert len(result["messages"]) >= 1

    for msg in result["messages"]:
        for field in ("id", "threadId", "subject", "from", "date", "snippet", "labels"):
            assert field in msg, f"Missing field: {field}"
        assert not any(lbl.startswith("Label_") for lbl in msg["labels"])


@pytest.mark.asyncio
async def test_modify_messages_mark_read_and_restore():
    """Mark a message as read then restore unread — leaves state unchanged."""
    result = await gmail_modify_messages([KNOWN_MESSAGE_ID], mark_read=True)

    assert isinstance(result, dict), f"Expected dict, got: {result}"
    assert "error" not in result, f"API error: {result}"
    assert result.get("ok") is True
    assert result.get("modified") == 1

    # Restore to unread
    restore = await gmail_modify_messages([KNOWN_MESSAGE_ID], add_labels=["UNREAD"])
    assert restore.get("ok") is True


@pytest.mark.asyncio
async def test_modify_messages_batch():
    """Batch modify accepts multiple IDs."""
    result = await gmail_list_messages(unread=True, max_results=3, include_metadata=False)
    ids = [m["id"] for m in result.get("messages", [])]

    if not ids:
        pytest.skip("No unread messages available for batch test")

    batch_result = await gmail_modify_messages(ids, mark_read=True)
    assert batch_result.get("ok") is True
    assert batch_result.get("modified") == len(ids)

    # Restore
    await gmail_modify_messages(ids, add_labels=["UNREAD"])
