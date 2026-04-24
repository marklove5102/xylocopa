"""Display file writer — writes per-agent JSONL files for the frontend.

Each agent gets a `data/display/{agent_id}.jsonl` file containing one JSON
line per message, ordered by display_seq.  The frontend reads these files
to render the chat history without querying the DB.

Design:
    - Display file is append-only (rebuild appends new seq block)
    - File write happens BEFORE DB commit (safe: if DB fails, display_seq
      stays NULL, next flush retries; frontend deduplicates by id)
    - File writes use fcntl.flock to prevent interleaved lines

Functions:
    flush_agent            — append undisplayed messages to the display file
    update_last            — append a replacement line for a streaming update
    flush_queued_entry     — append a `_queued` line for a pre-delivery msg
    update_queued_entry    — append a `_queued + _replace` line
    update_after_metadata_change — branch on display_seq: queued vs delivered
    mark_deleted           — append a `{_deleted: true}` tombstone
    promote_to_delivered   — atomically tombstone queued + write delivered
    rebuild_agent          — rebuild the display file (append-only: new seq block)
    delete_agent           — remove the display file
    startup_rebuild_all    — rebuild all active agents on server startup
"""

import fcntl
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

from sqlalchemy import func, text

from config import _resolve
from database import SessionLocal
from models import Agent, AgentStatus, Message, MessageRole, MessageStatus

logger = logging.getLogger("orchestrator.display_writer")

DISPLAY_DIR = _resolve("data/display")


# ---- Pre-delivery in-memory index ----
#
# Per the Phase 1 plan in docs/REFACTOR_PREDELIVERY_PLAN.md, pre-delivery
# messages (queued / scheduled / cancelled) are eventually going to live
# exclusively in the per-agent display file (no DB row). Until a message is
# promoted to "sent", the authoritative view of it lives here in memory
# (backed by the JSONL file on disk so it survives restart).
#
# `_predelivery_index[agent_id][msg_id] = entry_dict` — latest state of each
# pre-delivery entry. Mutations to the index are guarded by
# `_predelivery_lock` (a threading.Lock; the existing fcntl.flock on the
# file only guards multi-process append ordering, not in-process index
# writes).
#
# The index is built lazily per agent on first access (see
# `_ensure_index_loaded`) or eagerly during `rebuild_agent` /
# `startup_rebuild_all`.
_predelivery_index: dict[str, dict[str, dict]] = {}
_predelivery_index_ready: set[str] = set()
_predelivery_lock = threading.Lock()


_VALID_PRE_SOURCES = {"web", "task", "plan_continue"}
_VALID_PRE_STATUSES = {"queued", "scheduled", "cancelled"}


_ATTACHMENT_TAG_RE = re.compile(r'\n?\[Attached file: [^\]]+\]')
_ATTACHMENT_PATH_RE = re.compile(r'\[Attached file: ([^\]]+)\]')
_STOP_NOTE_RE = re.compile(r'^(Task dropped|Redo)\s*—\s*(.*)', re.DOTALL)
_TASK_NOTIFICATION_FIELD_RE = {
    f: re.compile(rf'<{f}>([\s\S]*?)</{f}>') for f in ('status', 'summary', 'result')
}


def _display_path(agent_id: str) -> str:
    """Return path: data/display/{agent_id}.jsonl"""
    return os.path.join(DISPLAY_DIR, f"{agent_id}.jsonl")


def transform_for_display(role: str | None, content: str | None,
                          metadata: dict | None) -> tuple[str | None, dict | None]:
    """Apply display transformations so the JSONL/API content matches what
    the UI should render without further frontend processing.

    Returns (content, metadata) — both may be modified copies.

    Transformations:
    - display_content override (e.g. retry agent first message)
    - USER messages: strip [Attached file: ...] tags, store paths in metadata
    - SYSTEM stop notes: strip prefix, store stop_action in metadata
    - Task notifications: parse XML into metadata.task_notification
    """
    if content is None:
        return content, metadata

    # 1. display_content override (already set by _prepare_dispatch)
    if isinstance(metadata, dict) and "display_content" in metadata:
        content = metadata["display_content"]

    # 2. USER: strip attachment tags, store paths
    if role == "USER":
        paths = _ATTACHMENT_PATH_RE.findall(content)
        if paths:
            content = _ATTACHMENT_TAG_RE.sub('', content).strip()
            metadata = dict(metadata) if metadata else {}
            metadata['attachments'] = paths

    # 3. SYSTEM stop notes: "Task dropped — reason" / "Redo — reason"
    if role == "SYSTEM":
        m = _STOP_NOTE_RE.match(content)
        if m:
            metadata = dict(metadata) if metadata else {}
            metadata['stop_action'] = 'dropped' if m.group(1) == 'Task dropped' else 'redo'
            content = m.group(2)

    # 4. Task notifications: parse XML fields into metadata
    if content.lstrip().startswith('<task-notification>'):
        tn = {}
        for field, regex in _TASK_NOTIFICATION_FIELD_RE.items():
            fm = regex.search(content)
            if fm:
                tn[field] = fm.group(1).strip()
        if tn:
            metadata = dict(metadata) if metadata else {}
            metadata['task_notification'] = tn

    return content, metadata


def _prepare_display_fields(msg: Message) -> tuple[str | None, str | None, dict | None]:
    """Parse meta_json, resolve tool_use_id, and apply display transforms.

    Returns (role_val, content, metadata).
    """
    metadata = None
    if msg.meta_json:
        try:
            metadata = json.loads(msg.meta_json)
        except (json.JSONDecodeError, ValueError):
            metadata = None

    # Extract tool_use_id from metadata if present, or use direct column
    tool_use_id = getattr(msg, "tool_use_id", None)
    if not tool_use_id and isinstance(metadata, dict):
        for item in metadata.get("interactive", []):
            if "tool_use_id" in item:
                tool_use_id = item["tool_use_id"]
                break

    role_val = msg.role.value if msg.role else None
    content, metadata = transform_for_display(role_val, msg.content, metadata)

    # Stash resolved tool_use_id back onto msg attr for serializers without
    # re-running the extraction. Non-persisting — just a local attribute.
    msg._resolved_tool_use_id = tool_use_id
    return role_val, content, metadata


def _serialize_message(msg: Message, seq: int, replace: bool = False) -> str:
    """Serialize a delivered Message to a JSON line for the display file.

    Fields: id, seq, role, kind, content, source, status, metadata,
    tool_use_id, created_at, completed_at, delivered_at.
    If replace=True, add "_replace": true.
    """
    role_val, content, metadata = _prepare_display_fields(msg)
    tool_use_id = getattr(msg, "_resolved_tool_use_id", None)

    obj = {
        "id": msg.id,
        "seq": seq,
        "role": role_val,
        "kind": msg.kind if hasattr(msg, "kind") else "message",
        "content": content,
        "source": msg.source,
        "status": msg.status.value if msg.status else None,
        "metadata": metadata,
        "tool_use_id": tool_use_id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "completed_at": msg.completed_at.isoformat() if msg.completed_at else None,
        "delivered_at": msg.delivered_at.isoformat() if msg.delivered_at else None,
    }
    if replace:
        obj["_replace"] = True

    return json.dumps(obj, separators=(",", ":"))


def _serialize_queued(msg: Message, replace: bool = False) -> str:
    """Serialize a pre-delivery (queued) Message as a `_queued` JSONL line.

    No `seq` field — queued entries are not part of the main partition.
    Carries the same fields the frontend's queued-bubble render consumes
    from the DB fallback MessageOut: id, role, content, status, source,
    metadata, created_at, scheduled_at, delivered_at (null), tool_use_id,
    kind.
    """
    role_val, content, metadata = _prepare_display_fields(msg)
    tool_use_id = getattr(msg, "_resolved_tool_use_id", None)

    obj = {
        "id": msg.id,
        "_queued": True,
        "role": role_val,
        "kind": msg.kind if hasattr(msg, "kind") else None,
        "content": content,
        "source": msg.source,
        "status": msg.status.value if msg.status else None,
        "metadata": metadata,
        "tool_use_id": tool_use_id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "scheduled_at": msg.scheduled_at.isoformat() if msg.scheduled_at else None,
        "completed_at": msg.completed_at.isoformat() if msg.completed_at else None,
        "delivered_at": msg.delivered_at.isoformat() if msg.delivered_at else None,
    }
    if replace:
        obj["_replace"] = True
    return json.dumps(obj, separators=(",", ":"))


def _serialize_tombstone(message_id: str) -> str:
    """Serialize a tombstone marker removing `message_id` from display."""
    return json.dumps({"id": message_id, "_deleted": True}, separators=(",", ":"))


def _write_locked(path: str, lines: list[str]):
    """Append lines to file with exclusive flock to prevent interleaving."""
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            for line in lines:
                f.write(line + "\n")
            f.flush()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def flush_agent(agent_id: str):
    """Append all undisplayed messages (display_seq IS NULL) to the display file.

    Order of operations (file-first for safety):
    1. Query messages WHERE display_seq IS NULL
    2. Assign display_seq in memory
    3. Write to file (with flock)
    4. Commit display_seq to DB

    If file write fails → display_seq stays NULL → next flush retries.
    If DB commit fails → display_seq reverts to NULL → next flush retries,
    file has duplicate lines but frontend deduplicates by id.
    """
    db = SessionLocal()
    try:
        _MAX_TS = datetime(9999, 1, 1, tzinfo=timezone.utc)
        undisplayed = (
            db.query(Message)
            .filter(
                Message.agent_id == agent_id,
                Message.display_seq.is_(None),
                # Skip undelivered user messages — they enter the display
                # file only after delivered_at is set (by UserPromptSubmit
                # hook), so they sort after the preceding agent response.
                ~(
                    (Message.role == MessageRole.USER)
                    & (Message.delivered_at.is_(None))
                ),
            )
            .all()
        )

        def _sort_key(msg: Message) -> datetime:
            """Ordering: delivered_at if available, else created_at."""
            ts = msg.delivered_at or msg.created_at or _MAX_TS
            # Ensure tz-aware for consistent comparison (some DB rows
            # may have naive timestamps from older code paths).
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts

        undisplayed.sort(key=_sort_key)
        if not undisplayed:
            return

        # Get current max display_seq
        max_seq = db.query(func.max(Message.display_seq)).filter(
            Message.agent_id == agent_id,
        ).scalar()
        next_seq = (max_seq or 0) + 1

        # Ensure directory exists
        os.makedirs(DISPLAY_DIR, exist_ok=True)

        path = _display_path(agent_id)
        lines = []
        for msg in undisplayed:
            msg.display_seq = next_seq
            lines.append(_serialize_message(msg, next_seq))
            next_seq += 1

        # Write file FIRST — if this fails, display_seq stays uncommitted
        try:
            _write_locked(path, lines)
        except OSError:
            # File write failed — reset display_seq so next flush retries
            for msg in undisplayed:
                msg.display_seq = None
            db.expire_all()
            logger.exception("File write failed for agent %s display file", agent_id[:8])
            return

        # Commit display_seq to DB — file is already written
        db.commit()

        logger.debug(
            "Flushed %d messages to display file for agent %s (seq %d..%d)",
            len(undisplayed), agent_id[:8],
            undisplayed[0].display_seq, undisplayed[-1].display_seq,
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to flush display file for agent %s", agent_id[:8])
    finally:
        db.close()


def update_last(agent_id: str, message_id: str):
    """Append a replacement line for a message whose content/status changed.

    Used for:
    - Streaming content updates (agent response growing)
    - Delivery status updates (delivered_at set after promotion)

    If the message already has display_seq, appends with _replace=True so
    the frontend overwrites the stale entry.  If display_seq is None (message
    not yet in the display file), falls through to flush_agent which assigns
    a seq and writes the message for the first time.
    """
    _needs_flush = False
    db = SessionLocal()
    try:
        msg = db.get(Message, message_id)
        if not msg or msg.agent_id != agent_id:
            return
        if msg.display_seq is None:
            _needs_flush = True
        else:
            os.makedirs(DISPLAY_DIR, exist_ok=True)
            path = _display_path(agent_id)
            line = _serialize_message(msg, msg.display_seq, replace=True)
            _write_locked(path, [line])
    except Exception:
        logger.exception(
            "Failed to update display file for agent %s msg %s",
            agent_id[:8], message_id,
        )
    finally:
        db.close()

    if _needs_flush:
        flush_agent(agent_id)


def flush_queued_entry(agent_id: str, message_id: str):
    """Append a `_queued` line for a pre-delivery message.

    Precondition: caller committed a Message row with `display_seq IS NULL`.
    Raises RuntimeError if the precondition is violated — do not catch; the
    caller is buggy and the failure must surface, not be silently absorbed.
    """
    db = SessionLocal()
    try:
        msg = db.get(Message, message_id)
        if not msg:
            raise RuntimeError(
                f"flush_queued_entry: msg {message_id} not found in DB "
                "(caller must commit before calling)"
            )
        if msg.agent_id != agent_id:
            raise RuntimeError(
                f"flush_queued_entry: msg {message_id} belongs to agent "
                f"{msg.agent_id}, not {agent_id}"
            )
        if msg.display_seq is not None:
            raise RuntimeError(
                f"flush_queued_entry contract violation: msg {message_id} "
                f"already has display_seq={msg.display_seq}. This function "
                "is only for pre-delivery messages."
            )

        os.makedirs(DISPLAY_DIR, exist_ok=True)
        path = _display_path(agent_id)
        line = _serialize_queued(msg)
        _write_locked(path, [line])
    finally:
        db.close()


def update_queued_entry(agent_id: str, message_id: str):
    """Append a `_queued + _replace` line updating a pre-delivery message.

    Used for content edits, PENDING→QUEUED transitions, and interactive-card
    metadata changes before delivery. Caller must have committed DB first.
    Raises RuntimeError if the message has already been promoted — that
    indicates the caller should have taken the post-delivery `update_last`
    branch instead.
    """
    db = SessionLocal()
    try:
        msg = db.get(Message, message_id)
        if not msg:
            raise RuntimeError(
                f"update_queued_entry: msg {message_id} not found in DB"
            )
        if msg.agent_id != agent_id:
            raise RuntimeError(
                f"update_queued_entry: msg {message_id} belongs to agent "
                f"{msg.agent_id}, not {agent_id}"
            )
        if msg.display_seq is not None:
            raise RuntimeError(
                f"update_queued_entry contract violation: msg {message_id} "
                f"already promoted (display_seq={msg.display_seq}). Caller "
                "should branch on display_seq and use update_last for "
                "post-delivery updates."
            )

        os.makedirs(DISPLAY_DIR, exist_ok=True)
        path = _display_path(agent_id)
        line = _serialize_queued(msg, replace=True)
        _write_locked(path, [line])
    finally:
        db.close()


def update_after_metadata_change(agent_id: str, message_id: str):
    """Append a replacement line after the caller committed a metadata
    (meta_json) patch on a message that may be pre- or post-delivery.

    Branches on `display_seq`:
      - NULL  → `update_queued_entry` (the `_queued + _replace` line)
      - set   → `update_last`          (a regular `_replace` line)

    Caller must have committed the DB change before calling. Picking the
    wrong branch would violate the writer contracts (e.g. a `_replace`
    line with no preceding regular entry, or a `_queued` line on an
    already-promoted message — which `update_queued_entry` now raises on
    per the "fail loudly" policy).

    Silently no-ops if the row has been deleted between commit and call.
    """
    db = SessionLocal()
    try:
        msg = db.get(Message, message_id)
        if msg is None:
            # Defensive: row deleted between caller's commit and this call.
            return
        has_seq = msg.display_seq is not None
    finally:
        db.close()

    if has_seq:
        update_last(agent_id, message_id)
    else:
        update_queued_entry(agent_id, message_id)


def mark_deleted(agent_id: str, message_id: str):
    """Append a tombstone marker. Readers drop any entry whose winning line
    has `_deleted: true`. No DB interaction — semantics are caller's choice.
    """
    try:
        os.makedirs(DISPLAY_DIR, exist_ok=True)
        path = _display_path(agent_id)
        _write_locked(path, [_serialize_tombstone(message_id)])
    except Exception:
        logger.exception(
            "Failed to write tombstone for agent %s msg %s",
            agent_id[:8], message_id,
        )


def promote_to_delivered(agent_id: str, message_id: str):
    """Move a queued entry to the delivered partition.

    Fresh promotion path (msg.display_seq is None): under a single flock,
    append tombstone `{id, _deleted: true}` + the full regular entry with a
    freshly allocated `display_seq`; then commit `display_seq` on the DB row.

    Already-promoted path (msg.display_seq is set): log a warning and
    degrade to `update_last`. Legitimate cause is a startup rebuild that
    re-flushed an already-delivered row before sync had a chance to link
    its jsonl_uuid — on the next sync wake, sync tries to promote again
    and must not kill the loop. Keeping this function idempotent is the
    robustness net for "hook-wrote-delivered-at-before-restart" races.
    """
    db = SessionLocal()
    try:
        msg = db.get(Message, message_id)
        if not msg:
            raise RuntimeError(
                f"promote_to_delivered: msg {message_id} not found in DB"
            )
        if msg.agent_id != agent_id:
            raise RuntimeError(
                f"promote_to_delivered: msg {message_id} belongs to agent "
                f"{msg.agent_id}, not {agent_id}"
            )
        if msg.display_seq is not None:
            logger.warning(
                "promote_to_delivered: msg %s already has display_seq=%d — "
                "degrading to update_last. Expected on post-restart UUID "
                "catch-up; investigate if frequent in steady state.",
                message_id, msg.display_seq,
            )
            db.close()
            update_last(agent_id, message_id)
            return

        os.makedirs(DISPLAY_DIR, exist_ok=True)
        path = _display_path(agent_id)

        # Allocate next display_seq using the same rule as flush_agent.
        max_seq = db.query(func.max(Message.display_seq)).filter(
            Message.agent_id == agent_id,
        ).scalar()
        next_seq = (max_seq or 0) + 1

        tombstone = _serialize_tombstone(message_id)
        delivered_line = _serialize_message(msg, next_seq)

        # Single flock covers tombstone + delivered entry so readers never
        # observe the id present in both partitions simultaneously.
        _write_locked(path, [tombstone, delivered_line])

        msg.display_seq = next_seq
        db.commit()
    finally:
        try:
            db.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Pre-delivery API (Phase 1 of docs/REFACTOR_PREDELIVERY_PLAN.md)
# ---------------------------------------------------------------------------
#
# These functions maintain the in-memory `_predelivery_index` and append
# matching JSONL lines to the per-agent display file. They do NOT touch the
# DB — a pre-delivery entry has no DB row by design. The moment a message is
# sent, `predelivery_promote_to_sent` transfers ownership from file-only to
# file+DB. See the plan for the full state machine.
#
# All functions are process-safe (fcntl.flock) and thread-safe
# (threading.Lock on the index dict).


def _scan_file_into_index(agent_id: str) -> dict[str, dict]:
    """Read the agent's display file once and return the pre-delivery
    index state implied by the file (last-occurrence-wins by id, entries
    with `_pre: true`, dropping tombstoned ones).

    Returns an empty dict if the file does not exist. Does NOT mutate the
    shared index — callers do that under `_predelivery_lock`.
    """
    path = _display_path(agent_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return {}
    except OSError:
        logger.exception("predelivery: failed to read %s", path)
        return {}

    seen: dict[str, dict] = {}
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        mid = obj.get("id")
        if not mid:
            continue
        seen[mid] = obj

    result: dict[str, dict] = {}
    for mid, obj in seen.items():
        if obj.get("_deleted"):
            continue
        if not obj.get("_pre"):
            continue
        result[mid] = obj
    return result


def _ensure_index_loaded(agent_id: str) -> None:
    """Populate `_predelivery_index[agent_id]` from disk if not yet loaded.

    Idempotent: subsequent calls are O(1). Holds `_predelivery_lock` for
    the duration of the load so concurrent calls don't double-scan.
    """
    with _predelivery_lock:
        if agent_id in _predelivery_index_ready:
            return
        loaded = _scan_file_into_index(agent_id)
        _predelivery_index[agent_id] = loaded
        _predelivery_index_ready.add(agent_id)


def _validate_predelivery_entry(entry: dict) -> None:
    """Validate a caller-supplied pre-delivery entry dict.

    Raises ValueError on missing/invalid required fields.
    """
    required = ("id", "role", "content", "source", "status", "created_at")
    for field in required:
        if field not in entry:
            raise ValueError(f"predelivery entry missing required field: {field}")
    if entry["role"] != "USER":
        raise ValueError(
            f"predelivery entry role must be 'USER', got {entry['role']!r}"
        )
    if entry["source"] not in _VALID_PRE_SOURCES:
        raise ValueError(
            f"predelivery entry source must be one of {_VALID_PRE_SOURCES}, "
            f"got {entry['source']!r}"
        )
    if entry["status"] not in _VALID_PRE_STATUSES:
        raise ValueError(
            f"predelivery entry status must be one of {_VALID_PRE_STATUSES}, "
            f"got {entry['status']!r}"
        )


def predelivery_create(agent_id: str, entry: dict) -> str:
    """Append a new pre-delivery entry to the agent's display file and
    insert it into the in-memory index.

    Precondition: `entry` is a dict with the required fields (id, role,
    content, source, status, created_at). Optional fields (scheduled_at,
    metadata) may be present.

    Fills defaults (_queued=True, _pre=True, delivered_at=None,
    completed_at=None, tool_use_id=None) if absent.

    Returns the entry id.

    Raises:
        ValueError: if required fields are missing or invalid.
    """
    _validate_predelivery_entry(entry)
    _ensure_index_loaded(agent_id)

    full = dict(entry)
    full.setdefault("_queued", True)
    full["_queued"] = True  # enforce
    full["_pre"] = True
    full.setdefault("scheduled_at", None)
    full.setdefault("metadata", None)
    full.setdefault("delivered_at", None)
    full.setdefault("completed_at", None)
    full.setdefault("tool_use_id", None)

    msg_id = full["id"]
    line = json.dumps(full, separators=(",", ":"))

    os.makedirs(DISPLAY_DIR, exist_ok=True)
    path = _display_path(agent_id)
    _write_locked(path, [line])

    with _predelivery_lock:
        bucket = _predelivery_index.setdefault(agent_id, {})
        bucket[msg_id] = full
        _predelivery_index_ready.add(agent_id)

    return msg_id


def predelivery_update(agent_id: str, msg_id: str, patch: dict) -> None:
    """Merge `patch` into the existing pre-delivery entry and append a
    `_queued + _pre + _replace` line.

    Only these fields are mergeable: content, scheduled_at, metadata,
    status. Other fields in `patch` are ignored.

    Precondition: entry must exist in the index (no DB row, still _pre).

    Raises:
        KeyError: if msg_id is not a pre-delivery entry for this agent.
    """
    _ensure_index_loaded(agent_id)

    merged: dict
    with _predelivery_lock:
        bucket = _predelivery_index.get(agent_id, {})
        current = bucket.get(msg_id)
        if current is None:
            raise KeyError(
                f"predelivery_update: no pre-delivery entry for msg_id="
                f"{msg_id} on agent {agent_id[:8]}"
            )
        if not current.get("_pre"):
            raise KeyError(
                f"predelivery_update: msg {msg_id} is not a pre-delivery "
                "entry (no _pre marker) — caller must use update_last"
            )
        merged = dict(current)
        for field in ("content", "scheduled_at", "metadata", "status"):
            if field in patch:
                merged[field] = patch[field]
        merged["_queued"] = True
        merged["_pre"] = True
        merged["_replace"] = True
        bucket[msg_id] = {k: v for k, v in merged.items() if k != "_replace"}

    # Write outside the index lock (flock only); reuse the same serialized
    # form we just built, which includes _replace.
    os.makedirs(DISPLAY_DIR, exist_ok=True)
    path = _display_path(agent_id)
    _write_locked(path, [json.dumps(merged, separators=(",", ":"))])


def predelivery_cancel(agent_id: str, msg_id: str) -> None:
    """Soft-cancel a queued/scheduled pre-delivery entry.

    Patches status='cancelled' and appends a _replace line. The entry
    remains visible (grey bubble) until `predelivery_tombstone` is called.

    Raises:
        KeyError: if the entry doesn't exist.
        ValueError: if the current status is not 'queued' or 'scheduled'.
    """
    _ensure_index_loaded(agent_id)
    with _predelivery_lock:
        bucket = _predelivery_index.get(agent_id, {})
        current = bucket.get(msg_id)
        if current is None:
            raise KeyError(
                f"predelivery_cancel: no pre-delivery entry for msg_id="
                f"{msg_id} on agent {agent_id[:8]}"
            )
        cur_status = current.get("status")
        if cur_status not in ("queued", "scheduled"):
            raise ValueError(
                f"predelivery_cancel: current status is {cur_status!r}, "
                "only 'queued' or 'scheduled' can be cancelled"
            )
    predelivery_update(agent_id, msg_id, {"status": "cancelled"})


def predelivery_tombstone(agent_id: str, msg_id: str) -> None:
    """Hard-delete a cancelled pre-delivery entry.

    Appends `{"id": msg_id, "_deleted": True}` tombstone and removes the
    id from the in-memory index.

    Raises:
        KeyError: if the entry doesn't exist.
        ValueError: if current status is not 'cancelled' (caller must
            cancel first).
    """
    _ensure_index_loaded(agent_id)
    with _predelivery_lock:
        bucket = _predelivery_index.get(agent_id, {})
        current = bucket.get(msg_id)
        if current is None:
            raise KeyError(
                f"predelivery_tombstone: no pre-delivery entry for msg_id="
                f"{msg_id} on agent {agent_id[:8]}"
            )
        if current.get("status") != "cancelled":
            raise ValueError(
                "predelivery_tombstone: entry must be 'cancelled' first "
                f"(current status={current.get('status')!r})"
            )
        bucket.pop(msg_id, None)

    os.makedirs(DISPLAY_DIR, exist_ok=True)
    path = _display_path(agent_id)
    _write_locked(path, [_serialize_tombstone(msg_id)])


def predelivery_list(agent_id: str) -> list[dict]:
    """Return the current pre-delivery entries for an agent as a list.

    Cheap — reads the in-memory index. Returns shallow copies of each
    entry dict, so callers can mutate freely without affecting index
    state. Order is dict-insertion order, which matches creation order
    for entries that have not been updated out of band.
    """
    _ensure_index_loaded(agent_id)
    with _predelivery_lock:
        bucket = _predelivery_index.get(agent_id, {})
        return [dict(v) for v in bucket.values()]


def predelivery_get(agent_id: str, msg_id: str) -> dict | None:
    """Return a shallow copy of a pre-delivery entry, or None."""
    _ensure_index_loaded(agent_id)
    with _predelivery_lock:
        bucket = _predelivery_index.get(agent_id, {})
        current = bucket.get(msg_id)
        if current is None:
            return None
        return dict(current)


def predelivery_promote_to_sent(
    agent_id: str,
    msg_id: str,
    seq: int,
    sent_line: dict,
) -> None:
    """Atomically transition a pre-delivery entry to sent (DB-backed).

    Under one flock:
      1. append `{"id": msg_id, "_deleted": True}` — evicts the _pre line
         from the reader's queued partition
      2. append `sent_line` — the regular delivered-partition entry (must
         carry a seq and not be _queued/_pre)

    Also removes msg_id from the in-memory index.

    Precondition: the caller INSERTed the DB row for this message already.
    This function only writes the file.

    Raises:
        ValueError: if `sent_line` has no `id` or its id doesn't match
            `msg_id`, or if it carries _queued / _pre markers.
    """
    if sent_line.get("id") != msg_id:
        raise ValueError(
            f"predelivery_promote_to_sent: sent_line id "
            f"{sent_line.get('id')!r} does not match msg_id {msg_id!r}"
        )
    if sent_line.get("_queued") or sent_line.get("_pre"):
        raise ValueError(
            "predelivery_promote_to_sent: sent_line must not carry "
            "_queued or _pre markers"
        )
    # seq is informational here — the caller embedded it into sent_line
    # already; we don't double-write.
    _ = seq

    _ensure_index_loaded(agent_id)
    with _predelivery_lock:
        bucket = _predelivery_index.get(agent_id, {})
        bucket.pop(msg_id, None)

    os.makedirs(DISPLAY_DIR, exist_ok=True)
    path = _display_path(agent_id)
    tombstone = _serialize_tombstone(msg_id)
    sent_serialized = json.dumps(sent_line, separators=(",", ":"))
    # Single _write_locked call → single flock acquisition for both lines.
    _write_locked(path, [tombstone, sent_serialized])


def rebuild_agent(agent_id: str):
    """Rebuild display file from scratch (read-before-truncate).

    Truncates the existing file and re-flushes all messages with fresh
    display_seq values.  This prevents stale append-only blocks from
    accumulating and ensures the file reflects the current DB state.

    Read-before-truncate: before truncating, reads the current file and
    preserves any pre-delivery (`_pre: true`) entries that are not
    tombstoned — these have no DB row by design, so rebuilding solely
    from the DB would drop them. After the DB-driven flush completes,
    the preserved entries are appended back and the in-memory pre-
    delivery index is rebuilt for this agent.

    Also re-emits any legacy pre-delivery rows that still live in the DB
    as a backwards-compat path during the Phase 1→2 transition — Phase 3
    will remove this fallback.
    """
    path = _display_path(agent_id)

    # 1. Read-before-truncate: snapshot surviving _pre entries.
    preserved_pre: dict[str, dict] = _scan_file_into_index(agent_id)

    db = SessionLocal()
    try:
        # Reset display_seq to NULL so flush_agent picks them all up
        db.execute(
            text("UPDATE messages SET display_seq = NULL WHERE agent_id = :aid"),
            {"aid": agent_id},
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to reset display_seq for agent %s", agent_id[:8])
        return
    finally:
        db.close()

    # Truncate existing file — flush_agent will write a clean file
    try:
        with open(path, "w") as f:
            f.truncate(0)
    except OSError:
        pass  # file may not exist yet — flush_agent will create it

    flush_agent(agent_id)

    # 2. Re-append preserved _pre entries and rebuild the in-memory index.
    if preserved_pre:
        os.makedirs(DISPLAY_DIR, exist_ok=True)
        pre_lines = [
            json.dumps(entry, separators=(",", ":"))
            for entry in preserved_pre.values()
        ]
        try:
            _write_locked(path, pre_lines)
        except OSError:
            logger.exception(
                "rebuild_agent: failed to re-append _pre entries for agent %s",
                agent_id[:8],
            )

    with _predelivery_lock:
        _predelivery_index[agent_id] = dict(preserved_pre)
        _predelivery_index_ready.add(agent_id)

    # 3. Backwards-compat: re-emit legacy DB-backed pre-delivery rows so
    #    anything the caller hasn't migrated to the file yet still shows
    #    up as a queued bubble. Phase 3 of the refactor removes this.
    db = SessionLocal()
    try:
        queued = (
            db.query(Message)
            .filter(
                Message.agent_id == agent_id,
                Message.delivered_at.is_(None),
                Message.status != MessageStatus.CANCELLED,
                Message.source.in_(("web", "plan_continue", "task")),
                Message.display_seq.is_(None),
            )
            .order_by(Message.created_at.asc())
            .all()
        )
        if not queued:
            return
        os.makedirs(DISPLAY_DIR, exist_ok=True)
        lines = [_serialize_queued(m) for m in queued]
        try:
            _write_locked(path, lines)
        except OSError:
            logger.exception(
                "rebuild_agent: failed to append queued entries for agent %s",
                agent_id[:8],
            )
    except Exception:
        logger.exception(
            "rebuild_agent: failed to query queued messages for agent %s",
            agent_id[:8],
        )
    finally:
        db.close()


def delete_agent(agent_id: str):
    """Remove display file for a deleted/stopped agent."""
    path = _display_path(agent_id)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Failed to delete display file %s: %s", path, e)


def startup_rebuild_all():
    """On server startup, rebuild display files for all active agents.

    Query agents WHERE status NOT IN ('STOPPED', 'ERROR'), rebuild each.
    After rebuild, ensure every active agent's pre-delivery index is
    initialised (read-only scan is cheap for any agent the rebuild step
    already loaded).
    """
    db = SessionLocal()
    try:
        agents = (
            db.query(Agent.id)
            .filter(Agent.status.notin_([AgentStatus.STOPPED, AgentStatus.ERROR]))
            .all()
        )
    finally:
        db.close()

    if not agents:
        logger.info("No active agents — skipping display file rebuild")
        return

    logger.info("Rebuilding display files for %d active agents", len(agents))
    for (aid,) in agents:
        try:
            rebuild_agent(aid)
        except Exception:
            logger.exception("Failed to rebuild display file for agent %s", aid[:8])

    # Safety net: for agents whose rebuild failed or was skipped, still
    # load the pre-delivery index so the reader endpoint serves a correct
    # queued partition on first request.
    for (aid,) in agents:
        try:
            _ensure_index_loaded(aid)
        except Exception:
            logger.exception(
                "Failed to load predelivery index for agent %s", aid[:8]
            )

    logger.info("Display file rebuild complete")
