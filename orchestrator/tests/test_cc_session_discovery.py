"""Tests for cc_session_discovery — pure read functions.

Synthetic JSONLs only. No real ``~/.claude/`` files are touched.
"""
from __future__ import annotations

import json
import os

import pytest


def _write_jsonl(path, entries):
    """Write a list of dicts as a JSONL file."""
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _top_level_entries(session_id="s-top-1"):
    """A minimal but realistic top-level CC session."""
    return [
        # First entry has parentUuid=None — this is the marker for top-level
        {
            "parentUuid": None,
            "isSidechain": False,
            "type": "user",
            "uuid": "u-first-001",
            "timestamp": "2026-04-01T00:00:00.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": "hello"},
            "cwd": "/tmp/proj",
        },
        {
            "parentUuid": "u-first-001",
            "type": "assistant",
            "uuid": "a-001",
            "timestamp": "2026-04-01T00:00:01.000Z",
            "sessionId": session_id,
            "message": {
                "model": "claude-opus-4-7",
                "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 100,
                    "cache_read_input_tokens": 200,
                },
            },
        },
        {
            "parentUuid": "a-001",
            "type": "user",
            "uuid": "u-002",
            "timestamp": "2026-04-01T00:00:02.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": "more"},
        },
        {
            "parentUuid": "u-002",
            "type": "assistant",
            "uuid": "a-002",
            "timestamp": "2026-04-01T00:00:05.000Z",
            "sessionId": session_id,
            "message": {
                "model": "claude-opus-4-7",
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 7,
                    "cache_creation_input_tokens": 50,
                    "cache_read_input_tokens": 300,
                },
            },
        },
    ]


def _sub_session_entries(parent_uuid, session_id="s-sub-1"):
    """A sub-session whose first entry's parentUuid points back at the parent JSONL."""
    return [
        {
            "parentUuid": parent_uuid,
            "isSidechain": True,
            "type": "user",
            "uuid": "sub-u-001",
            "timestamp": "2026-04-01T00:00:10.000Z",
            "sessionId": session_id,
            "message": {"role": "user", "content": "sub task"},
        },
        {
            "parentUuid": "sub-u-001",
            "type": "assistant",
            "uuid": "sub-a-001",
            "timestamp": "2026-04-01T00:00:12.000Z",
            "sessionId": session_id,
            "message": {
                "model": "claude-sonnet-4-6",
                "role": "assistant",
                "content": [{"type": "text", "text": "sub done"}],
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# parse_jsonl_metadata
# ---------------------------------------------------------------------------

def test_parse_top_level_jsonl_returns_metadata(tmp_path):
    from cc_session_discovery import parse_jsonl_metadata

    jpath = tmp_path / "s-top-1.jsonl"
    _write_jsonl(jpath, _top_level_entries("s-top-1"))

    md = parse_jsonl_metadata(str(jpath))
    assert md is not None
    assert md["session_id"] == "s-top-1"
    assert md["parent_jsonl_uuid"] is None
    assert md["started_at"] == "2026-04-01T00:00:00.000Z"
    assert md["ended_at"] == "2026-04-01T00:00:05.000Z"
    assert md["model"] == "claude-opus-4-7"
    assert md["total_input_tokens"] == 30
    assert md["total_output_tokens"] == 12
    assert md["total_cache_creation_tokens"] == 150
    assert md["total_cache_read_tokens"] == 500
    assert md["turn_count"] == 2


def test_parse_sub_session_jsonl_keeps_parent_uuid(tmp_path):
    from cc_session_discovery import parse_jsonl_metadata

    jpath = tmp_path / "s-sub-1.jsonl"
    _write_jsonl(jpath, _sub_session_entries(parent_uuid="parent-tool-use-uuid"))

    md = parse_jsonl_metadata(str(jpath))
    assert md is not None
    assert md["session_id"] == "s-sub-1"
    assert md["parent_jsonl_uuid"] == "parent-tool-use-uuid"
    assert md["model"] == "claude-sonnet-4-6"
    assert md["turn_count"] == 1


def test_parse_empty_file_returns_none(tmp_path):
    from cc_session_discovery import parse_jsonl_metadata

    jpath = tmp_path / "empty.jsonl"
    jpath.write_text("")
    assert parse_jsonl_metadata(str(jpath)) is None


def test_parse_missing_file_returns_none(tmp_path):
    from cc_session_discovery import parse_jsonl_metadata
    assert parse_jsonl_metadata(str(tmp_path / "no-such.jsonl")) is None


def test_parse_malformed_jsonl_partial(tmp_path):
    """All-malformed → None; partially malformed → returns metadata for the valid lines."""
    from cc_session_discovery import parse_jsonl_metadata

    # All-malformed.
    bad = tmp_path / "all-bad.jsonl"
    bad.write_text("not-json\n{also-not-json\n")
    assert parse_jsonl_metadata(str(bad)) is None

    # Mixed: garbage + one valid line. Should return metadata.
    mixed = tmp_path / "s-mixed.jsonl"
    with open(mixed, "w") as f:
        f.write("not-json\n")
        f.write(json.dumps({
            "parentUuid": None,
            "type": "user",
            "uuid": "u-1",
            "timestamp": "2026-04-01T00:00:00Z",
            "message": {"role": "user", "content": "hi"},
        }) + "\n")
        f.write("{truncated\n")
    md = parse_jsonl_metadata(str(mixed))
    assert md is not None
    assert md["session_id"] == "s-mixed"
    assert md["parent_jsonl_uuid"] is None


def test_parse_jsonl_token_totals_match_sum_jsonl_usage(tmp_path):
    from cc_session_discovery import parse_jsonl_metadata
    from session_history import sum_jsonl_usage

    jpath = tmp_path / "s-x.jsonl"
    _write_jsonl(jpath, _top_level_entries("s-x"))

    md = parse_jsonl_metadata(str(jpath))
    direct = sum_jsonl_usage(str(jpath))
    assert md["total_input_tokens"] == direct["input_tokens"]
    assert md["total_output_tokens"] == direct["output_tokens"]
    assert md["total_cache_creation_tokens"] == direct["cache_creation_input_tokens"]
    assert md["total_cache_read_tokens"] == direct["cache_read_input_tokens"]
    assert md["turn_count"] == direct["turn_count"]


# ---------------------------------------------------------------------------
# link_sub_to_parent
# ---------------------------------------------------------------------------

def test_link_sub_to_parent_finds_match(tmp_path):
    from cc_session_discovery import link_sub_to_parent, parse_jsonl_metadata

    # Top-level JSONL contains an entry with uuid="tool-use-X"
    top_path = tmp_path / "s-top.jsonl"
    entries = _top_level_entries("s-top")
    # Append a synthetic tool_use-bearing entry with a known uuid.
    entries.append({
        "parentUuid": "a-002",
        "type": "assistant",
        "uuid": "tool-use-X",
        "timestamp": "2026-04-01T00:00:06Z",
        "sessionId": "s-top",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "Task", "id": "tu-1"}],
        },
    })
    _write_jsonl(top_path, entries)

    # Sub-session points at that uuid.
    sub_path = tmp_path / "s-sub.jsonl"
    _write_jsonl(sub_path, _sub_session_entries(parent_uuid="tool-use-X",
                                                session_id="s-sub"))

    top_md = parse_jsonl_metadata(str(top_path))
    sub_md = parse_jsonl_metadata(str(sub_path))
    all_md = [top_md, sub_md]

    parent_sid = link_sub_to_parent(sub_md, all_md)
    assert parent_sid == "s-top"


def test_link_sub_to_parent_no_match_returns_none(tmp_path):
    from cc_session_discovery import link_sub_to_parent, parse_jsonl_metadata

    top_path = tmp_path / "s-top.jsonl"
    _write_jsonl(top_path, _top_level_entries("s-top"))

    sub_path = tmp_path / "s-orphan.jsonl"
    _write_jsonl(sub_path, _sub_session_entries(parent_uuid="missing-uuid",
                                                session_id="s-orphan"))

    top_md = parse_jsonl_metadata(str(top_path))
    sub_md = parse_jsonl_metadata(str(sub_path))
    assert link_sub_to_parent(sub_md, [top_md, sub_md]) is None


def test_link_sub_to_parent_top_level_returns_none(tmp_path):
    """A session with parent_jsonl_uuid=None should always return None."""
    from cc_session_discovery import link_sub_to_parent, parse_jsonl_metadata

    top_path = tmp_path / "s-top.jsonl"
    _write_jsonl(top_path, _top_level_entries("s-top"))

    md = parse_jsonl_metadata(str(top_path))
    assert link_sub_to_parent(md, [md]) is None


# ---------------------------------------------------------------------------
# find_owner_for_top_session
# ---------------------------------------------------------------------------

def test_find_owner_reads_json_sidecar(tmp_path):
    from cc_session_discovery import find_owner_for_top_session

    sid = "s-owned"
    (tmp_path / f"{sid}.owner").write_text(json.dumps({"agent_id": "abc123def456"}))
    assert find_owner_for_top_session(sid, str(tmp_path)) == "abc123def456"


def test_find_owner_reads_legacy_plain_text(tmp_path):
    from cc_session_discovery import find_owner_for_top_session

    sid = "s-legacy"
    (tmp_path / f"{sid}.owner").write_text("legacy-agent-id")
    assert find_owner_for_top_session(sid, str(tmp_path)) == "legacy-agent-id"


def test_find_owner_missing_returns_none(tmp_path):
    from cc_session_discovery import find_owner_for_top_session
    assert find_owner_for_top_session("nope", str(tmp_path)) is None


def test_find_owner_malformed_returns_none(tmp_path):
    from cc_session_discovery import find_owner_for_top_session

    sid = "s-bad"
    (tmp_path / f"{sid}.owner").write_text("{not valid json")
    assert find_owner_for_top_session(sid, str(tmp_path)) is None


# ---------------------------------------------------------------------------
# discover_project_sessions
# ---------------------------------------------------------------------------

def test_discover_project_sessions_returns_metadata_list(tmp_path, monkeypatch):
    """End-to-end: synthesize a project session_dir via session_source_dir
    monkey-patch and verify discover finds every JSONL."""
    from cc_session_discovery import discover_project_sessions

    fake_sdir = tmp_path / "session-dir"
    fake_sdir.mkdir()
    _write_jsonl(fake_sdir / "s-1.jsonl", _top_level_entries("s-1"))
    _write_jsonl(
        fake_sdir / "s-2.jsonl",
        _sub_session_entries(parent_uuid="ignored-for-now", session_id="s-2"),
    )

    monkeypatch.setattr(
        "cc_session_discovery.session_source_dir",
        lambda p: str(fake_sdir),
    )

    project_path = tmp_path / "fake-project"
    project_path.mkdir()

    sessions = discover_project_sessions(str(project_path))
    sids = sorted(m["session_id"] for m in sessions)
    assert sids == ["s-1", "s-2"]
