"""Tests for cc_session_writer — INSERT/UPDATE helpers for cc_sessions.

These tests pin SessionLocal to an in-memory DB engine via monkeypatch
(same pattern used by test_sync_sent_to_delivered) and exercise the
public surface: ``upsert_cc_session``, ``mark_session_ended``, plus FK
ON DELETE SET NULL behavior.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from models import (
    Agent,
    AgentMode,
    AgentStatus,
    CCSession,
    Project,
)


def _fresh(n: int = 12) -> str:
    return uuid.uuid4().hex[:n]


@pytest.fixture()
def cc_env(db_engine, monkeypatch):
    """Wire cc_session_writer.SessionLocal to the in-memory test engine."""
    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr("database.SessionLocal", Session)
    monkeypatch.setattr("cc_session_writer.SessionLocal", Session)

    db = Session()
    try:
        db.add(Project(
            name="cc-proj",
            display_name="CC Test Project",
            path="/tmp/cc-proj",
            default_model="claude-opus-4-7",
        ))
        db.flush()
        agent_id = _fresh()
        db.add(Agent(
            id=agent_id,
            project="cc-proj",
            name="Test Agent",
            mode=AgentMode.AUTO,
            status=AgentStatus.IDLE,
            model="claude-opus-4-7",
        ))
        db.commit()
    finally:
        db.close()

    return {"Session": Session, "agent_id": agent_id}


# ---------------------------------------------------------------------------
# upsert_cc_session — INSERT path
# ---------------------------------------------------------------------------

def test_upsert_inserts_new_row(cc_env):
    """upsert_cc_session creates a row when session_id is unseen."""
    import cc_session_writer as _ccw

    sid = "sess-" + _fresh()
    aid = cc_env["agent_id"]
    started = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)

    result = _ccw.upsert_cc_session(
        session_id=sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
        started_at=started,
        end_reason="active",
        model="claude-opus-4-7",
        totals={
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 5,
            "turn_count": 3,
        },
    )
    assert result == sid

    db = cc_env["Session"]()
    try:
        row = db.get(CCSession, sid)
        assert row is not None
        assert row.agent_id == aid
        assert row.project_path == "/tmp/cc-proj"
        assert row.end_reason == "active"
        assert row.model == "claude-opus-4-7"
        assert row.total_input_tokens == 100
        assert row.total_output_tokens == 50
        assert row.total_cache_creation_tokens == 10
        assert row.total_cache_read_tokens == 5
        assert row.turn_count == 3
        assert row.is_subagent_session is False
        # SQLite drops tzinfo on storage — compare as naive UTC
        assert row.started_at.replace(tzinfo=timezone.utc) == started
    finally:
        db.close()


# ---------------------------------------------------------------------------
# upsert_cc_session — UPDATE path
# ---------------------------------------------------------------------------

def test_upsert_updates_existing_row(cc_env):
    """upsert overwrites totals but preserves fields when args are None."""
    import cc_session_writer as _ccw

    sid = "sess-" + _fresh()
    aid = cc_env["agent_id"]
    started = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Initial insert with model + started_at + totals.
    _ccw.upsert_cc_session(
        session_id=sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
        started_at=started,
        end_reason="active",
        model="claude-opus-4-7",
        totals={"input": 10, "output": 5, "cache_creation": 1,
                "cache_read": 0, "turn_count": 1},
    )

    # Update with ONLY new totals — model, started_at, end_reason should
    # remain. Token totals overwrite (they are always provided fresh).
    result = _ccw.upsert_cc_session(
        session_id=sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
        totals={"input": 200, "output": 100, "cache_creation": 20,
                "cache_read": 10, "turn_count": 7},
    )
    assert result == sid

    db = cc_env["Session"]()
    try:
        row = db.get(CCSession, sid)
        assert row.total_input_tokens == 200
        assert row.total_output_tokens == 100
        assert row.total_cache_creation_tokens == 20
        assert row.total_cache_read_tokens == 10
        assert row.turn_count == 7
        # Preserved fields
        assert row.started_at.replace(tzinfo=timezone.utc) == started
        assert row.end_reason == "active"
        assert row.model == "claude-opus-4-7"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# mark_session_ended
# ---------------------------------------------------------------------------

def test_mark_session_ended_sets_end_fields(cc_env):
    """mark_session_ended sets ended_at + end_reason and can update totals."""
    import cc_session_writer as _ccw

    sid = "sess-" + _fresh()
    aid = cc_env["agent_id"]

    _ccw.upsert_cc_session(
        session_id=sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
        end_reason="active",
    )

    ok = _ccw.mark_session_ended(
        sid, "rotation",
        totals={"input": 1, "output": 2, "cache_creation": 3,
                "cache_read": 4, "turn_count": 9},
    )
    assert ok is True

    db = cc_env["Session"]()
    try:
        row = db.get(CCSession, sid)
        assert row.ended_at is not None
        assert row.end_reason == "rotation"
        assert row.total_input_tokens == 1
        assert row.total_output_tokens == 2
        assert row.total_cache_creation_tokens == 3
        assert row.total_cache_read_tokens == 4
        assert row.turn_count == 9
    finally:
        db.close()

    # Marking a non-existent session returns False (graceful).
    assert _ccw.mark_session_ended("does-not-exist", "rotation") is False


# ---------------------------------------------------------------------------
# Error handling — DB exception inside upsert returns gracefully
# ---------------------------------------------------------------------------

def test_upsert_swallows_db_exception(cc_env, monkeypatch):
    """A DB error inside the upsert path is logged, not raised."""
    import cc_session_writer as _ccw
    from sqlalchemy.exc import OperationalError

    class _BoomSession:
        def __init__(self, *_a, **_kw):
            pass

        def get(self, *_a, **_kw):
            raise OperationalError("boom", {}, Exception("boom"))

        def add(self, *_a, **_kw):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("cc_session_writer.SessionLocal", _BoomSession)

    result = _ccw.upsert_cc_session(
        session_id="sess-x",
        agent_id=cc_env["agent_id"],
        project_path="/tmp/cc-proj",
    )
    assert result is None  # graceful failure


# ---------------------------------------------------------------------------
# FK ON DELETE SET NULL — parent_session_id
# ---------------------------------------------------------------------------

def test_parent_fk_set_null_on_parent_delete(cc_env):
    """Deleting the parent CCSession nulls children's parent_session_id."""
    import cc_session_writer as _ccw

    parent_sid = "parent-" + _fresh()
    child_sid = "child-" + _fresh()
    aid = cc_env["agent_id"]

    _ccw.upsert_cc_session(
        session_id=parent_sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
        end_reason="active",
    )
    _ccw.upsert_cc_session(
        session_id=child_sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
        parent_session_id=parent_sid,
        is_subagent_session=True,
        end_reason="subagent_done",
    )

    # Delete the parent through SQLAlchemy directly. PRAGMA
    # foreign_keys=ON is enabled in the conftest engine, so SET NULL
    # should propagate to the child.
    db = cc_env["Session"]()
    try:
        parent_row = db.get(CCSession, parent_sid)
        db.delete(parent_row)
        db.commit()
    finally:
        db.close()

    db = cc_env["Session"]()
    try:
        child = db.get(CCSession, child_sid)
        assert child is not None  # child still exists
        assert child.parent_session_id is None  # FK was set to NULL
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Concurrent upsert with same session_id → no duplicate rows
# ---------------------------------------------------------------------------

def test_concurrent_upsert_no_duplicates(cc_env):
    """Calling upsert twice with the same session_id is idempotent."""
    import cc_session_writer as _ccw

    sid = "sess-" + _fresh()
    aid = cc_env["agent_id"]

    for _ in range(3):
        _ccw.upsert_cc_session(
            session_id=sid,
            agent_id=aid,
            project_path="/tmp/cc-proj",
            end_reason="active",
            totals={"input": 5, "output": 5, "cache_creation": 0,
                    "cache_read": 0, "turn_count": 1},
        )

    db = cc_env["Session"]()
    try:
        rows = db.query(CCSession).filter(
            CCSession.session_id == sid
        ).all()
        assert len(rows) == 1
        assert rows[0].total_input_tokens == 5
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Minimal-args insert
# ---------------------------------------------------------------------------

def test_minimal_args_insert(cc_env):
    """All-None optional args still records a minimal row (PK + agent + path)."""
    import cc_session_writer as _ccw

    sid = "sess-" + _fresh()
    aid = cc_env["agent_id"]

    result = _ccw.upsert_cc_session(
        session_id=sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
    )
    assert result == sid

    db = cc_env["Session"]()
    try:
        row = db.get(CCSession, sid)
        assert row is not None
        assert row.agent_id == aid
        assert row.project_path == "/tmp/cc-proj"
        # Optional fields are None / defaults
        assert row.started_at is None
        assert row.ended_at is None
        assert row.end_reason is None
        assert row.model is None
        assert row.parent_session_id is None
        assert row.is_subagent_session is False
        # Totals default to zero
        assert row.total_input_tokens == 0
        assert row.total_output_tokens == 0
        assert row.total_cache_creation_tokens == 0
        assert row.total_cache_read_tokens == 0
        assert row.turn_count == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Token totals can be 0
# ---------------------------------------------------------------------------

def test_token_totals_can_be_zero(cc_env):
    """Explicit zero totals are written as 0 (not skipped or coerced)."""
    import cc_session_writer as _ccw

    sid = "sess-" + _fresh()
    aid = cc_env["agent_id"]

    _ccw.upsert_cc_session(
        session_id=sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
        totals={
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "turn_count": 0,
        },
    )

    db = cc_env["Session"]()
    try:
        row = db.get(CCSession, sid)
        assert row.total_input_tokens == 0
        assert row.total_output_tokens == 0
        assert row.total_cache_creation_tokens == 0
        assert row.total_cache_read_tokens == 0
        assert row.turn_count == 0
    finally:
        db.close()

    # And update with non-zero, then back to zero — totals overwrite
    # (no "preserve previous nonzero" sticky behavior).
    _ccw.upsert_cc_session(
        session_id=sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
        totals={"input": 99, "output": 0, "cache_creation": 0,
                "cache_read": 0, "turn_count": 0},
    )
    _ccw.upsert_cc_session(
        session_id=sid,
        agent_id=aid,
        project_path="/tmp/cc-proj",
        totals={"input": 0, "output": 0, "cache_creation": 0,
                "cache_read": 0, "turn_count": 0},
    )

    db = cc_env["Session"]()
    try:
        row = db.get(CCSession, sid)
        assert row.total_input_tokens == 0
    finally:
        db.close()
