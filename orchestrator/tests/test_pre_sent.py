"""Unit tests for the Phase 1 pre-sent API in display_writer.

Covers the lifecycle: create → update → cancel → tombstone, plus
promote_to_sent and the rebuild_agent read-before-truncate semantics.

These tests mutate module-global state in display_writer (the
_pre_sent_index and the per-agent jsonl files), so each test uses a
unique agent_id and the autouse fixture cleans any file + index residue
at teardown.
"""

import json
import os
import uuid

import pytest

from display_writer import (
    DISPLAY_DIR,
    _display_path,
    _pre_sent_index,
    _pre_sent_index_ready,
    _pre_sent_lock,
    pre_sent_cancel,
    pre_sent_create,
    pre_sent_get,
    pre_sent_list,
    pre_sent_promote_to_sent,
    pre_sent_tombstone,
    pre_sent_update,
    rebuild_agent,
)


def _fresh_agent_id() -> str:
    """Return a 12-hex agent id unique to the test run."""
    return uuid.uuid4().hex[:12]


def _fresh_msg_id() -> str:
    return uuid.uuid4().hex[:12]


def _mk_entry(content: str = "hello", status: str = "queued",
              source: str = "web", msg_id: str | None = None) -> dict:
    return {
        "id": msg_id or _fresh_msg_id(),
        "role": "USER",
        "content": content,
        "source": source,
        "status": status,
        "created_at": "2026-04-24T00:00:00+00:00",
    }


@pytest.fixture()
def agent_id():
    """Provide a fresh agent id and clean up index + file at teardown."""
    aid = _fresh_agent_id()
    os.makedirs(DISPLAY_DIR, exist_ok=True)
    yield aid
    # Teardown: remove the file and clear index state for this agent.
    try:
        os.unlink(_display_path(aid))
    except FileNotFoundError:
        pass
    with _pre_sent_lock:
        _pre_sent_index.pop(aid, None)
        _pre_sent_index_ready.discard(aid)


def _read_lines(agent_id: str) -> list[dict]:
    """Read all parsed JSON lines from the agent's file."""
    path = _display_path(agent_id)
    try:
        with open(path, "r") as f:
            raw = f.read()
    except FileNotFoundError:
        return []
    out = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


# ---- Lifecycle tests --------------------------------------------------


def test_create_and_list(agent_id):
    """Two creates → list returns both in creation order."""
    e1 = _mk_entry(content="first")
    e2 = _mk_entry(content="second")

    id1 = pre_sent_create(agent_id, e1)
    id2 = pre_sent_create(agent_id, e2)

    entries = pre_sent_list(agent_id)
    assert [e["id"] for e in entries] == [id1, id2]
    assert entries[0]["content"] == "first"
    assert entries[1]["content"] == "second"
    assert entries[0]["_pre_sent"] is True
    assert entries[0]["_queued"] is True


def test_update(agent_id):
    """pre_sent_update merges patch and the latest state wins in list."""
    e1 = _mk_entry(content="original")
    mid = pre_sent_create(agent_id, e1)

    pre_sent_update(agent_id, mid, {"content": "edited", "metadata": {"k": 1}})

    got = pre_sent_get(agent_id, mid)
    assert got["content"] == "edited"
    assert got["metadata"] == {"k": 1}
    assert got["status"] == "queued"
    # File has at least two lines: original + _replace edit
    lines = _read_lines(agent_id)
    assert len(lines) >= 2
    last = lines[-1]
    assert last["_replace"] is True
    assert last["content"] == "edited"


def test_cancel_and_tombstone(agent_id):
    """cancel → status='cancelled' stays in index; tombstone removes."""
    mid = pre_sent_create(agent_id, _mk_entry())

    pre_sent_cancel(agent_id, mid)
    got = pre_sent_get(agent_id, mid)
    assert got is not None
    assert got["status"] == "cancelled"

    pre_sent_tombstone(agent_id, mid)
    assert pre_sent_get(agent_id, mid) is None
    lines = _read_lines(agent_id)
    # Final line should be the tombstone.
    assert lines[-1] == {"id": mid, "_deleted": True}


def test_tombstone_before_cancel_fails(agent_id):
    """Tombstoning a still-queued entry must raise."""
    mid = pre_sent_create(agent_id, _mk_entry())

    with pytest.raises(ValueError):
        pre_sent_tombstone(agent_id, mid)

    # Index still has the entry
    assert pre_sent_get(agent_id, mid) is not None


def test_cancel_cancelled_fails(agent_id):
    """Cancel on an already-cancelled entry must raise (only queued/scheduled)."""
    mid = pre_sent_create(agent_id, _mk_entry())
    pre_sent_cancel(agent_id, mid)

    with pytest.raises(ValueError):
        pre_sent_cancel(agent_id, mid)


def test_update_nonexistent_raises(agent_id):
    with pytest.raises(KeyError):
        pre_sent_update(agent_id, "deadbeef0000", {"content": "x"})


def test_promote_to_sent(agent_id):
    """promote_to_sent removes from index, writes tombstone + sent line."""
    mid = pre_sent_create(agent_id, _mk_entry(content="to be sent"))

    sent_line = {
        "id": mid,
        "seq": 5,
        "role": "USER",
        "kind": "text",
        "content": "to be sent",
        "source": "web",
        "status": "sent",
        "metadata": None,
        "tool_use_id": None,
        "created_at": "2026-04-24T00:00:00+00:00",
        "completed_at": None,
        "delivered_at": None,
    }
    pre_sent_promote_to_sent(agent_id, mid, seq=5, sent_line=sent_line)

    assert pre_sent_get(agent_id, mid) is None
    # File should end with tombstone + sent line as the last two lines.
    lines = _read_lines(agent_id)
    assert lines[-2] == {"id": mid, "_deleted": True}
    assert lines[-1]["seq"] == 5
    assert lines[-1]["status"] == "sent"
    assert lines[-1].get("_queued") is None
    assert lines[-1].get("_pre") is None
    assert lines[-1].get("_pre_sent") is None


def test_promote_to_sent_rejects_mismatched_id(agent_id):
    mid = pre_sent_create(agent_id, _mk_entry())
    with pytest.raises(ValueError):
        pre_sent_promote_to_sent(
            agent_id, mid, seq=1,
            sent_line={"id": "different0000", "seq": 1, "status": "sent"},
        )


def test_promote_to_sent_rejects_pre_marker(agent_id):
    mid = pre_sent_create(agent_id, _mk_entry())
    with pytest.raises(ValueError):
        pre_sent_promote_to_sent(
            agent_id, mid, seq=1,
            sent_line={"id": mid, "_pre_sent": True, "status": "sent"},
        )


def test_validate_required_fields(agent_id):
    with pytest.raises(ValueError):
        pre_sent_create(agent_id, {"id": "x", "role": "USER"})


def test_validate_role(agent_id):
    bad = _mk_entry()
    bad["role"] = "AGENT"
    with pytest.raises(ValueError):
        pre_sent_create(agent_id, bad)


def test_validate_source(agent_id):
    bad = _mk_entry(source="cli")
    with pytest.raises(ValueError):
        pre_sent_create(agent_id, bad)


def test_validate_status(agent_id):
    bad = _mk_entry(status="sent")
    with pytest.raises(ValueError):
        pre_sent_create(agent_id, bad)


# ---- Rebuild tests ----------------------------------------------------


def test_rebuild_preserves_pre_entries(agent_id, db_session):
    """rebuild_agent's read-before-truncate keeps _pre_sent entries alive."""
    # db_session fixture ensures Message table exists; rebuild_agent will
    # open its own SessionLocal — that's fine, this test is file-focused.
    mid1 = pre_sent_create(agent_id, _mk_entry(content="one"))
    mid2 = pre_sent_create(agent_id, _mk_entry(content="two"))

    rebuild_agent(agent_id)

    entries = pre_sent_list(agent_id)
    ids = {e["id"] for e in entries}
    assert mid1 in ids
    assert mid2 in ids
    contents = {e["content"] for e in entries}
    assert contents == {"one", "two"}


def test_rebuild_drops_tombstoned(agent_id, db_session):
    """After cancel + tombstone, rebuild must not resurrect the entry."""
    mid = pre_sent_create(agent_id, _mk_entry())
    pre_sent_cancel(agent_id, mid)
    pre_sent_tombstone(agent_id, mid)

    rebuild_agent(agent_id)

    assert pre_sent_get(agent_id, mid) is None
    entries = pre_sent_list(agent_id)
    assert all(e["id"] != mid for e in entries)


def test_rebuild_preserves_cancelled(agent_id, db_session):
    """Per §9.1 of the plan, cancelled bubbles survive rebuild."""
    mid = pre_sent_create(agent_id, _mk_entry())
    pre_sent_cancel(agent_id, mid)

    rebuild_agent(agent_id)

    got = pre_sent_get(agent_id, mid)
    assert got is not None
    assert got["status"] == "cancelled"
