"""Tests for the DB-backed get_lifetime path (cc_sessions table).

The new lifetime module reads primarily from ``cc_sessions`` and falls
back to the legacy file-history only when no DB rows exist for the
agent. We verify both paths plus the tree-building helper, the running
current-session overlay, and end-to-end cost math.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from context.lifetime import (
    build_cc_session_tree,
    get_lifetime,
)
from context.pricing import compute_cost
from models import Agent, AgentMode, AgentStatus, CCSession, Project


@pytest.fixture()
def isolated_history(tmp_path, monkeypatch):
    """Point session_history.HISTORY_DIR at a temp dir for the test."""
    import session_history

    new_dir = tmp_path / "agent-sessions"
    new_dir.mkdir()
    monkeypatch.setattr(session_history, "HISTORY_DIR", str(new_dir))
    return new_dir


@pytest.fixture()
def stub_session_local(monkeypatch, db_engine):
    """Make get_lifetime's `from database import SessionLocal` resolve to
    a sessionmaker bound to the in-memory db_engine fixture."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    import database
    monkeypatch.setattr(database, "SessionLocal", Session)
    return Session


def _seed_project_and_agent(db, agent_id="aaaa11112222", model="claude-opus-4-7"):
    proj = Project(name="proj-x", display_name="X", path="/tmp/x",
                   default_model=model)
    db.add(proj)
    db.flush()
    agent = Agent(
        id=agent_id,
        project="proj-x",
        name="A",
        mode=AgentMode.AUTO,
        status=AgentStatus.IDLE,
        model=model,
    )
    db.add(agent)
    db.commit()
    return agent


def _make_cc_session(
    db, *, session_id, agent_id,
    parent_session_id=None,
    is_subagent=False,
    end_reason="rotation",
    model="claude-opus-4-7",
    input_t=0, output_t=0, cache_create=0, cache_read=0,
    turns=0, started_at=None, ended_at=None,
):
    row = CCSession(
        session_id=session_id,
        agent_id=agent_id,
        parent_session_id=parent_session_id,
        project_path="/tmp/x",
        worktree=None,
        is_subagent_session=is_subagent,
        started_at=started_at or datetime.now(timezone.utc),
        ended_at=ended_at,
        end_reason=end_reason,
        model=model,
        total_input_tokens=input_t,
        total_output_tokens=output_t,
        total_cache_creation_tokens=cache_create,
        total_cache_read_tokens=cache_read,
        turn_count=turns,
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Fallback path
# ---------------------------------------------------------------------------
def test_empty_cc_sessions_falls_back_to_file_history(
    isolated_history, stub_session_local, db_session
):
    """No rows in cc_sessions, no history file → all zeros, empty tree."""
    _seed_project_and_agent(db_session)

    res = get_lifetime(
        agent_id="aaaa11112222",
        model="claude-opus-4-7",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    assert res["history_session_count"] == 0
    assert res["session_count"] == 0
    assert res["turn_count"] == 0
    assert res["total_tokens"] == 0
    assert res["estimated_cost_usd"] == 0
    assert res["cc_sessions"] == []
    # by_kind keys present
    assert set(res["by_kind"].keys()) == {
        "input_tokens", "output_tokens",
        "cache_creation_input_tokens", "cache_read_input_tokens",
    }


def test_empty_cc_sessions_with_file_history_still_aggregates(
    isolated_history, stub_session_local, db_session
):
    """With no DB rows but a populated history file we still get totals."""
    from session_history import append_ended_session

    _seed_project_and_agent(db_session, agent_id="bbbb22223333")
    append_ended_session(
        "bbbb22223333", "old-sess", "/tmp/x", None, "compact",
        "claude-opus-4-7",
        usage={
            "input_tokens": 100, "output_tokens": 50,
            "cache_creation_input_tokens": 10, "cache_read_input_tokens": 200,
        },
        turn_count=3,
    )

    res = get_lifetime(
        agent_id="bbbb22223333",
        model="claude-opus-4-7",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    assert res["history_session_count"] == 1
    assert res["session_count"] == 1
    assert res["turn_count"] == 3
    assert res["by_kind"]["input_tokens"] == 100
    assert res["by_kind"]["cache_read_input_tokens"] == 200
    assert res["cc_sessions"] == []  # no DB rows → empty tree


# ---------------------------------------------------------------------------
# DB-backed path
# ---------------------------------------------------------------------------
def test_one_top_level_session_aggregates_correctly(
    isolated_history, stub_session_local, db_session
):
    _seed_project_and_agent(db_session)
    _make_cc_session(
        db_session, session_id="sess-1", agent_id="aaaa11112222",
        end_reason="rotation",
        input_t=1000, output_t=500, cache_create=200, cache_read=4000,
        turns=10,
    )

    res = get_lifetime(
        agent_id="aaaa11112222",
        model="claude-opus-4-7",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    assert res["session_count"] == 1
    assert res["history_session_count"] == 1
    assert res["turn_count"] == 10
    assert res["by_kind"]["input_tokens"] == 1000
    assert res["by_kind"]["output_tokens"] == 500
    assert res["by_kind"]["cache_creation_input_tokens"] == 200
    assert res["by_kind"]["cache_read_input_tokens"] == 4000
    assert res["total_tokens"] == 5700
    assert len(res["cc_sessions"]) == 1
    assert res["cc_sessions"][0]["session_id"] == "sess-1"
    assert res["cc_sessions"][0]["sub_sessions"] == []


def test_top_level_with_two_subs_builds_tree_and_sums_totals(
    isolated_history, stub_session_local, db_session
):
    _seed_project_and_agent(db_session)
    _make_cc_session(
        db_session, session_id="parent", agent_id="aaaa11112222",
        end_reason="rotation",
        input_t=2000, output_t=1000, cache_create=0, cache_read=0,
        turns=20,
    )
    _make_cc_session(
        db_session, session_id="sub-a", agent_id="aaaa11112222",
        parent_session_id="parent", is_subagent=True,
        end_reason="subagent_done",
        input_t=300, output_t=100, cache_create=0, cache_read=0,
        turns=5,
    )
    _make_cc_session(
        db_session, session_id="sub-b", agent_id="aaaa11112222",
        parent_session_id="parent", is_subagent=True,
        end_reason="subagent_done",
        input_t=400, output_t=150, cache_create=0, cache_read=0,
        turns=7,
    )

    res = get_lifetime(
        agent_id="aaaa11112222",
        model="claude-opus-4-7",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    # Sub-sessions sum naturally — they all share agent_id
    assert res["by_kind"]["input_tokens"] == 2000 + 300 + 400
    assert res["by_kind"]["output_tokens"] == 1000 + 100 + 150
    assert res["turn_count"] == 20 + 5 + 7
    # Tree shape: 1 top-level with 2 subs
    assert res["session_count"] == 1
    assert len(res["cc_sessions"]) == 1
    parent = res["cc_sessions"][0]
    assert parent["session_id"] == "parent"
    assert len(parent["sub_sessions"]) == 2
    sub_ids = {s["session_id"] for s in parent["sub_sessions"]}
    assert sub_ids == {"sub-a", "sub-b"}
    assert all(s["is_subagent_session"] for s in parent["sub_sessions"])


def test_current_session_not_in_cc_sessions_overlays_running_total(
    isolated_history, stub_session_local, db_session, tmp_path, monkeypatch
):
    """Current session_id missing from cc_sessions → JSONL overlay added."""
    _seed_project_and_agent(db_session)
    _make_cc_session(
        db_session, session_id="sess-old", agent_id="aaaa11112222",
        end_reason="rotation",
        input_t=100, output_t=50, cache_create=0, cache_read=0,
        turns=3,
    )

    # Fake JSONL with two assistant turns of usage
    jsonl_path = tmp_path / "current.jsonl"
    with open(jsonl_path, "w") as f:
        for _ in range(2):
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-7",
                    "usage": {
                        "input_tokens": 7,
                        "output_tokens": 3,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }) + "\n")

    import agent_dispatcher
    monkeypatch.setattr(
        agent_dispatcher, "_resolve_session_jsonl",
        lambda sid, pp, wt: str(jsonl_path),
    )

    res = get_lifetime(
        agent_id="aaaa11112222",
        model="claude-opus-4-7",
        project_path="/tmp/x",
        worktree=None,
        current_session_id="sess-current-not-in-db",
    )
    # Overlay adds 2 turns × (7 input + 3 output)
    assert res["by_kind"]["input_tokens"] == 100 + 14
    assert res["by_kind"]["output_tokens"] == 50 + 6
    assert res["turn_count"] == 3 + 2
    # Tree contains the synthetic node with end_reason=active
    ids = [s["session_id"] for s in res["cc_sessions"]]
    assert "sess-current-not-in-db" in ids
    active = next(
        s for s in res["cc_sessions"]
        if s["session_id"] == "sess-current-not-in-db"
    )
    assert active["end_reason"] == "active"


def test_pricing_model_resolved_in_payload(
    isolated_history, stub_session_local, db_session
):
    """pricing_model passes through unchanged; pricing_per_million reflects it."""
    _seed_project_and_agent(db_session, model="claude-sonnet-4-6")
    _make_cc_session(
        db_session, session_id="s1", agent_id="aaaa11112222",
        model="claude-sonnet-4-6",
        input_t=1000, output_t=500,
        turns=2,
    )
    res = get_lifetime(
        agent_id="aaaa11112222",
        model="claude-sonnet-4-6",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    assert res["pricing_model"] == "claude-sonnet-4-6"
    # Sonnet rates differ from Opus — sanity check the lookup
    assert res["pricing_per_million"]["input"] == 3.00
    assert res["pricing_per_million"]["output"] == 15.00


def test_end_to_end_cost_math_matches_compute_cost(
    isolated_history, stub_session_local, db_session
):
    """Insert real rows, query lifetime, verify the rounded cost equals
    compute_cost(by_kind)."""
    _seed_project_and_agent(db_session)
    _make_cc_session(
        db_session, session_id="p1", agent_id="aaaa11112222",
        input_t=12_345, output_t=6_789,
        cache_create=1_111, cache_read=9_999,
        turns=2,
    )
    _make_cc_session(
        db_session, session_id="sub", agent_id="aaaa11112222",
        parent_session_id="p1", is_subagent=True,
        end_reason="subagent_done",
        input_t=500, output_t=200, cache_create=0, cache_read=10,
        turns=1,
    )
    res = get_lifetime(
        agent_id="aaaa11112222",
        model="claude-opus-4-7",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    expected = round(compute_cost(res["by_kind"], "claude-opus-4-7"), 4)
    assert res["estimated_cost_usd"] == expected
    # And cc_sessions key is always present in DB-backed path
    assert "cc_sessions" in res


# ---------------------------------------------------------------------------
# Tree-builder unit test
# ---------------------------------------------------------------------------
def test_build_cc_session_tree_orphan_subs_promoted_to_top_level():
    """A sub whose parent_session_id has no matching row should not vanish.

    Uses an unsaved CCSession instance so we don't trip the FK constraint
    on parent_session_id — the helper must work on whatever rows it gets.
    """
    orphan = CCSession(
        session_id="orphan-sub",
        agent_id="aaaa11112222",
        parent_session_id="ghost-parent",  # ghost: not in row set
        project_path="/tmp/x",
        is_subagent_session=True,
        end_reason="subagent_done",
        model="claude-opus-4-7",
        total_input_tokens=10,
        total_output_tokens=5,
        total_cache_creation_tokens=0,
        total_cache_read_tokens=0,
        turn_count=1,
    )
    tree = build_cc_session_tree([orphan], "claude-opus-4-7")
    assert len(tree) == 1
    assert tree[0]["session_id"] == "orphan-sub"
