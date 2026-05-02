"""Centralized writers for the cc_sessions table.

The ``cc_sessions`` table tracks one Claude Code conversation session per
row — either a top-level CLI session owned by a xylo agent (possibly one
of many across /compact /clear rotations) or a sub-session spawned via
the Task tool inside another CC session.

This module is the SOLE place that mutates ``CCSession`` rows from the
live event hooks (``agent_dispatcher._rotate_agent_session`` and the
``sync_engine.sync_import_new_turns`` path). Reconcile sweeps live in
``cc_session_reconcile`` and ``cc_session_discovery`` (sibling modules).

All writes are best-effort: cc_sessions is a bookkeeping table, NEVER a
fatal path. Every public function wraps its DB work in try/except and
swallows errors with a logged warning.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy.exc import DatabaseError, IntegrityError

from database import SessionLocal
from models import CCSession
from utils import utcnow as _utcnow

logger = logging.getLogger("orchestrator.cc_session_writer")


# ---------------------------------------------------------------------------
# Token totals normalization
# ---------------------------------------------------------------------------
# ``session_history.sum_jsonl_usage`` returns long-form keys
# (input_tokens, output_tokens, cache_creation_input_tokens,
# cache_read_input_tokens) plus turn_count. The CCSession columns use
# short forms (total_input_tokens, total_output_tokens,
# total_cache_creation_tokens, total_cache_read_tokens). The spec for
# this module documents ``totals`` with short keys (input / output /
# cache_creation / cache_read / turn_count). Accept BOTH.

_LONG_TO_SHORT = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_creation_input_tokens": "cache_creation",
    "cache_read_input_tokens": "cache_read",
}


def _normalize_totals(totals: dict | None) -> dict[str, int]:
    """Coerce a totals dict to the short-key form used internally.

    Accepts either ``sum_jsonl_usage``-style long keys or the spec's
    short keys. Missing entries default to 0. Returned dict always
    contains all five keys (input/output/cache_creation/cache_read/
    turn_count).
    """
    out: dict[str, int] = {
        "input": 0,
        "output": 0,
        "cache_creation": 0,
        "cache_read": 0,
        "turn_count": 0,
    }
    if not totals:
        return out
    for k, v in totals.items():
        if k in _LONG_TO_SHORT:
            short = _LONG_TO_SHORT[k]
            try:
                out[short] = int(v or 0)
            except (TypeError, ValueError):
                continue
        elif k in out:
            try:
                out[k] = int(v or 0)
            except (TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# upsert_cc_session
# ---------------------------------------------------------------------------

def upsert_cc_session(
    session_id: str,
    agent_id: str,
    project_path: str,
    *,
    parent_session_id: str | None = None,
    parent_jsonl_uuid: str | None = None,
    worktree: str | None = None,
    is_subagent_session: bool = False,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    end_reason: str | None = None,
    model: str | None = None,
    totals: dict | None = None,
) -> str | None:
    """INSERT or UPDATE a ``cc_sessions`` row. Idempotent.

    On INSERT the row is created with whatever fields are provided.
    On UPDATE only non-None scalar args overwrite existing values, so
    callers can submit narrow patches without erasing fields populated
    by an earlier writer or by reconcile.

    Token totals (``totals`` arg) are an exception: they ALWAYS overwrite
    when provided, since the writer always rescans the JSONL to get the
    exact current value (no stale-Nones risk).

    Returns the session_id on success, None on failure (logged).
    """
    if not session_id or not agent_id or not project_path:
        logger.warning(
            "upsert_cc_session: missing required field "
            "(session_id=%r agent_id=%r project_path=%r)",
            session_id, agent_id, project_path,
        )
        return None

    db = SessionLocal()
    try:
        row = db.get(CCSession, session_id)
        norm_totals = _normalize_totals(totals) if totals is not None else None

        if row is None:
            # INSERT path
            row = CCSession(
                session_id=session_id,
                agent_id=agent_id,
                project_path=project_path,
                parent_session_id=parent_session_id,
                parent_jsonl_uuid=parent_jsonl_uuid,
                worktree=worktree,
                is_subagent_session=bool(is_subagent_session),
                started_at=started_at,
                ended_at=ended_at,
                end_reason=end_reason,
                model=model,
            )
            if norm_totals is not None:
                row.total_input_tokens = norm_totals["input"]
                row.total_output_tokens = norm_totals["output"]
                row.total_cache_creation_tokens = norm_totals["cache_creation"]
                row.total_cache_read_tokens = norm_totals["cache_read"]
                row.turn_count = norm_totals["turn_count"]
            db.add(row)
        else:
            # UPDATE path — only patch non-None scalars; preserve
            # existing values for any arg the caller passed as None.
            # agent_id and project_path may also be patched (e.g.
            # reconcile correcting an earlier guess), but only when
            # the caller actually provides a non-default value.
            if agent_id and agent_id != row.agent_id:
                row.agent_id = agent_id
            if project_path and project_path != row.project_path:
                row.project_path = project_path
            if parent_session_id is not None:
                row.parent_session_id = parent_session_id
            if parent_jsonl_uuid is not None:
                row.parent_jsonl_uuid = parent_jsonl_uuid
            if worktree is not None:
                row.worktree = worktree
            # is_subagent_session is a bool flag — only flip if the
            # caller is explicitly marking this session as subagent
            # (False is the column default, so a False arg that doesn't
            # match an existing True would clobber reconcile's work).
            if is_subagent_session and not row.is_subagent_session:
                row.is_subagent_session = True
            if started_at is not None:
                row.started_at = started_at
            if ended_at is not None:
                row.ended_at = ended_at
            if end_reason is not None:
                row.end_reason = end_reason
            if model is not None:
                row.model = model
            if norm_totals is not None:
                row.total_input_tokens = norm_totals["input"]
                row.total_output_tokens = norm_totals["output"]
                row.total_cache_creation_tokens = norm_totals["cache_creation"]
                row.total_cache_read_tokens = norm_totals["cache_read"]
                row.turn_count = norm_totals["turn_count"]
            row.updated_at = _utcnow()

        db.commit()
        return session_id
    except (DatabaseError, IntegrityError) as exc:
        db.rollback()
        logger.warning(
            "upsert_cc_session: DB error for session=%s agent=%s: %s",
            (session_id or "")[:12], (agent_id or "")[:8], exc,
        )
        return None
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not propagate
        db.rollback()
        logger.warning(
            "upsert_cc_session: unexpected error for session=%s: %s",
            (session_id or "")[:12], exc, exc_info=True,
        )
        return None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# mark_session_ended
# ---------------------------------------------------------------------------

def mark_session_ended(
    session_id: str,
    end_reason: str,
    totals: dict | None = None,
) -> bool:
    """Set ``ended_at=now`` and ``end_reason=<given>`` on an existing row.

    Optionally updates token totals (same merge rules as
    ``upsert_cc_session``: totals overwrite when provided).

    Returns True on success, False if the row was missing or the write
    failed.
    """
    if not session_id or not end_reason:
        logger.warning(
            "mark_session_ended: missing field (session_id=%r end_reason=%r)",
            session_id, end_reason,
        )
        return False

    db = SessionLocal()
    try:
        row = db.get(CCSession, session_id)
        if row is None:
            logger.debug(
                "mark_session_ended: no row for session=%s",
                (session_id or "")[:12],
            )
            return False
        row.ended_at = _utcnow()
        row.end_reason = end_reason
        if totals is not None:
            norm = _normalize_totals(totals)
            row.total_input_tokens = norm["input"]
            row.total_output_tokens = norm["output"]
            row.total_cache_creation_tokens = norm["cache_creation"]
            row.total_cache_read_tokens = norm["cache_read"]
            row.turn_count = norm["turn_count"]
        row.updated_at = _utcnow()
        db.commit()
        return True
    except (DatabaseError, IntegrityError) as exc:
        db.rollback()
        logger.warning(
            "mark_session_ended: DB error for session=%s: %s",
            (session_id or "")[:12], exc,
        )
        return False
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not propagate
        db.rollback()
        logger.warning(
            "mark_session_ended: unexpected error for session=%s: %s",
            (session_id or "")[:12], exc, exc_info=True,
        )
        return False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# detect_and_record_subsessions
# ---------------------------------------------------------------------------

def _parse_iso_ts(ts: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string to datetime; None on failure."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def detect_and_record_subsessions(
    parent_jsonl_path: str,
    parent_session_id: str,
    parent_agent_id: str,
    *,
    project_path: str | None = None,
    worktree: str | None = None,
) -> int:
    """Scan parent's session_dir for sub-session JSONLs and record them.

    A sub-session is a JSONL whose first entry's ``parentUuid`` matches
    a UUID present in the parent JSONL — i.e. the sub-session was
    spawned via a Task tool call from inside the parent.

    Caller is expected to invoke this AFTER a Task tool_result lands
    (signaled by sync detecting the tool_result entry). One scan
    discovers all unmapped sub-sessions in the directory; idempotent
    re-runs are safe — ``upsert_cc_session`` deduplicates by session_id.

    The optional ``project_path`` / ``worktree`` args back-fill the
    ``CCSession`` row's ``project_path`` / ``worktree`` columns; the
    parent's value is reused when not given.

    Returns the count of sub-sessions newly recorded (i.e. that were
    not already in the cc_sessions table). Returns 0 silently when the
    sibling discovery module isn't importable yet.
    """
    if not parent_jsonl_path or not parent_session_id or not parent_agent_id:
        return 0
    if not os.path.isfile(parent_jsonl_path):
        return 0

    # Lazy import — sibling subagent owns this module. If it isn't
    # ready yet (or imports raise), bail silently so the live hooks
    # don't crash.
    try:
        import cc_session_discovery as _disc  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        logger.debug(
            "detect_and_record_subsessions: cc_session_discovery not available"
        )
        return 0
    parse_meta = getattr(_disc, "parse_jsonl_metadata", None)
    link_sub = getattr(_disc, "link_sub_to_parent", None)
    if parse_meta is None or link_sub is None:
        logger.debug(
            "detect_and_record_subsessions: required helpers not exported"
        )
        return 0

    session_dir = os.path.dirname(parent_jsonl_path)
    if not os.path.isdir(session_dir):
        return 0

    # Pull parent metadata once — also serves as the fast-fail check
    # that the parent JSONL parses.
    try:
        parent_meta = parse_meta(parent_jsonl_path) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "detect_and_record_subsessions: parent meta parse failed: %s", exc,
        )
        return 0
    if not parent_meta:
        return 0

    # Enumerate all sibling JSONLs in the same session_dir, parsing
    # metadata for each so we can call link_sub_to_parent.
    try:
        entries = os.listdir(session_dir)
    except OSError as exc:
        logger.debug(
            "detect_and_record_subsessions: listdir failed for %s: %s",
            session_dir, exc,
        )
        return 0

    sibling_metas: list[dict] = []
    for fname in entries:
        if not fname.endswith(".jsonl"):
            continue
        jsonl_path = os.path.join(session_dir, fname)
        try:
            md = parse_meta(jsonl_path)
        except Exception:  # noqa: BLE001
            continue
        if md:
            sibling_metas.append(md)

    if not sibling_metas:
        return 0

    db = SessionLocal()
    try:
        recorded = 0
        for sub_meta in sibling_metas:
            sub_sid = sub_meta.get("session_id")
            if not sub_sid or sub_sid == parent_session_id:
                continue
            sub_parent_uuid = sub_meta.get("parent_jsonl_uuid")
            # Top-level sessions have no parentUuid — skip; reconcile
            # owns those.
            if not sub_parent_uuid:
                continue

            # Skip if already linked to this parent (idempotent
            # short-circuit avoids doing the link_sub scan).
            existing = db.get(CCSession, sub_sid)
            if existing and existing.parent_session_id == parent_session_id:
                continue

            # Confirm the parent linkage. link_sub_to_parent accepts
            # the candidate list and returns the parent's session_id
            # if a UUID match is found in any candidate's JSONL.
            try:
                linked_parent_sid = link_sub(sub_meta, sibling_metas)
            except Exception:  # noqa: BLE001
                continue
            if linked_parent_sid != parent_session_id:
                continue

            sub_proj = project_path or parent_meta.get("project_path") or ""
            sub_wt = worktree or parent_meta.get("worktree")

            ok = upsert_cc_session(
                session_id=sub_sid,
                agent_id=parent_agent_id,
                project_path=sub_proj,
                parent_session_id=parent_session_id,
                parent_jsonl_uuid=sub_parent_uuid,
                worktree=sub_wt,
                is_subagent_session=True,
                started_at=_parse_iso_ts(sub_meta.get("started_at")),
                ended_at=_parse_iso_ts(sub_meta.get("ended_at")),
                end_reason="subagent_done",
                model=sub_meta.get("model"),
                totals={
                    "input_tokens": sub_meta.get("total_input_tokens", 0),
                    "output_tokens": sub_meta.get("total_output_tokens", 0),
                    "cache_creation_input_tokens": sub_meta.get(
                        "total_cache_creation_tokens", 0
                    ),
                    "cache_read_input_tokens": sub_meta.get(
                        "total_cache_read_tokens", 0
                    ),
                    "turn_count": sub_meta.get("turn_count", 0),
                },
            )
            if ok and existing is None:
                recorded += 1
        return recorded
    finally:
        db.close()
