"""Tests for cc_session_reconcile — JSONL → cc_sessions inserts/updates.

Synthesizes JSONLs in tmp_path, monkey-patches
``cc_session_discovery.session_source_dir`` so the discovery module
points at our fake dir, and asserts the resulting CCSession rows.
"""
from __future__ import annotations

import json

import pytest

from models import Agent, AgentMode, AgentStatus, CCSession, Project


def _write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _top_entries(session_id, parent_uuid=None, *, last_uuid="last-uuid",
                 input_tok=10, output_tok=5):
    return [
        {
            "parentUuid": parent_uuid,
            "type": "user",
            "uuid": "first-uuid-" + session_id,
            "timestamp": "2026-04-01T00:00:00.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": "hi"},
        },
        {
            "parentUuid": "first-uuid-" + session_id,
            "type": "assistant",
            "uuid": last_uuid,
            "timestamp": "2026-04-01T00:00:01.000Z",
            "sessionId": session_id,
            "message": {
                "model": "claude-opus-4-7",
                "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {
                    "input_tokens": input_tok,
                    "output_tokens": output_tok,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        },
    ]


@pytest.fixture()
def reconcile_env(tmp_path, monkeypatch, db_session):
    """Wire a sample Project + Agent into the test DB and point discovery
    at a tmp session_dir. Returns an object with the bits each test needs.
    """
    project_path = tmp_path / "fake-project"
    project_path.mkdir()
    session_dir = tmp_path / "session-dir"
    session_dir.mkdir()

    proj = Project(
        name="test-proj",
        display_name="Test Proj",
        path=str(project_path),
        max_concurrent=2,
        default_model="claude-opus-4-7",
    )
    db_session.add(proj)
    db_session.commit()

    agent = Agent(
        id="agent-cc-01",
        project="test-proj",
        name="cc test agent",
        mode=AgentMode.AUTO,
        status=AgentStatus.IDLE,
        model="claude-opus-4-7",
    )
    db_session.add(agent)
    db_session.commit()

    monkeypatch.setattr(
        "cc_session_discovery.session_source_dir",
        lambda p: str(session_dir),
    )

    # Force reconcile_all/reconcile_agent to use the test DB session
    # rather than allocating its own SessionLocal() (which would hit the
    # real on-disk SQLite file).
    monkeypatch.setattr(
        "cc_session_reconcile.SessionLocal",
        lambda: db_session,
    )
    # Block the inner close() on the test session — db_session fixture
    # owns the lifetime.
    monkeypatch.setattr(db_session, "close", lambda: None)

    return type("E", (), {
        "project_path": project_path,
        "session_dir": session_dir,
        "agent_id": agent.id,
        "db": db_session,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_reconcile_empty_project_inserts_nothing(reconcile_env):
    from cc_session_reconcile import reconcile_agent

    counts = reconcile_agent(reconcile_env.agent_id)
    assert counts["discovered"] == 0
    assert counts["inserted"] == 0
    assert counts["updated"] == 0
    rows = reconcile_env.db.query(CCSession).all()
    assert rows == []


def test_reconcile_two_owned_top_level_sessions(reconcile_env):
    from cc_session_reconcile import reconcile_agent

    sdir = reconcile_env.session_dir
    aid = reconcile_env.agent_id

    _write_jsonl(sdir / "s-A.jsonl", _top_entries("s-A", input_tok=10, output_tok=5))
    _write_jsonl(sdir / "s-B.jsonl", _top_entries("s-B", input_tok=20, output_tok=8))
    (sdir / "s-A.owner").write_text(json.dumps({"agent_id": aid}))
    (sdir / "s-B.owner").write_text(json.dumps({"agent_id": aid}))

    counts = reconcile_agent(aid)
    assert counts["discovered"] == 2
    assert counts["inserted"] == 2

    rows = {r.session_id: r for r in reconcile_env.db.query(CCSession).all()}
    assert set(rows) == {"s-A", "s-B"}
    for r in rows.values():
        assert r.agent_id == aid
        assert r.is_subagent_session is False
        assert r.parent_session_id is None
        assert r.model == "claude-opus-4-7"
    assert rows["s-A"].total_input_tokens == 10
    assert rows["s-A"].total_output_tokens == 5
    assert rows["s-B"].total_input_tokens == 20
    assert rows["s-B"].total_output_tokens == 8


def test_reconcile_skips_unowned_top_level(reconcile_env):
    """Top-level JSONLs whose .owner sidecar names a different agent are skipped."""
    from cc_session_reconcile import reconcile_agent

    sdir = reconcile_env.session_dir
    _write_jsonl(sdir / "s-mine.jsonl", _top_entries("s-mine"))
    _write_jsonl(sdir / "s-foreign.jsonl", _top_entries("s-foreign"))
    (sdir / "s-mine.owner").write_text(
        json.dumps({"agent_id": reconcile_env.agent_id})
    )
    (sdir / "s-foreign.owner").write_text(
        json.dumps({"agent_id": "some-other-agent"})
    )

    counts = reconcile_agent(reconcile_env.agent_id)
    assert counts["discovered"] == 2
    assert counts["inserted"] == 1

    rows = reconcile_env.db.query(CCSession).all()
    assert len(rows) == 1
    assert rows[0].session_id == "s-mine"


def test_reconcile_links_sub_session_to_parent(reconcile_env):
    """Sub-session whose first entry's parentUuid matches an entry in the
    parent JSONL gets its parent_session_id wired up."""
    from cc_session_reconcile import reconcile_agent

    sdir = reconcile_env.session_dir
    aid = reconcile_env.agent_id

    # Parent JSONL: include a tool_use-like entry with a known uuid.
    parent_entries = _top_entries("s-parent", last_uuid="tool-use-marker")
    _write_jsonl(sdir / "s-parent.jsonl", parent_entries)
    (sdir / "s-parent.owner").write_text(json.dumps({"agent_id": aid}))

    # Sub-session: parentUuid points at the marker.
    sub_entries = _top_entries("s-sub", parent_uuid="tool-use-marker")
    _write_jsonl(sdir / "s-sub.jsonl", sub_entries)
    # No .owner sidecar for the sub — ownership is inherited via the
    # parent_jsonl_uuid chain.

    counts = reconcile_agent(aid)
    assert counts["discovered"] == 2
    assert counts["inserted"] == 2

    rows = {r.session_id: r for r in reconcile_env.db.query(CCSession).all()}
    assert rows["s-parent"].parent_session_id is None
    assert rows["s-parent"].is_subagent_session is False
    assert rows["s-sub"].parent_session_id == "s-parent"
    assert rows["s-sub"].is_subagent_session is True
    assert rows["s-sub"].parent_jsonl_uuid == "tool-use-marker"


def test_reconcile_is_idempotent(reconcile_env):
    """Re-running on the same disk state should insert 0 new rows."""
    from cc_session_reconcile import reconcile_agent

    sdir = reconcile_env.session_dir
    aid = reconcile_env.agent_id

    _write_jsonl(sdir / "s-X.jsonl", _top_entries("s-X"))
    (sdir / "s-X.owner").write_text(json.dumps({"agent_id": aid}))

    first = reconcile_agent(aid)
    assert first["inserted"] == 1
    assert first["skipped"] == 0

    second = reconcile_agent(aid)
    assert second["inserted"] == 0
    assert second["skipped"] == 1

    assert reconcile_env.db.query(CCSession).count() == 1


def test_reconcile_updates_token_totals_when_jsonl_grows(reconcile_env):
    """If the JSONL gains a new assistant turn between sweeps, the row's
    token totals + ended_at + turn_count must update; metadata stays put."""
    from cc_session_reconcile import reconcile_agent

    sdir = reconcile_env.session_dir
    aid = reconcile_env.agent_id

    # Initial: 1 turn (10 / 5).
    _write_jsonl(sdir / "s-grow.jsonl",
                 _top_entries("s-grow", input_tok=10, output_tok=5))
    (sdir / "s-grow.owner").write_text(json.dumps({"agent_id": aid}))

    reconcile_agent(aid)
    row = reconcile_env.db.query(CCSession).filter_by(session_id="s-grow").one()
    assert row.total_input_tokens == 10
    assert row.total_output_tokens == 5
    assert row.turn_count == 1
    initial_started_at = row.started_at

    # Append another assistant turn.
    extra_entry = {
        "parentUuid": "last-uuid",
        "type": "assistant",
        "uuid": "new-turn",
        "timestamp": "2026-04-01T00:01:00.000Z",
        "sessionId": "s-grow",
        "message": {
            "model": "claude-opus-4-7",
            "role": "assistant",
            "content": [{"type": "text", "text": "more"}],
            "usage": {
                "input_tokens": 50,
                "output_tokens": 25,
                "cache_creation_input_tokens": 5,
                "cache_read_input_tokens": 9,
            },
        },
    }
    with open(sdir / "s-grow.jsonl", "a") as f:
        f.write(json.dumps(extra_entry) + "\n")

    counts = reconcile_agent(aid)
    assert counts["updated"] == 1
    assert counts["inserted"] == 0

    reconcile_env.db.refresh(row)
    assert row.total_input_tokens == 60
    assert row.total_output_tokens == 30
    assert row.total_cache_creation_tokens == 5
    assert row.total_cache_read_tokens == 9
    assert row.turn_count == 2
    # Metadata stays put (started_at not overwritten by reconcile).
    assert row.started_at == initial_started_at
