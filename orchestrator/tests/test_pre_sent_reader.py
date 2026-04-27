"""Reader-side tests for the split /display endpoints.

After the endpoint split, /display/pre-sent always returns a full
authoritative snapshot from the in-memory _pre_sent_index, and
/display/sent reads sent (seq != null) entries from the file by
byte offset / tail bytes. There is no longer a "queued_authoritative"
mode flag — pre-sent is always full snapshot, sent is always file
incremental.
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

    try:
        os.unlink(_display_path(aid))
    except FileNotFoundError:
        pass
    with _pre_sent_lock:
        _pre_sent_index.pop(aid, None)
        _pre_sent_index_ready.discard(aid)


@pytest.mark.anyio
async def test_pre_sent_endpoint_returns_index_snapshot(client, reader_agent):
    """/display/pre-sent returns every entry in the in-memory index."""
    aid = reader_agent
    ids = [
        pre_sent_create(aid, _mk_entry(content="a")),
        pre_sent_create(aid, _mk_entry(content="b")),
        pre_sent_create(aid, _mk_entry(content="c")),
    ]

    resp = await client.get(f"/api/agents/{aid}/display/pre-sent")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    returned_ids = {e["id"] for e in data["entries"]}
    assert returned_ids == set(ids)
    for e in data["entries"]:
        assert e.get("_pre_sent") is True
        assert e["role"] == "USER"
        assert e["content"] in {"a", "b", "c"}


@pytest.mark.anyio
async def test_pre_sent_endpoint_is_authoritative_on_every_call(client, reader_agent):
    """No incremental mode — every /display/pre-sent call returns full snapshot.

    This is the structural fix for the "queued bubble disappears on poll"
    bug: the endpoint never returns an empty snapshot just because of
    cursor state.
    """
    aid = reader_agent
    pre_sent_create(aid, _mk_entry(content="only"))

    # Two consecutive calls — both must return the same authoritative set.
    resp1 = await client.get(f"/api/agents/{aid}/display/pre-sent")
    resp2 = await client.get(f"/api/agents/{aid}/display/pre-sent")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(resp1.json()["entries"]) == 1
    assert len(resp2.json()["entries"]) == 1


@pytest.mark.anyio
async def test_sent_endpoint_excludes_pre_sent_entries(client, reader_agent):
    """/display/sent never returns _queued / pre_sent entries even if
    they're physically in the file.
    """
    aid = reader_agent
    # pre_sent_create writes a `_queued: true _pre_sent: true` line to the file.
    pre_sent_create(aid, _mk_entry(content="should-not-appear-in-sent"))

    resp = await client.get(f"/api/agents/{aid}/display/sent?tail_bytes=50000")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["messages"] == []


@pytest.mark.anyio
async def test_sent_endpoint_returns_seq_entries(client, reader_agent):
    """A line with `seq: N` (no _queued) appears in /display/sent.messages."""
    aid = reader_agent
    msg_id = uuid.uuid4().hex[:12]
    sent_line = json.dumps({
        "id": msg_id,
        "seq": 1,
        "role": "USER",
        "kind": None,
        "content": "real sent message",
        "source": "web",
        "status": "sent",
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
        f.write(sent_line + "\n")

    resp = await client.get(f"/api/agents/{aid}/display/sent?tail_bytes=50000")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = {m["id"] for m in data["messages"]}
    assert msg_id in ids
