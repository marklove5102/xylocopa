"""Reader-side tests for the Phase 1 pre_sent flow.

Verifies GET /api/agents/{id}/display sources queued entries from the
in-memory _pre_sent_index on initial load, returns an empty queued
list on incremental polls with `queued_authoritative: false`, and
still honors legacy `_queued` lines (without `_pre`) for backwards
compat during the Phase 1→2 transition.
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
    pre_sent_create,
)
from models import Agent, AgentMode, AgentStatus, Project


def _mk_entry(msg_id: str | None = None, content: str = "hi",
              status: str = "queued") -> dict:
    return {
        "id": msg_id or uuid.uuid4().hex[:12],
        "role": "USER",
        "content": content,
        "source": "web",
        "status": status,
        "created_at": "2026-04-24T00:00:00+00:00",
    }


@pytest.fixture()
def reader_agent(db_engine):
    """Insert an Agent row into the test DB (via sessionmaker bound to
    db_engine — matches the override wired into `client`). Returns the
    id and cleans up index + file at teardown.
    """
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    try:
        proj = Project(name="pre-proj", display_name="Pre", path="/tmp/pre")
        db.add(proj)
        db.commit()
        aid = uuid.uuid4().hex[:12]
        agent = Agent(
            id=aid,
            project=proj.name,
            name="pre-agent",
            mode=AgentMode.AUTO,
            status=AgentStatus.IDLE,
            model="claude-opus-4-7",
        )
        db.add(agent)
        db.commit()
    finally:
        db.close()

    os.makedirs(DISPLAY_DIR, exist_ok=True)
    yield aid

    # Teardown
    try:
        os.unlink(_display_path(aid))
    except FileNotFoundError:
        pass
    with _pre_sent_lock:
        _pre_sent_index.pop(aid, None)
        _pre_sent_index_ready.discard(aid)


@pytest.mark.anyio
async def test_initial_load_returns_pre_entries(client, reader_agent):
    """pre_sent_create 3 entries → initial GET returns them in data.queued."""
    aid = reader_agent
    ids = [
        pre_sent_create(aid, _mk_entry(content="a")),
        pre_sent_create(aid, _mk_entry(content="b")),
        pre_sent_create(aid, _mk_entry(content="c")),
    ]

    resp = await client.get(f"/api/agents/{aid}/display?tail_bytes=50000")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["queued_authoritative"] is True
    returned_ids = {e["id"] for e in data["queued"]}
    assert returned_ids == set(ids)
    # Each entry carries the _pre_sent marker (aliased in the JSON response).
    for e in data["queued"]:
        assert e.get("_pre_sent") is True
        assert e["role"] == "USER"
        assert e["content"] in {"a", "b", "c"}


@pytest.mark.anyio
async def test_incremental_poll_returns_null_queued(client, reader_agent):
    """After initial load, incremental GET returns empty queued list with
    queued_authoritative=false — frontend must leave queued state alone.
    """
    aid = reader_agent
    pre_sent_create(aid, _mk_entry(content="only"))

    # Initial load — capture next_offset
    resp0 = await client.get(f"/api/agents/{aid}/display?tail_bytes=50000")
    assert resp0.status_code == 200
    next_offset = resp0.json()["next_offset"]

    # Incremental poll
    resp1 = await client.get(f"/api/agents/{aid}/display?offset={next_offset}")
    assert resp1.status_code == 200, resp1.text
    data = resp1.json()
    assert data["queued_authoritative"] is False
    assert data["queued"] == []


@pytest.mark.anyio
async def test_file_without_pre_index_still_reads_legacy(client, reader_agent):
    """A legacy _queued line (no _pre) written directly to the file must
    still appear in data.queued (backwards compat during Phase 1→2).
    """
    aid = reader_agent
    legacy_id = uuid.uuid4().hex[:12]
    legacy_line = json.dumps({
        "id": legacy_id,
        "_queued": True,
        "role": "USER",
        "kind": None,
        "content": "legacy queued",
        "source": "web",
        "status": "PENDING",
        "metadata": None,
        "tool_use_id": None,
        "created_at": "2026-04-24T00:00:00+00:00",
        "scheduled_at": None,
        "completed_at": None,
        "delivered_at": None,
    })
    path = _display_path(aid)
    os.makedirs(DISPLAY_DIR, exist_ok=True)
    with open(path, "a") as f:
        f.write(legacy_line + "\n")

    resp = await client.get(f"/api/agents/{aid}/display?tail_bytes=50000")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["queued_authoritative"] is True
    ids = {e["id"] for e in data["queued"]}
    assert legacy_id in ids
    # Find the legacy entry
    entry = next(e for e in data["queued"] if e["id"] == legacy_id)
    assert entry["content"] == "legacy queued"
    # Legacy lines have no _pre / _pre_sent marker.
    assert entry.get("_pre") is None
    assert entry.get("_pre_sent") is None
