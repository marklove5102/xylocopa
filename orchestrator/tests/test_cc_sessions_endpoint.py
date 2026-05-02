"""Tests for GET /api/agents/{agent_id}/cc-sessions.

Integration tests that exercise the FastAPI route through the ASGI
TestClient. We seed the in-memory DB directly via the same engine the
client wraps, then assert on JSON shape and tree nesting.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from models import Agent, AgentMode, AgentStatus, CCSession, Project


def _seed(db_engine, agent_id="aaaa11112222"):
    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    try:
        db.add(Project(name="proj-z", display_name="Z", path="/tmp/z",
                       default_model="claude-opus-4-7"))
        db.flush()
        db.add(Agent(
            id=agent_id,
            project="proj-z",
            name="A",
            mode=AgentMode.AUTO,
            status=AgentStatus.IDLE,
            model="claude-opus-4-7",
        ))
        db.commit()
    finally:
        db.close()


def _add_cc_session(db_engine, **kwargs):
    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    try:
        defaults = dict(
            project_path="/tmp/z",
            worktree=None,
            is_subagent_session=False,
            started_at=datetime.now(timezone.utc),
            ended_at=None,
            end_reason="rotation",
            model="claude-opus-4-7",
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_creation_tokens=0,
            total_cache_read_tokens=0,
            turn_count=0,
            parent_session_id=None,
        )
        defaults.update(kwargs)
        row = CCSession(**defaults)
        db.add(row)
        db.commit()
    finally:
        db.close()


@pytest.mark.anyio
async def test_unknown_agent_returns_404(client):
    resp = await client.get("/api/agents/nonexistent1/cc-sessions")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_known_agent_with_no_sessions_returns_empty_tree(
    client, db_engine
):
    _seed(db_engine)
    resp = await client.get("/api/agents/aaaa11112222/cc-sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"sessions": []}


@pytest.mark.anyio
async def test_returns_top_level_sessions_for_agent(client, db_engine):
    _seed(db_engine)
    _add_cc_session(
        db_engine, session_id="top-1", agent_id="aaaa11112222",
        end_reason="rotation",
        total_input_tokens=1000, total_output_tokens=500,
        turn_count=10,
    )
    _add_cc_session(
        db_engine, session_id="top-2", agent_id="aaaa11112222",
        end_reason="compact",
        total_input_tokens=200, total_output_tokens=80,
        turn_count=4,
    )

    resp = await client.get("/api/agents/aaaa11112222/cc-sessions")
    assert resp.status_code == 200
    body = resp.json()
    sessions = body["sessions"]
    assert len(sessions) == 2
    ids = {s["session_id"] for s in sessions}
    assert ids == {"top-1", "top-2"}
    # Each top-level row has expected keys + empty sub_sessions
    for s in sessions:
        assert "started_at" in s
        assert "end_reason" in s
        assert "totals" in s
        assert "cost_usd" in s
        assert "turn_count" in s
        assert s["sub_sessions"] == []


@pytest.mark.anyio
async def test_sub_sessions_nested_under_parent(client, db_engine):
    _seed(db_engine)
    _add_cc_session(
        db_engine, session_id="parent", agent_id="aaaa11112222",
        end_reason="rotation",
        total_input_tokens=500, total_output_tokens=200,
        turn_count=8,
    )
    _add_cc_session(
        db_engine, session_id="child-a", agent_id="aaaa11112222",
        parent_session_id="parent", is_subagent_session=True,
        end_reason="subagent_done",
        total_input_tokens=20, total_output_tokens=10, turn_count=1,
    )
    _add_cc_session(
        db_engine, session_id="child-b", agent_id="aaaa11112222",
        parent_session_id="parent", is_subagent_session=True,
        end_reason="subagent_done",
        total_input_tokens=30, total_output_tokens=15, turn_count=2,
    )

    resp = await client.get("/api/agents/aaaa11112222/cc-sessions")
    assert resp.status_code == 200
    body = resp.json()
    sessions = body["sessions"]
    # Parent appears at top level; both subs nested underneath
    assert len(sessions) == 1
    parent = sessions[0]
    assert parent["session_id"] == "parent"
    assert len(parent["sub_sessions"]) == 2
    sub_ids = {s["session_id"] for s in parent["sub_sessions"]}
    assert sub_ids == {"child-a", "child-b"}
    for sub in parent["sub_sessions"]:
        assert sub["is_subagent_session"] is True
        assert sub["end_reason"] == "subagent_done"
