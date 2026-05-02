"""Tests for context.lifetime — aggregation across history + current session.

Pure-logic tests: we drive the function with a temporary HISTORY_DIR and
JSONL fixture so no real DB or filesystem state is touched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from context import lifetime as lifetime_mod
from context.lifetime import get_lifetime
from context.pricing import compute_cost


@pytest.fixture()
def isolated_history(tmp_path, monkeypatch):
    """Point session_history.HISTORY_DIR at a temp dir for the test."""
    import session_history

    new_dir = tmp_path / "agent-sessions"
    new_dir.mkdir()
    monkeypatch.setattr(session_history, "HISTORY_DIR", str(new_dir))
    return new_dir


def _stub_resolve(jsonl_path):
    """Make `_resolve_session_jsonl` import succeed and return our fake path."""
    import agent_dispatcher

    def fake_resolve(session_id, project_path, worktree):
        return jsonl_path

    return fake_resolve


def test_empty_history_no_current_session_returns_zeros(isolated_history):
    """No history file, no current session_id."""
    res = get_lifetime(
        agent_id="aaaa11112222",
        model="claude-opus-4-7",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    assert res["session_count"] == 0
    assert res["history_session_count"] == 0
    assert res["turn_count"] == 0
    assert res["total_tokens"] == 0
    assert res["estimated_cost_usd"] == 0
    assert res["by_kind"]["input_tokens"] == 0
    assert res["by_kind"]["output_tokens"] == 0


def test_history_records_sum_correctly(isolated_history):
    """Two ended sessions → counts/usage sum across them."""
    from session_history import append_ended_session

    agent_id = "aaaa11112222"
    append_ended_session(
        agent_id, "sess-1", "/tmp/proj", None, "compact", "claude-opus-4-7",
        usage={
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 200,
        },
        turn_count=3,
    )
    append_ended_session(
        agent_id, "sess-2", "/tmp/proj", None, "clear", "claude-opus-4-7",
        usage={
            "input_tokens": 200,
            "output_tokens": 100,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 400,
        },
        turn_count=4,
    )

    res = get_lifetime(
        agent_id=agent_id,
        model="claude-opus-4-7",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    assert res["history_session_count"] == 2
    assert res["session_count"] == 2  # no current
    assert res["turn_count"] == 7
    assert res["by_kind"]["input_tokens"] == 300
    assert res["by_kind"]["output_tokens"] == 150
    assert res["by_kind"]["cache_creation_input_tokens"] == 30
    assert res["by_kind"]["cache_read_input_tokens"] == 600
    assert res["total_tokens"] == 1080


def test_combined_dict_has_four_expected_keys(isolated_history):
    res = get_lifetime(
        agent_id="aaaa11112222",
        model="claude-opus-4-7",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    assert set(res["by_kind"].keys()) == {
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    }


def test_cost_math_matches_pricing_module(isolated_history):
    """Lifetime cost must equal compute_cost(by_kind, model) rounded to 4 dp."""
    from session_history import append_ended_session

    agent_id = "bbbb22223333"
    usage = {
        "input_tokens": 12_345,
        "output_tokens": 6_789,
        "cache_creation_input_tokens": 1_111,
        "cache_read_input_tokens": 9_999,
    }
    append_ended_session(
        agent_id, "sess-x", "/tmp/proj", None, "stopped",
        "claude-opus-4-7", usage=usage, turn_count=2,
    )
    res = get_lifetime(
        agent_id=agent_id,
        model="claude-opus-4-7",
        project_path=None,
        worktree=None,
        current_session_id=None,
    )
    expected = round(compute_cost(usage, "claude-opus-4-7"), 4)
    assert res["estimated_cost_usd"] == expected


def test_turn_count_aggregates_history_plus_current(
    isolated_history, tmp_path, monkeypatch
):
    """History turn_count + JSONL turn_count = total."""
    from session_history import append_ended_session

    agent_id = "cccc33334444"
    append_ended_session(
        agent_id, "sess-old", "/tmp/proj", None, "compact",
        "claude-opus-4-7",
        usage={"input_tokens": 10, "output_tokens": 5,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        turn_count=2,
    )

    # Create a fake current-session JSONL with 3 assistant turns
    jsonl_path = tmp_path / "current.jsonl"
    with open(jsonl_path, "w") as f:
        for _ in range(3):
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-7",
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }) + "\n")

    # Stub _resolve_session_jsonl to return our fake JSONL
    import agent_dispatcher
    monkeypatch.setattr(
        agent_dispatcher,
        "_resolve_session_jsonl",
        lambda sid, pp, wt: str(jsonl_path),
    )

    res = get_lifetime(
        agent_id=agent_id,
        model="claude-opus-4-7",
        project_path="/tmp/proj",
        worktree=None,
        current_session_id="cur-session",
    )
    assert res["turn_count"] == 2 + 3
    assert res["history_session_count"] == 1
    assert res["session_count"] == 2  # 1 ended + 1 current
