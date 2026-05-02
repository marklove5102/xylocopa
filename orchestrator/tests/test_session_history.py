"""Tests for session_history — per-agent ended-session aggregation."""
from __future__ import annotations

import json

import pytest


@pytest.fixture()
def isolated_history(tmp_path, monkeypatch):
    """Point session_history.HISTORY_DIR at a temp dir for the test."""
    import session_history

    new_dir = tmp_path / "agent-sessions"
    new_dir.mkdir()
    monkeypatch.setattr(session_history, "HISTORY_DIR", str(new_dir))
    return new_dir


def test_append_ended_session_writes_jsonl_line(isolated_history):
    from session_history import _history_file, append_ended_session

    ok = append_ended_session(
        agent_id="aaaa11112222",
        session_id="sess-1",
        project_path="/tmp/proj",
        worktree=None,
        end_reason="compact",
        model="claude-opus-4-7",
        usage={"input_tokens": 100, "output_tokens": 50,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        turn_count=3,
        started_at="2025-01-01T00:00:00Z",
    )
    assert ok is True

    # File should exist with exactly one line of valid JSON
    path = _history_file("aaaa11112222")
    with open(path) as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["session_id"] == "sess-1"
    assert rec["end_reason"] == "compact"
    assert rec["turn_count"] == 3


def test_read_history_reads_what_was_written(isolated_history):
    from session_history import append_ended_session, read_history

    append_ended_session(
        "agent-x", "sess-a", "/tmp/p", None, "clear",
        "claude-opus-4-7",
        {"input_tokens": 10, "output_tokens": 5,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        turn_count=1,
    )
    append_ended_session(
        "agent-x", "sess-b", "/tmp/p", None, "stopped",
        "claude-sonnet-4-6",
        {"input_tokens": 20, "output_tokens": 7,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        turn_count=2,
    )

    history = read_history("agent-x")
    assert len(history) == 2
    assert history[0]["session_id"] == "sess-a"
    assert history[1]["session_id"] == "sess-b"
    assert history[1]["model"] == "claude-sonnet-4-6"


def test_sum_history_usage_aggregates_correctly(isolated_history):
    from session_history import append_ended_session, sum_history_usage

    append_ended_session(
        "agent-y", "s1", "/tmp/p", None, "compact", "claude-opus-4-7",
        {"input_tokens": 100, "output_tokens": 50,
         "cache_creation_input_tokens": 10, "cache_read_input_tokens": 200},
        turn_count=3,
    )
    append_ended_session(
        "agent-y", "s2", "/tmp/p", None, "clear", "claude-opus-4-7",
        {"input_tokens": 200, "output_tokens": 100,
         "cache_creation_input_tokens": 20, "cache_read_input_tokens": 400},
        turn_count=5,
    )
    append_ended_session(
        "agent-y", "s3", "/tmp/p", None, "stopped", "claude-opus-4-7",
        {"input_tokens": 50, "output_tokens": 25,
         "cache_creation_input_tokens": 5, "cache_read_input_tokens": 100},
        turn_count=2,
    )

    cum = sum_history_usage("agent-y")
    assert cum["input_tokens"] == 350
    assert cum["output_tokens"] == 175
    assert cum["cache_creation_input_tokens"] == 35
    assert cum["cache_read_input_tokens"] == 700
    assert cum["sessions"] == 3
    assert cum["turn_count"] == 10


def test_remove_history_deletes_file(isolated_history):
    from session_history import (
        _history_file,
        append_ended_session,
        remove_history,
    )
    import os

    append_ended_session(
        "agent-z", "s1", "/tmp/p", None, "compact", "claude-opus-4-7",
        {"input_tokens": 1, "output_tokens": 1,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        turn_count=1,
    )
    path = _history_file("agent-z")
    assert os.path.isfile(path)

    assert remove_history("agent-z") is True
    assert not os.path.isfile(path)


def test_remove_history_idempotent_on_missing_file(isolated_history):
    from session_history import remove_history

    # Never appended — file does not exist.
    assert remove_history("nonexistent-agent") is True
    # Calling again still returns True.
    assert remove_history("nonexistent-agent") is True


def test_sum_jsonl_usage_extracts_assistant_blocks(tmp_path):
    """Synthetic JSONL with mixed entries — only assistant-with-usage counts."""
    from session_history import sum_jsonl_usage

    jsonl_path = tmp_path / "fixture.jsonl"
    with open(jsonl_path, "w") as f:
        # User entry — should be skipped
        f.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        # Assistant with usage
        f.write(json.dumps({
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 100,
                },
            },
        }) + "\n")
        # Assistant without usage — skipped
        f.write(json.dumps({
            "type": "assistant",
            "message": {"content": "no-usage"},
        }) + "\n")
        # Another assistant with usage
        f.write(json.dumps({
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 10,
                    "cache_creation_input_tokens": 5,
                    "cache_read_input_tokens": 50,
                },
            },
        }) + "\n")
        # Garbage line — silently skipped
        f.write("not-json\n")

    cum = sum_jsonl_usage(str(jsonl_path))
    assert cum["input_tokens"] == 30
    assert cum["output_tokens"] == 15
    assert cum["cache_creation_input_tokens"] == 5
    assert cum["cache_read_input_tokens"] == 150
    assert cum["turn_count"] == 2


def test_sum_jsonl_usage_missing_file_returns_zeros():
    from session_history import sum_jsonl_usage

    cum = sum_jsonl_usage("/nonexistent/path.jsonl")
    assert cum["input_tokens"] == 0
    assert cum["turn_count"] == 0
