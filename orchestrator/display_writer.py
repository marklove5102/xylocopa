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
from datetime import datetime, timezone

from sqlalchemy import func, text

from config import _resolve
from database import SessionLocal
from models import Agent, AgentStatus, Message, MessageRole, MessageStatus

logger = logging.getLogger("orchestrator.display_writer")

DISPLAY_DIR = _resolve("data/display")


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
    """Atomically move a queued entry to the delivered partition.

    Under a single flock: append (a) tombstone `{id, _deleted: true}` and
    (b) the full regular entry with freshly allocated `display_seq`. Then
    commit `display_seq` on the DB row.

    Precondition: DB row exists, `delivered_at` is set, `display_seq` is
    NULL. Raises RuntimeError if `display_seq` is already set — that means
    another code path allocated a seq first (typically flush_agent), which
    violates the sync post-commit ordering contract (promote_to_delivered
    must run BEFORE flush_agent).
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
            raise RuntimeError(
                f"promote_to_delivered contract violation: msg {message_id} "
                f"already has display_seq={msg.display_seq}. Typical cause: "
                "flush_agent ran before promote_to_delivered in the sync "
                "post-commit block (wrong order)."
            )

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
        db.close()


def rebuild_agent(agent_id: str):
    """Rebuild display file from scratch.

    Truncates the existing file and re-flushes all messages with fresh
    display_seq values.  This prevents stale append-only blocks from
    accumulating and ensures the file reflects the current DB state.
    """
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
    path = _display_path(agent_id)
    try:
        with open(path, "w") as f:
            f.truncate(0)
    except OSError:
        pass  # file may not exist yet — flush_agent will create it

    flush_agent(agent_id)

    # Also re-emit any pre-delivery queued entries so the queued partition
    # survives rebuild. Reader dedup by id handles any overlap safely.
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

    logger.info("Display file rebuild complete")
