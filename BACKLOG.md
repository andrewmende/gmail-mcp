# Backlog

## Gmail Tools

- [x] Typed filter params for `gmail_list_messages` — add `unread: bool`, `label: str` args and build the Gmail query string server-side instead of requiring the agent to write raw query syntax
- [x] Update `gmail_list_messages` to fetch metadata (subject/from/date/snippet) for each result in parallel via `asyncio.gather`; add `include_metadata: bool = True` param to allow skipping for performance at high `max_results`
- [x] `gmail_get_message(id, format="metadata"|"full"|"minimal")` — fetch a single message; `metadata` returns subject/sender/date/snippet without the full body
- [x] `gmail_get_thread(thread_id)` — return all messages in a thread in order so the agent can reason about conversations without stitching individual messages together

## Gmail Actions

- [x] `gmail_modify_messages(ids, mark_read, archive, add_labels, remove_labels)` — batch label operations on 1–1000 messages; `mark_read` removes UNREAD, `archive` removes INBOX, `add_labels`/`remove_labels` accept label names resolved to IDs internally via `_fetch_label_map()`; uses `batchModify` under the hood
- [x] `gmail_trash_message(id)` — move a single message to trash (reversible); kept separate from modify because it is a distinct endpoint and a distinct semantic action
