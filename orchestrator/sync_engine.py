"""Sync engine — pointer-based JSONL-to-DB synchronization.

Design principles:
1. Pointer (last_turn_count) tracks sync position
2. Hooks wake syncing (never create messages)
3. sync_import_new_turns is the SOLE message creation path
4. sync_full_scan is read-only audit (never creates/updates messages from JSONL)
5. Compact/clear/new → sync_full_scan resets pointer

All functions take (ad, ctx) where ad is AgentDispatcher, ctx is SyncContext.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_ as _or
from sqlalchemy.exc import DatabaseError, IntegrityError

from database import SessionLocal
from models import (
    Agent,
    AgentStatus,
    Message,
    MessageRole,
    MessageStatus,
)
from utils import utcnow as _utcnow, is_interrupt_message


def _parse_jsonl_ts(ts: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp from JSONL into a datetime, or None."""
    if not ts:
        return None
    try:
        # Handle "2026-03-24T17:02:44.544Z" format
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        logger.debug("Failed to parse JSONL timestamp: %s", ts)
        return None

logger = logging.getLogger("orchestrator.sync_engine")

MAX_AUDIT_FILE_SIZE = 50 * 1024 * 1024  # 50MB — protect sync_full_scan


# ---------------------------------------------------------------------------
# SyncContext dataclass — holds all per-agent sync state
# ---------------------------------------------------------------------------

@dataclass
class SyncContext:
    agent_id: str
    session_id: str
    project_path: str
    worktree: str | None = None
    agent_name: str = ""
    agent_project: str = ""
    jsonl_path: str = ""

    # Sync pointer — the only 3 state fields that matter
    last_offset: int = 0           # file byte size — change detection only
    last_turn_count: int = 0       # THE pointer: number of turns processed
    last_content_hash: str = ""    # hash of last turn content — streaming detection

    # Agent operational state
    compact_notified: bool = False
    compact_end_emitted: bool = False
    compact_detected_at: float = 0.0
    idle_polls: int = 0
    getsize_error_count: int = 0
    awaiting_rotation: bool = False     # set by SessionEnd, consumed by SessionStart


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_tool_use_id(meta: dict | None) -> str | None:
    """Extract primary tool_use_id from parsed interactive metadata."""
    if not meta or not isinstance(meta, dict):
        return None
    items = meta.get("interactive", [])
    if items and isinstance(items, list):
        return items[0].get("tool_use_id")
    return None


def _content_hash(content: str) -> str:
    """Fast hash of content for change detection."""
    import hashlib
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:16]


def _end_compact_activity(db, agent_id: str, session_id: str):
    """Mark the most recent unfinished Compact tool_activity Message as ended.

    Returns the message id (str) if found, else None — caller should
    update_last() after commit to push the status change to the display file.
    """
    existing = (
        db.query(Message)
        .filter(
            Message.agent_id == agent_id,
            Message.kind == "tool_activity",
            Message.status == MessageStatus.EXECUTING,
            Message.meta_json.contains('"tool_kind":"compact"'),
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if existing:
        import json as _json
        existing.completed_at = _utcnow()
        existing.status = MessageStatus.COMPLETED
        _meta = _json.loads(existing.meta_json or "{}")
        _meta["phase"] = "end"
        _meta["output_summary"] = "context compacted"
        existing.meta_json = _json.dumps(_meta)
        return existing.id
    return None


def _notify_interactive(ad, agent, new_turns):
    """Send push notifications for unanswered interactive items."""
    _interactive_types = []
    for _r, _c, *_rest in new_turns:
        if _r == "assistant" and _rest:
            _meta = _rest[0] if _rest else None
            if isinstance(_meta, dict):
                for _item in _meta.get("interactive", []):
                    if _item.get("answer") is None:
                        _interactive_types.append(_item.get("type", ""))

    if not _interactive_types:
        return

    if "exit_plan_mode" in _interactive_types:
        ad._send_agent_notification(agent, "Plan approval needed")
    elif "ask_user_question" in _interactive_types:
        ad._send_agent_notification(agent, "Question — waiting for your answer")


# ---------------------------------------------------------------------------
# User message promotion — single path (Phase 3a)
# ---------------------------------------------------------------------------

def _promote_or_create_user_msg(db, ctx: SyncContext, content, jsonl_uuid, seq, meta, kind, jsonl_ts=None,
                                 deferred_updates: list | None = None):
    """Match a JSONL user turn to a sent-state DB row, or create a CLI message.

    Strategy (pre-delivery refactor):
    1. UUID dedup — skip if already imported.
    2. Content-match against sent-state rows — messages that were promoted
       from the pre-delivery file on tmux send (status=QUEUED, jsonl_uuid
       NULL, delivered_at NULL) but not yet confirmed by UserPromptSubmit.
    3. No match → genuine CLI-typed user input, create a fresh row.

    Returns Message to insert, or None if already handled (dedup or
    sent->delivered update).

    When a sent row is matched, the id is appended to ``deferred_updates``
    (if provided) so the caller calls `update_last` AFTER db.commit() —
    writing the `_replace` line with status='delivered'.
    """
    from content_matcher import ContentMatcher

    # 1. UUID dedup (fastest — covers restarts/re-reads)
    if jsonl_uuid:
        existing = db.query(Message).filter(
            Message.agent_id == ctx.agent_id,
            Message.jsonl_uuid == jsonl_uuid,
        ).first()
        if existing:
            if existing.session_seq != seq:
                existing.session_seq = seq
            logger.debug("Agent %s: dedup skip uuid=%s", ctx.agent_id[:8], jsonl_uuid)
            return None

    # 2. Fetch unpromoted candidates.
    # Two shapes end up here:
    #   (a) pre-delivery → sent rows: status=QUEUED, delivered_at=NULL,
    #       jsonl_uuid=NULL (web/plan_continue path).
    #   (b) task-launched rows from _dispatch_task_tmux: status=COMPLETED
    #       synchronously, but still delivered_at=NULL, jsonl_uuid=NULL
    #       until the JSONL echo arrives.
    # Both are "not yet confirmed by JSONL"; filtering only by QUEUED
    # (case a) would orphan task-launched rows and create a duplicate
    # `source=cli` row on JSONL import — losing the insights metadata
    # that the task row carries.
    candidates = (
        db.query(Message)
        .filter(
            Message.agent_id == ctx.agent_id,
            Message.role == MessageRole.USER,
            Message.status != MessageStatus.CANCELLED,
            _or(
                Message.source == "web",
                Message.source == "plan_continue",
                Message.source == "task",
            ),
            Message.jsonl_uuid.is_(None),
            Message.delivered_at.is_(None),
        )
        .order_by(Message.created_at.asc())
        .all()
    )

    web_msg, method = ContentMatcher.match(content, candidates)

    if web_msg:
        try:
            with db.begin_nested():  # SAVEPOINT — protect against UUID collision
                if jsonl_uuid:
                    web_msg.jsonl_uuid = jsonl_uuid
                web_msg.session_seq = seq
                # sent → delivered: row already has display_seq (allocated
                # at promote-to-sent time). Just update status + timestamps.
                web_msg.delivered_at = _parse_jsonl_ts(jsonl_ts) or _utcnow()
                web_msg.status = MessageStatus.COMPLETED
                web_msg.completed_at = web_msg.delivered_at
                db.flush()
        except IntegrityError:
            # UUID collision — skip promotion, fall through to CLI creation
            logger.warning(
                "Agent %s: UUID collision promoting web msg %s (uuid=%s), "
                "creating CLI message instead",
                ctx.agent_id[:8], web_msg.id, jsonl_uuid,
            )
        else:
            logger.info("Agent %s: sent → delivered for msg %s → uuid=%s (method=%s)",
                        ctx.agent_id[:8], web_msg.id, jsonl_uuid, method)

            # Defer the display-file write until after the caller's commit.
            # Writing inline would open a second session that sees the
            # uncommitted update and writes stale state.
            if deferred_updates is not None:
                deferred_updates.append(web_msg.id)

            # Emit WS delivery event
            if web_msg.delivered_at:
                from websocket import emit_message_delivered
                asyncio.ensure_future(emit_message_delivered(
                    ctx.agent_id, web_msg.id,
                    web_msg.delivered_at.isoformat(),
                ))
            return None  # updated — no insert needed

    # 3. No promotable sent row — genuine CLI-typed input
    _ts = _parse_jsonl_ts(jsonl_ts) or _utcnow()
    return Message(
        agent_id=ctx.agent_id,
        role=MessageRole.USER,
        content=content,
        status=MessageStatus.COMPLETED,
        source="cli",
        jsonl_uuid=jsonl_uuid,
        created_at=_ts,
        completed_at=_ts,
        delivered_at=_ts,
        tool_use_id=_extract_tool_use_id(meta),
        session_seq=seq,
        kind=kind,
    )


# ---------------------------------------------------------------------------
# Assistant/system message creation (Phase 3b)
# ---------------------------------------------------------------------------

def _create_agent_msg(db, ctx: SyncContext, content, jsonl_uuid, seq, meta, meta_json, kind, jsonl_ts=None):
    """UUID dedup, then create AGENT message. Returns Message or None."""
    if jsonl_uuid:
        existing = db.query(Message.id).filter(
            Message.agent_id == ctx.agent_id,
            Message.jsonl_uuid == jsonl_uuid,
        ).first()
        if existing:
            logger.debug("Agent %s: dedup skip uuid=%s", ctx.agent_id[:8], jsonl_uuid)
            return None

    logger.debug("Agent %s: creating message role=assistant kind=%s uuid=%s seq=%d",
                 ctx.agent_id[:8], kind, jsonl_uuid, seq)
    _now = _parse_jsonl_ts(jsonl_ts) or _utcnow()
    _tid = (meta.get("tool_use_id") if kind == "tool_use" and meta
            else _extract_tool_use_id(meta))
    return Message(
        agent_id=ctx.agent_id,
        role=MessageRole.AGENT,
        content=content,
        status=MessageStatus.COMPLETED,
        source="cli",
        meta_json=meta_json,
        jsonl_uuid=jsonl_uuid,
        created_at=_now,
        completed_at=_now,
        delivered_at=_now,
        tool_use_id=_tid,
        session_seq=seq,
        kind=kind,
    )


def _create_system_msg(db, ctx: SyncContext, content, jsonl_uuid, seq, kind, jsonl_ts=None):
    """UUID dedup, then create SYSTEM message. Returns Message or None."""
    if jsonl_uuid:
        existing = db.query(Message.id).filter(
            Message.agent_id == ctx.agent_id,
            Message.jsonl_uuid == jsonl_uuid,
        ).first()
        if existing:
            logger.debug("Agent %s: dedup skip uuid=%s", ctx.agent_id[:8], jsonl_uuid)
            return None

    logger.debug("Agent %s: creating message role=system kind=%s uuid=%s seq=%d",
                 ctx.agent_id[:8], kind, jsonl_uuid, seq)
    _now = _parse_jsonl_ts(jsonl_ts) or _utcnow()
    return Message(
        agent_id=ctx.agent_id,
        role=MessageRole.SYSTEM,
        content=content,
        status=MessageStatus.COMPLETED,
        source="cli",
        jsonl_uuid=jsonl_uuid,
        created_at=_now,
        completed_at=_now,
        delivered_at=_now,
        session_seq=seq,
        kind=kind,
    )


# ---------------------------------------------------------------------------
# Streaming update helper (Phase 3c)
# ---------------------------------------------------------------------------

def _handle_streaming_update(ad, ctx: SyncContext, turns, current_size) -> str:
    """Update last assistant message content if it grew (streaming).

    Only applies to text turns (tool_use turns don't stream).
    Returns "turn_updated", "exit", or "no_change".
    """
    from jsonl_parser import merge_interactive_meta as _merge_interactive_meta
    from websocket import emit_new_message

    last_turn = turns[-1]
    last_kind = last_turn[4] if len(last_turn) > 4 else None
    new_hash = _content_hash(last_turn[1])

    if (new_hash == ctx.last_content_hash
            or last_turn[0] != "assistant"
            or last_kind not in ("text", None)):
        ctx.last_offset = current_size
        return "no_change"

    db = SessionLocal()
    try:
        agent = db.get(Agent, ctx.agent_id)
        if not agent or agent.status in (AgentStatus.STOPPED, AgentStatus.ERROR):
            return "exit"

        last_msg = db.query(Message).filter(
            Message.agent_id == ctx.agent_id,
            Message.role == MessageRole.AGENT,
        ).order_by(Message.created_at.desc()).first()

        if not last_msg:
            ctx.last_offset = current_size
            return "no_change"

        _role, _content, *_rest = last_turn
        _meta = _rest[0] if _rest else None
        _uuid = _rest[1] if len(_rest) > 1 else None

        logger.debug("Agent %s: streaming update msg=%s new_len=%d",
                     ctx.agent_id[:8], last_msg.id, len(_content))

        last_msg.content = _content
        last_msg.completed_at = _utcnow()
        last_msg.session_seq = last_msg.session_seq or (len(turns) - 1)
        if _uuid and not last_msg.jsonl_uuid:
            last_msg.jsonl_uuid = _uuid
        if _meta is not None:
            last_msg.meta_json = _merge_interactive_meta(
                last_msg.meta_json, _meta,
            )
        agent.last_message_preview = (_content or "")[:200]
        agent.last_message_at = _utcnow()
        db.commit()

        # Update display file with replaced content
        from display_writer import update_last as _update_display
        _update_display(ctx.agent_id, last_msg.id)

        ad._emit(emit_new_message(
            agent.id, "sync", ctx.agent_name, ctx.agent_project,
        ))
        ctx.last_content_hash = new_hash
        ctx.last_offset = current_size
        logger.info(
            "Updated last turn content for agent %s (%d chars)",
            ctx.agent_id, len(_content),
        )
    finally:
        db.close()
    return "turn_updated"


# ---------------------------------------------------------------------------
# sync_import_new_turns — SOLE message creation path
# ---------------------------------------------------------------------------

async def sync_import_new_turns(ad, ctx: SyncContext):
    """Full-parse JSONL, import new turns via pointer.

    This is the SOLE path that creates Message rows from JSONL.
    Returns: "new_turns", "turn_updated", "no_change", "compact", "exit",
             "commit_error"
    """
    from jsonl_parser import (
        parse_session_turns as _parse_session_turns,
        merge_interactive_meta as _merge_interactive_meta,
    )
    from websocket import emit_agent_update, emit_new_message
    from thumbnails import generate_thumbnails_for_message

    # 1. Check file size for change detection
    try:
        current_size = os.path.getsize(ctx.jsonl_path)
    except OSError as e:
        logger.warning("Cannot stat JSONL %s: %s", ctx.jsonl_path, e)
        return "no_change"

    if current_size < ctx.last_offset:
        return "compact"  # caller handles via sync_full_scan

    if current_size == ctx.last_offset:
        return "no_change"

    # 2. Full parse — simple, correct, the "stable point" approach
    turns = _parse_session_turns(ctx.jsonl_path)

    logger.debug("Agent %s: parsed %d total turns, pointer at %d, new_turns=%d",
                 ctx.agent_id[:8], len(turns), ctx.last_turn_count,
                 max(0, len(turns) - ctx.last_turn_count))

    # 3. Detect turn count decrease (compact with longer summary)
    if len(turns) < ctx.last_turn_count:
        return "compact"

    # 4. Slice new turns using the pointer
    new_turns = turns[ctx.last_turn_count:]

    # 5. Streaming update — last turn content changed but no new turns
    if not new_turns and turns:
        return _handle_streaming_update(ad, ctx, turns, current_size)

    if not new_turns:
        ctx.last_offset = current_size
        return "no_change"

    # 6. Import new turns
    db = SessionLocal()
    try:
        agent = db.get(Agent, ctx.agent_id)
        if not agent or agent.status in (AgentStatus.STOPPED, AgentStatus.ERROR):
            return "exit"

        # Sanity check: previous turn content should not grow between syncs.
        # Claude Code buffers responses and flushes to JSONL on completion,
        # so content should be final when hook-driven sync imports it.
        if ctx.last_turn_count > 0:
            prev_role, prev_content, *prev_rest = turns[ctx.last_turn_count - 1]
            if prev_role == "assistant":
                last_agent_msg = db.query(Message).filter(
                    Message.agent_id == ctx.agent_id,
                    Message.role == MessageRole.AGENT,
                ).order_by(Message.created_at.desc()).first()
                if (last_agent_msg
                        and len(last_agent_msg.content or "") < len(prev_content)):
                    logger.warning(
                        "Agent %s: previous turn content grew between syncs "
                        "(db_len=%d, jsonl_len=%d, msg_id=%s, jsonl_uuid=%s). "
                        "DB message may have stale content.",
                        ctx.agent_id[:8],
                        len(last_agent_msg.content or ""),
                        len(prev_content),
                        last_agent_msg.id,
                        last_agent_msg.jsonl_uuid,
                    )

        _actually_inserted = 0
        _saw_interrupt = False
        _saw_stop_hook = False
        _saw_rate_limit = False
        # Accumulate message_ids updated (sent→delivered) this cycle so we
        # can call update_last AFTER db.commit(). Writing inline would
        # violate the display_writer "commit → then flush" contract (the
        # function opens its own session, which would see stale state).
        _deferred_updates: list[str] = []
        for i, (role, content, *rest) in enumerate(new_turns):
            seq = ctx.last_turn_count + i
            meta = rest[0] if rest else None
            jsonl_uuid = rest[1] if len(rest) > 1 else None
            kind = rest[2] if len(rest) > 2 else None
            jsonl_ts = rest[3] if len(rest) > 3 else None
            meta_json = json.dumps(meta) if meta else None

            logger.debug("Agent %s: processing turn %d: role=%s kind=%s uuid=%s content_len=%d",
                         ctx.agent_id[:8], seq, role, kind, jsonl_uuid, len(content or ""))

            if role == "user":
                msg = _promote_or_create_user_msg(
                    db, ctx, content, jsonl_uuid, seq, meta, kind, jsonl_ts,
                    deferred_updates=_deferred_updates,
                )
                if msg is None:
                    continue

            elif role == "assistant":
                msg = _create_agent_msg(
                    db, ctx, content, jsonl_uuid, seq, meta, meta_json, kind, jsonl_ts,
                )
                if msg is None:
                    continue

            elif role == "system":
                if kind == "stop_hook":
                    _saw_stop_hook = True
                if kind == "interrupt":
                    _saw_interrupt = True
                if kind == "rate_limit":
                    _saw_rate_limit = True

                msg = _create_system_msg(
                    db, ctx, content, jsonl_uuid, seq, kind, jsonl_ts,
                )
                if msg is None:
                    continue

            else:
                continue

            # SAVEPOINT insert — protects against duplicate UUIDs
            try:
                with db.begin_nested():
                    db.add(msg)
                    db.flush()
                    _actually_inserted += 1
            except IntegrityError:
                logger.warning(
                    "Skipped duplicate jsonl_uuid %s for agent %s",
                    jsonl_uuid, ctx.agent_id[:8],
                )
                continue

        if _actually_inserted:
            # Skip stop_hook turns for preview (they're signals, not content)
            _preview_turn = next(
                (t for t in reversed(new_turns) if not (len(t) > 4 and t[4] == "stop_hook")),
                new_turns[-1],
            )
            agent.last_message_preview = (_preview_turn[1] or "")[:200]
            agent.last_message_at = _utcnow()

        try:
            db.commit()
        except (DatabaseError, IntegrityError) as exc:
            db.rollback()
            logger.warning(
                "Commit failed for agent %s, will retry next cycle: %s",
                ctx.agent_id[:8], exc,
            )
            # Drop deferred updates — the rows never committed, so the
            # display file must not reflect them.
            _deferred_updates.clear()
            # DO NOT advance pointer — next cycle retries, UUID dedup
            # skips already-committed turns
            return "commit_error"

        # Advance pointer ONLY on successful commit
        ctx.last_turn_count = len(turns)
        ctx.last_offset = current_size
        ctx.last_content_hash = _content_hash(turns[-1][1]) if turns else ""

        # Sent rows already carry display_seq from the promote-to-sent
        # step. update_last appends a _replace line reflecting the new
        # status (delivered/completed), so the display file transitions
        # the bubble without a new seq slot.
        if _deferred_updates:
            from display_writer import update_last as _update_last
            for _updated_id in _deferred_updates:
                _update_last(ctx.agent_id, _updated_id)

        # Flush remaining undisplayed messages (AGENT/SYSTEM and any USER
        # turns not matched to a sent row — i.e. genuine CLI input).
        from display_writer import flush_agent as _flush_display
        _flush_display(ctx.agent_id)

        # Rate limit detected: transition to IDLE but do NOT dispatch queued
        # messages — the agent cannot process them while rate-limited.
        if _saw_rate_limit:
            logger.info(
                "sync: rate_limit detected for agent %s — "
                "transitioning to IDLE (no dispatch)",
                ctx.agent_id[:8],
            )
            ad._stop_generating(ctx.agent_id)
            # Claude Code shows a /rate-limit-options menu after rate limit.
            # Send Enter after 1s to dismiss it so the CLI returns to the
            # idle prompt and is ready for future messages.
            _rl_pane = agent.tmux_pane
            if _rl_pane:
                _rl_aid = ctx.agent_id[:8]
                async def _dismiss_rate_limit_menu(pane, aid_short):
                    await asyncio.sleep(1.0)
                    from agent_dispatcher import send_tmux_keys
                    if send_tmux_keys(pane, ["Enter"]):
                        logger.info(
                            "sync: sent Enter to dismiss rate-limit menu "
                            "for agent %s", aid_short,
                        )
                asyncio.ensure_future(
                    _dismiss_rate_limit_menu(_rl_pane, _rl_aid)
                )

        # Interrupt detected in JSONL: stop generating and dispatch PENDING
        # messages.  _stop_generating is called HERE (after db.commit) rather
        # than inside the turn loop to avoid a self-deadlock: the loop holds
        # uncommitted SAVEPOINTs on one connection while _stop_generating
        # opens a second connection that tries to write — same async task,
        # two connections, SQLite single-writer lock → 5s timeout → crash.
        if _saw_interrupt:
            ad._stop_generating(ctx.agent_id)
            if not _saw_rate_limit:
                asyncio.ensure_future(ad.dispatch_pending_message(ctx.agent_id, delay=0))
            # Dismiss any unanswered interactive cards — the interrupt killed
            # the tool_use before a tool_result could be written, so the
            # PostToolUse backfill path will never fire.
            from routers.agents import _dismiss_pending_interactive_cards
            _dismissed = _dismiss_pending_interactive_cards(db, ctx.agent_id)
            if _dismissed:
                from websocket import emit_metadata_update
                for _d in _dismissed:
                    ad._emit(emit_metadata_update(
                        ctx.agent_id, _d["message_id"], _d["metadata"],
                    ))
                logger.info(
                    "sync: dismissed %d interactive card(s) for agent %s on interrupt",
                    len(_dismissed), ctx.agent_id[:8],
                )

        # stop_hook_summary in JSONL: this is the authoritative signal that
        # the agent finished a turn.  Perform all stop-hook operations here
        # (the HTTP handler only wakes sync; this is the sole executor).
        # _stop_generating is idempotent; unread/notify/dispatch run once
        # because the HTTP handler no longer does them.
        if _saw_stop_hook:
            logger.info(
                "sync: stop_hook_summary detected for agent %s — "
                "executing stop-hook operations",
                ctx.agent_id[:8],
            )
            ad._stop_generating(ctx.agent_id)
            # unread + notify
            _sh_db = SessionLocal()
            _sh_project = None
            _sh_status = None
            _sh_bumped = False
            try:
                _sh_agent = _sh_db.get(Agent, ctx.agent_id)
                if _sh_agent:
                    _is_sub = _sh_agent.is_subagent or _sh_agent.parent_id
                    if not _is_sub and not ad._is_agent_in_use(
                        _sh_agent.id, _sh_agent.tmux_pane
                    ):
                        _sh_agent.unread_count += 1
                        _sh_bumped = True
                    _sh_db.commit()
                    _sh_project = _sh_agent.project
                    _sh_status = _sh_agent.status.value
                    if not _is_sub:
                        ad._maybe_notify_message(_sh_agent)
            finally:
                _sh_db.close()
            # Broadcast immediately so frontend subscribers (e.g. the FAB
            # unread badge) update in sync with the APNs push, instead of
            # waiting for the per-turn emit at the end of sync import (which
            # can lag 2-3s when importing large deltas / thumbnails).
            if _sh_bumped and _sh_project is not None:
                from websocket import emit_agent_update
                ad._emit(emit_agent_update(
                    ctx.agent_id, _sh_status or "IDLE", _sh_project,
                ))
            # mark slash commands completed
            import slash_commands as _sc
            _sc.mark_completed(ctx.agent_id)
            # dispatch pending (no delay — response already imported above)
            # Skip dispatch if rate-limited — agent can't process messages
            if not _saw_rate_limit:
                asyncio.ensure_future(
                    ad.dispatch_pending_message(ctx.agent_id, delay=0)
                )
            # Fire-and-forget resume hint refresh — summarize this agent's
            # last few turns into the project's recap.  Stop hook is the
            # authoritative "turn is done" signal.
            if _sh_project and _sh_agent and not _sh_agent.is_subagent:
                from routers.projects import _refresh_resume_hint
                asyncio.ensure_future(_refresh_resume_hint(ctx.agent_id))

        logger.debug("Agent %s: sync_import result=%s, inserted=%d, pointer now=%d",
                     ctx.agent_id[:8], "new_turns", _actually_inserted, ctx.last_turn_count)

        ad._emit(emit_agent_update(
            agent.id, agent.status.value, agent.project,
        ))
        logger.info(
            "Synced %d new turns for agent %s (roles=%s)",
            len(new_turns), ctx.agent_id,
            [r for r, *_ in new_turns],
        )
        if any(r != "user" for r, *_ in new_turns):
            ad._emit(emit_new_message(
                agent.id, "sync", ctx.agent_name, ctx.agent_project,
            ))

        # Notify for unanswered interactive items
        _notify_interactive(ad, agent, new_turns)

        # Generate video thumbnails for new assistant turns
        for _r, _c, *_ in new_turns:
            if _r == "assistant" and _c:
                asyncio.ensure_future(asyncio.to_thread(
                    generate_thumbnails_for_message, _c, ctx.project_path,
                ))

    finally:
        db.close()

    return "new_turns"


# ---------------------------------------------------------------------------
# sync_full_scan — read-only audit + pointer reset
# ---------------------------------------------------------------------------

async def sync_full_scan(ad, ctx: SyncContext, reason: str = "startup"):
    """Read-only audit + pointer reset.

    Called on: startup, compact, clear, new session, manual trigger.
    - On compact: deletes orphaned DB messages, reassigns session_seq.
    - On mismatch: logs warning, resets pointer for reimport.
    - Always: resets the sync pointer to current state.
    - NEVER creates or updates regular messages from JSONL.
    """
    from jsonl_parser import parse_session_turns as _parse_session_turns
    from websocket import emit_new_message

    logger.info("Full scan for agent %s (reason=%s)", ctx.agent_id, reason)

    turns = _parse_session_turns(ctx.jsonl_path, max_bytes=MAX_AUDIT_FILE_SIZE)
    try:
        current_size = os.path.getsize(ctx.jsonl_path)
    except OSError as e:
        logger.warning("Cannot stat JSONL %s during audit: %s", ctx.jsonl_path, e)
        current_size = 0

    # Collect all UUIDs from JSONL
    jsonl_uuids = {t[3] for t in turns if len(t) > 3 and t[3]}
    logger.debug("Agent %s: full_scan found %d JSONL UUIDs", ctx.agent_id[:8], len(jsonl_uuids))

    db = SessionLocal()
    try:
        # Get all DB messages that have a jsonl_uuid (includes cli-sourced
        # AND web-sourced messages that were linked via wrapped-prompt matching)
        db_msgs = (
            db.query(Message)
            .filter(
                Message.agent_id == ctx.agent_id,
                Message.jsonl_uuid.isnot(None),
            )
            .all()
        )

        db_by_uuid = {m.jsonl_uuid: m for m in db_msgs}
        logger.debug("Agent %s: full_scan found %d DB messages with UUID", ctx.agent_id[:8], len(db_msgs))

        # Detect drift
        missing_in_db = [u for u in jsonl_uuids if u not in db_by_uuid]
        extra_in_db = [
            m for m in db_msgs
            if m.jsonl_uuid and m.jsonl_uuid not in jsonl_uuids
        ]
        content_mismatches = []
        for t in turns:
            content, uuid = t[1], t[3] if len(t) > 3 else None
            if uuid and uuid in db_by_uuid:
                db_msg = db_by_uuid[uuid]
                if abs(len(db_msg.content or "") - len(content)) > 50:
                    content_mismatches.append(uuid)

        logger.debug("Agent %s: missing_in_db=%d extra_in_db=%d mismatches=%d",
                     ctx.agent_id[:8], len(missing_in_db), len(extra_in_db), len(content_mismatches))

        _changes_made = False

        # On compact: delete orphaned cli-sourced messages + reassign session_seq
        _compact_finalized_msg_id: str | None = None
        _compact_activity_id: str | None = None
        if reason == "compact":
            _cli_orphans = [m for m in extra_in_db if m.source == "cli"]
            if _cli_orphans:
                for m in _cli_orphans:
                    db.delete(m)
                logger.info(
                    "Purged %d orphaned messages for agent %s after compact",
                    len(_cli_orphans), ctx.agent_id,
                )
                _changes_made = True

            # Reassign session_seq from fresh turn order
            for idx, t in enumerate(turns):
                uuid = t[3] if len(t) > 3 else None
                if uuid and uuid in db_by_uuid:
                    db_by_uuid[uuid].session_seq = idx
            _changes_made = True

            # Finalize the /compact user message. It never lands in
            # post-compact JSONL (CC rewrites the file and drops that turn),
            # so _promote_or_create_user_msg can't match it. This path is
            # the only point the row ever gets its completion tick.
            _compact_msg = (
                db.query(Message)
                .filter(
                    Message.agent_id == ctx.agent_id,
                    Message.role == MessageRole.USER,
                    Message.source == "web",
                    Message.completed_at.is_(None),
                    Message.content.startswith("/compact"),
                )
                .order_by(Message.created_at.desc())
                .first()
            )
            if _compact_msg:
                _now = _utcnow()
                _compact_msg.completed_at = _now
                _compact_msg.status = MessageStatus.COMPLETED
                if not _compact_msg.delivered_at:
                    _compact_msg.delivered_at = _now
                # Fake jsonl_uuid so subsequent UUID-dedup / content-match
                # cycles don't try to re-link this row to a real user turn.
                if not _compact_msg.jsonl_uuid:
                    _compact_msg.jsonl_uuid = f"slash-{_compact_msg.id[:8]}"
                _compact_finalized_msg_id = _compact_msg.id
                _changes_made = True

            # End compact tool activity record
            _compact_activity_id = _end_compact_activity(
                db, ctx.agent_id, ctx.session_id,
            )

            # Handle compact UI signals
            if ctx.compact_end_emitted:
                ctx.compact_end_emitted = False
            else:
                import time as _time
                ctx.compact_detected_at = _time.monotonic()
            ctx.compact_notified = False

        # Log drift — no UI bubbles, no silent skipping.
        if missing_in_db:
            logger.warning(
                "Agent %s: %d JSONL turns not in DB (%s), resetting pointer for reimport",
                ctx.agent_id, len(missing_in_db), reason,
            )
        if extra_in_db and reason != "compact":
            logger.warning(
                "Agent %s: %d DB messages not in JSONL (%s)",
                ctx.agent_id, len(extra_in_db), reason,
            )
        if content_mismatches:
            logger.warning(
                "Agent %s: %d content mismatches (%s)",
                ctx.agent_id, len(content_mismatches), reason,
            )

        if _changes_made:
            db.commit()

        # Rebuild display file after compact — purge stale pre-compact entries
        if reason == "compact":
            from display_writer import rebuild_agent as _rebuild_display
            _rebuild_display(ctx.agent_id)

            # Frontend WS event: compact_msg now shows the double tick.
            # rebuild_agent already refreshed the display file; this is just
            # the push signal so clients don't wait for the next poll.
            if _compact_finalized_msg_id:
                _compact_msg_re = db.get(Message, _compact_finalized_msg_id)
                if _compact_msg_re and _compact_msg_re.completed_at:
                    from websocket import emit_message_update
                    asyncio.ensure_future(emit_message_update(
                        ctx.agent_id, _compact_finalized_msg_id, "COMPLETED",
                        completed_at=_compact_msg_re.completed_at.isoformat(),
                    ))

        # If turns are missing from DB, reset pointer so sync loop reimports them.
        # Otherwise, set pointer to current state.
        _old_count = ctx.last_turn_count
        if missing_in_db:
            ctx.last_turn_count = 0
            ctx.last_offset = 0
            ctx.last_content_hash = ""
        else:
            ctx.last_turn_count = len(turns)
            ctx.last_offset = current_size
            ctx.last_content_hash = _content_hash(turns[-1][1]) if turns else ""
        logger.debug("Agent %s: pointer reset to %d (was %d)",
                     ctx.agent_id[:8], ctx.last_turn_count, _old_count)

        logger.info(
            "Full scan complete for agent %s: %d turns, pointer at %d bytes",
            ctx.agent_id, len(turns), current_size,
        )

        return {
            "turns": len(turns),
            "missing_in_db": len(missing_in_db),
            "extra_in_db": len(extra_in_db),
            "content_mismatches": len(content_mismatches),
        }
    except (DatabaseError, IntegrityError) as e:
        logger.error("Full scan failed for %s: %s", ctx.agent_id, e)
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# trigger_sync — public entry point for hooks
# ---------------------------------------------------------------------------

async def trigger_sync(ad, agent_id: str):
    """Public entry point for hooks to wake the sync loop."""
    ctx = ad._sync_contexts.get(agent_id)
    if not ctx:
        return
    ad.wake_sync(agent_id)
