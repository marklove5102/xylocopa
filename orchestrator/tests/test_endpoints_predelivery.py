"""Endpoint tests for the Phase 2 pre-delivery refactor.

Covers POST /messages, DELETE /messages/{id}, and PUT /messages/{id} as
refactored by Impl-B. The display_writer `predelivery_*` API is stubbed
via monkeypatch so these tests do not touch the real display file.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from models import (
    Agent, AgentMode, AgentStatus, Message, MessageRole, MessageStatus,
    Project,
)
from schemas import MessageOut


def _make_session(db_engine):
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    return Session()


def _seed_agent(db, *, agent_id="pre111122223", project_name="pre-proj",
                status=AgentStatus.IDLE, tmux_pane=None):
    if not db.get(Project, project_name):
        db.add(Project(
            name=project_name,
            display_name=project_name.title(),
            path=f"/tmp/{project_name}",
        ))
        db.flush()
    db.add(Agent(
        id=agent_id,
        project=project_name,
        name=f"Agent {agent_id[:6]}",
        mode=AgentMode.AUTO,
        status=status,
        model="claude-opus-4-7",
        tmux_pane=tmux_pane,
    ))
    db.commit()
    return agent_id


class _PredeliveryStubStore:
    """In-memory stand-in for display_writer.predelivery_*.

    Records calls for assertion and maintains a minimal per-agent map of
    entries keyed by message id.
    """

    def __init__(self):
        self.entries: dict[str, dict[str, dict]] = {}
        self.create_calls: list[tuple[str, dict]] = []
        self.update_calls: list[tuple[str, str, dict]] = []
        self.cancel_calls: list[tuple[str, str]] = []
        self.tombstone_calls: list[tuple[str, str]] = []

    def create(self, agent_id: str, entry: dict) -> str:
        self.create_calls.append((agent_id, dict(entry)))
        bucket = self.entries.setdefault(agent_id, {})
        full = dict(entry)
        full.setdefault("scheduled_at", None)
        full.setdefault("metadata", None)
        bucket[entry["id"]] = full
        return entry["id"]

    def update(self, agent_id: str, msg_id: str, patch: dict) -> None:
        self.update_calls.append((agent_id, msg_id, dict(patch)))
        bucket = self.entries.setdefault(agent_id, {})
        current = bucket.get(msg_id)
        if current is None:
            raise KeyError(msg_id)
        merged = dict(current)
        for k in ("content", "scheduled_at", "metadata", "status"):
            if k in patch:
                merged[k] = patch[k]
        bucket[msg_id] = merged

    def cancel(self, agent_id: str, msg_id: str) -> None:
        self.cancel_calls.append((agent_id, msg_id))
        bucket = self.entries.setdefault(agent_id, {})
        current = bucket.get(msg_id)
        if current is None:
            raise KeyError(msg_id)
        if current.get("status") not in ("queued", "scheduled"):
            raise ValueError("only queued/scheduled can be cancelled")
        merged = dict(current)
        merged["status"] = "cancelled"
        bucket[msg_id] = merged

    def tombstone(self, agent_id: str, msg_id: str) -> None:
        self.tombstone_calls.append((agent_id, msg_id))
        bucket = self.entries.setdefault(agent_id, {})
        current = bucket.get(msg_id)
        if current is None:
            raise KeyError(msg_id)
        if current.get("status") != "cancelled":
            raise ValueError("must cancel first")
        bucket.pop(msg_id, None)

    def get(self, agent_id: str, msg_id: str):
        bucket = self.entries.get(agent_id, {})
        current = bucket.get(msg_id)
        return dict(current) if current is not None else None

    def list(self, agent_id: str):
        return [dict(v) for v in self.entries.get(agent_id, {}).values()]


@pytest.fixture()
def stub_store(monkeypatch):
    store = _PredeliveryStubStore()
    import display_writer as _dw
    monkeypatch.setattr(_dw, "predelivery_create", store.create)
    monkeypatch.setattr(_dw, "predelivery_update", store.update)
    monkeypatch.setattr(_dw, "predelivery_cancel", store.cancel)
    monkeypatch.setattr(_dw, "predelivery_tombstone", store.tombstone)
    monkeypatch.setattr(_dw, "predelivery_get", store.get)
    monkeypatch.setattr(_dw, "predelivery_list", store.list)
    # Also patch the router-level re-imports (the endpoint re-imports
    # inside the function body, so patching just display_writer works —
    # both import paths resolve to the same module attribute).
    return store


@pytest.fixture()
def ws_recorder(monkeypatch):
    """Record all WS emit_* calls invoked by the endpoints."""
    calls: list[tuple[str, tuple, dict]] = []

    async def _recorder_factory(name):
        async def _fake(*args, **kwargs):
            calls.append((name, args, kwargs))
        return _fake

    # Build async stubs that record args.
    def _make(name):
        async def _fake(*args, **kwargs):
            calls.append((name, args, kwargs))
        return _fake

    import websocket as _ws
    monkeypatch.setattr(_ws, "emit_predelivery_created", _make("predelivery_created"))
    monkeypatch.setattr(_ws, "emit_predelivery_updated", _make("predelivery_updated"))
    monkeypatch.setattr(_ws, "emit_predelivery_tombstoned", _make("predelivery_tombstoned"))
    return calls


@pytest.fixture()
def dispatcher_noop(monkeypatch):
    """Neutralize dispatcher side effects: no tmux probes, no async tick."""
    # Bypass the pane verify path entirely by keeping tmux_pane None on
    # the seeded agent. This fixture still patches dispatch_pending_message
    # so it doesn't spawn real background work under ASGITransport.
    recorded: list[tuple[str, str, float]] = []

    async def _fake_dispatch(self, agent_id, delay=0):
        recorded.append(("dispatch_pending_message", agent_id, delay))

    import agent_dispatcher as _ad
    monkeypatch.setattr(
        _ad.AgentDispatcher, "dispatch_pending_message", _fake_dispatch,
    )
    return recorded


# ---------------------------------------------------------------------------
# POST /messages
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_post_messages_creates_predelivery_entry(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="postidle0001", status=AgentStatus.IDLE)
    db.close()

    resp = await client.post(
        "/api/agents/postidle0001/messages",
        json={"content": "hello predelivery"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    # No DB row should have been created.
    db = _make_session(db_engine)
    assert db.query(Message).filter(Message.agent_id == "postidle0001").count() == 0
    db.close()

    # predelivery_create was called once with the right shape.
    assert len(stub_store.create_calls) == 1
    agent_arg, entry_arg = stub_store.create_calls[0]
    assert agent_arg == "postidle0001"
    assert entry_arg["role"] == "USER"
    assert entry_arg["source"] == "web"
    assert entry_arg["status"] == "queued"
    assert entry_arg["content"] == "hello predelivery"
    assert entry_arg["id"] == data["id"]
    assert entry_arg["scheduled_at"] is None

    # WS event emitted.
    event_names = [c[0] for c in ws_recorder]
    assert "predelivery_created" in event_names


@pytest.mark.anyio
async def test_post_messages_scheduled_uses_scheduled_status(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="postsched001", status=AgentStatus.IDLE)
    db.close()

    future = "2099-01-01T12:00:00+00:00"
    resp = await client.post(
        "/api/agents/postsched001/messages",
        json={"content": "later", "scheduled_at": future},
    )
    assert resp.status_code == 201, resp.text

    assert len(stub_store.create_calls) == 1
    entry = stub_store.create_calls[0][1]
    assert entry["status"] == "scheduled"
    assert entry["scheduled_at"] is not None

    # No dispatcher kick for scheduled sends (they flow through the
    # periodic _dispatch_tmux_scheduled tick instead).
    assert dispatcher_noop == []


@pytest.mark.anyio
async def test_post_messages_returns_valid_message_out(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="postshape001", status=AgentStatus.IDLE)
    db.close()

    resp = await client.post(
        "/api/agents/postshape001/messages",
        json={"content": "shape me"},
    )
    assert resp.status_code == 201
    data = resp.json()

    # Shape-check: the response JSON must round-trip into MessageOut.
    model = MessageOut.model_validate(data)
    assert model.id == data["id"]
    assert model.agent_id == "postshape001"
    assert model.role == MessageRole.USER
    assert model.content == "shape me"
    assert model.source == "web"
    assert model.status == MessageStatus.PENDING
    assert model.delivered_at is None
    assert model.completed_at is None


@pytest.mark.anyio
async def test_post_messages_agent_stopped_returns_400(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="poststop0001", status=AgentStatus.STOPPED)
    db.close()

    resp = await client.post(
        "/api/agents/poststop0001/messages",
        json={"content": "nope"},
    )
    assert resp.status_code == 400
    assert stub_store.create_calls == []


# ---------------------------------------------------------------------------
# DELETE /messages/{id}
# ---------------------------------------------------------------------------

def _seed_predelivery_entry(store, agent_id: str, *, status="queued",
                            content="hi", msg_id=None):
    mid = msg_id or "mid00000001"
    store.entries.setdefault(agent_id, {})[mid] = {
        "id": mid,
        "role": "USER",
        "content": content,
        "source": "web",
        "status": status,
        "created_at": "2026-04-24T00:00:00+00:00",
        "scheduled_at": None,
        "metadata": None,
    }
    return mid


@pytest.mark.anyio
async def test_delete_queued_tombstones_in_one_step(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    """Pressing delete on a queued entry hard-tombstones immediately —
    no soft-cancel intermediate state surfaced to the client."""
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="delq11112222", status=AgentStatus.IDLE)
    db.close()

    mid = _seed_predelivery_entry(stub_store, "delq11112222", status="queued")

    resp = await client.delete(f"/api/agents/delq11112222/messages/{mid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["detail"] == "deleted"

    # Storage layer still needs cancel→tombstone, but only the tombstone
    # event is broadcast (no transient `predelivery_updated`).
    assert stub_store.cancel_calls == [("delq11112222", mid)]
    assert stub_store.tombstone_calls == [("delq11112222", mid)]
    assert any(c[0] == "predelivery_tombstoned" for c in ws_recorder)
    assert not any(c[0] == "predelivery_updated" for c in ws_recorder)


@pytest.mark.anyio
async def test_delete_cancelled_hard_deletes(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    """Existing cancelled entries (e.g. created before single-step rollout)
    still tombstone correctly without re-cancelling."""
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="delh11112222", status=AgentStatus.IDLE)
    db.close()

    mid = _seed_predelivery_entry(stub_store, "delh11112222", status="cancelled")

    resp = await client.delete(f"/api/agents/delh11112222/messages/{mid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["detail"] == "deleted"

    assert stub_store.tombstone_calls == [("delh11112222", mid)]
    assert stub_store.cancel_calls == []
    assert any(c[0] == "predelivery_tombstoned" for c in ws_recorder)


@pytest.mark.anyio
async def test_delete_sent_returns_400(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    """A message with a DB row but no pre-delivery entry cannot be deleted."""
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="delsent00001", status=AgentStatus.IDLE)
    # Insert a DB row simulating a sent/delivered message.
    db.add(Message(
        id="sent00000001",
        agent_id="delsent00001",
        role=MessageRole.USER,
        content="already sent",
        status=MessageStatus.QUEUED,  # legacy QUEUED = sent
        source="web",
    ))
    db.commit()
    db.close()

    resp = await client.delete("/api/agents/delsent00001/messages/sent00000001")
    assert resp.status_code == 400
    assert stub_store.cancel_calls == []
    assert stub_store.tombstone_calls == []


@pytest.mark.anyio
async def test_delete_unknown_returns_404(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="del404000001", status=AgentStatus.IDLE)
    db.close()

    resp = await client.delete("/api/agents/del404000001/messages/doesnotexist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /messages/{id}
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_put_queued_updates_content(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="putedit00001", status=AgentStatus.IDLE)
    db.close()

    mid = _seed_predelivery_entry(
        stub_store, "putedit00001", status="queued", content="original",
    )

    resp = await client.put(
        f"/api/agents/putedit00001/messages/{mid}",
        json={"content": "edited"},
    )
    assert resp.status_code == 200, resp.text

    assert len(stub_store.update_calls) == 1
    agent_arg, mid_arg, patch = stub_store.update_calls[0]
    assert agent_arg == "putedit00001"
    assert mid_arg == mid
    assert patch["content"] == "edited"

    # Response shape round-trips into MessageOut.
    data = resp.json()
    model = MessageOut.model_validate(data)
    assert model.content == "edited"
    assert model.id == mid

    assert any(c[0] == "predelivery_updated" for c in ws_recorder)


@pytest.mark.anyio
async def test_put_scheduled_updates_schedule(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="putsched0001", status=AgentStatus.IDLE)
    db.close()

    mid = _seed_predelivery_entry(stub_store, "putsched0001", status="scheduled")
    # Put the original into scheduled state properly.
    stub_store.entries["putsched0001"][mid]["scheduled_at"] = "2099-01-01T00:00:00+00:00"

    resp = await client.put(
        f"/api/agents/putsched0001/messages/{mid}",
        json={"scheduled_at": "2099-06-15T12:00:00+00:00"},
    )
    assert resp.status_code == 200, resp.text

    patch = stub_store.update_calls[-1][2]
    assert patch["scheduled_at"].startswith("2099-06-15")


@pytest.mark.anyio
async def test_put_sent_returns_400(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    """Editing a non-pre-delivery message is rejected."""
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="putsent00001", status=AgentStatus.IDLE)
    db.add(Message(
        id="sentedit0001",
        agent_id="putsent00001",
        role=MessageRole.USER,
        content="already sent",
        status=MessageStatus.QUEUED,
        source="web",
    ))
    db.commit()
    db.close()

    resp = await client.put(
        "/api/agents/putsent00001/messages/sentedit0001",
        json={"content": "too late"},
    )
    assert resp.status_code == 400
    assert stub_store.update_calls == []


@pytest.mark.anyio
async def test_put_cancelled_returns_400(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="putcanc00001", status=AgentStatus.IDLE)
    db.close()

    mid = _seed_predelivery_entry(stub_store, "putcanc00001", status="cancelled")

    resp = await client.put(
        f"/api/agents/putcanc00001/messages/{mid}",
        json={"content": "no edits allowed"},
    )
    assert resp.status_code == 400
    assert stub_store.update_calls == []


@pytest.mark.anyio
async def test_put_empty_content_returns_400(
    client, db_engine, stub_store, ws_recorder, dispatcher_noop,
):
    db = _make_session(db_engine)
    _seed_agent(db, agent_id="putemt00001", status=AgentStatus.IDLE)
    db.close()

    mid = _seed_predelivery_entry(stub_store, "putemt00001", status="queued")

    resp = await client.put(
        f"/api/agents/putemt00001/messages/{mid}",
        json={"content": "   "},
    )
    assert resp.status_code == 400
    assert stub_store.update_calls == []


# ---------------------------------------------------------------------------
# anyio backend config
# ---------------------------------------------------------------------------

@pytest.fixture
def anyio_backend():
    return "asyncio"
