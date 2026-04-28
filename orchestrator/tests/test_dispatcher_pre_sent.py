"""Tests for the pre-sent dispatch flow in agent_dispatcher.

Covers dispatch_pending_message and _dispatch_tmux_scheduled reading
from the display_writer pre-sent index and promoting to DB sent rows
via _promote_pre_sent_to_sent.

These tests monkey-patch:
- `agent_dispatcher.send_tmux_message` / `verify_tmux_pane` to avoid real tmux.
- `agent_dispatcher.SessionLocal` and `display_writer.SessionLocal` to bind to
  the test's in-memory engine.
- `websocket.ws_manager.broadcast` to a no-op.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from models import (
    Agent,
    AgentMode,
    AgentStatus,
    Message,
    MessageRole,
    MessageStatus,
    Project,
)


def _fresh_agent_id() -> str:
    return uuid.uuid4().hex[:12]


def _mk_entry(msg_id: str, content: str = "hello",
              status: str = "queued",
              scheduled_at: str | None = None,
              created_at: str | None = None) -> dict:
    return {
        "id": msg_id,
        "role": "USER",
        "content": content,
        "source": "web",
        "status": status,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "scheduled_at": scheduled_at,
        "metadata": None,
    }


@pytest.fixture()
def ad_env(db_engine, monkeypatch):
    """Wire dispatcher + display_writer to the test engine, disable WS + tmux."""
    from display_writer import (
        DISPLAY_DIR,
        _display_path,
        _pre_sent_index,
        _pre_sent_index_ready,
        _pre_sent_lock,
    )
    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    # Route both modules' SessionLocal usage to the test engine.
    monkeypatch.setattr("agent_dispatcher.SessionLocal", Session)
    monkeypatch.setattr("database.SessionLocal", Session)
    monkeypatch.setattr("display_writer.SessionLocal", Session)

    # Avoid real ws/broadcast side-effects.
    async def _noop_broadcast(*args, **kwargs):
        return 0
    monkeypatch.setattr("websocket.ws_manager.broadcast", _noop_broadcast)

    # Default tmux stubs — tests override as needed.
    monkeypatch.setattr("agent_dispatcher.verify_tmux_pane", lambda _pane: True)
    sent: list[tuple[str, str]] = []

    def _send(pane: str, text: str) -> bool:
        sent.append((pane, text))
        return True
    monkeypatch.setattr("agent_dispatcher.send_tmux_message", _send)

    os.makedirs(DISPLAY_DIR, exist_ok=True)

    # Collect agent ids created by tests so we can clean up file + index.
    created_ids: list[str] = []

    def _mk_agent(status=AgentStatus.IDLE, tmux_pane="%42") -> str:
        db = Session()
        try:
            # Create a project if one doesn't exist.
            proj_name = "test-proj-pre"
            if not db.query(Project).filter_by(name=proj_name).first():
                db.add(Project(
                    name=proj_name, display_name="Test", path="/tmp/tp-pre",
                ))
                db.flush()  # satisfy FK before inserting the agent row
            aid = _fresh_agent_id()
            db.add(Agent(
                id=aid,
                project=proj_name,
                name="Test Agent",
                mode=AgentMode.AUTO,
                status=status,
                tmux_pane=tmux_pane,
                model="claude-opus-4-7",
            ))
            db.commit()
            created_ids.append(aid)
            return aid
        finally:
            db.close()

    ctx = {
        "Session": Session,
        "sent": sent,
        "mk_agent": _mk_agent,
    }
    yield ctx

    # Teardown — drop file + index residue for each agent.
    for aid in created_ids:
        try:
            os.unlink(_display_path(aid))
        except FileNotFoundError:
            pass
        with _pre_sent_lock:
            _pre_sent_index.pop(aid, None)
            _pre_sent_index_ready.discard(aid)


def _make_dispatcher():
    from unittest.mock import MagicMock
    from worker_manager import WorkerManager
    from agent_dispatcher import AgentDispatcher

    d = AgentDispatcher(MagicMock(spec=WorkerManager))
    # Prevent stray WS emits during tests — drop any coroutine/dict.
    def _drop(coro_or_dict):
        if hasattr(coro_or_dict, "close"):
            try:
                coro_or_dict.close()
            except Exception:
                pass
    d._emit = _drop
    return d


# ---------------------------------------------------------------------------
# dispatch_pending_message
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_dispatch_pending_promotes_pre_sent(ad_env):
    """dispatch_pending_message promotes the first queued _pre_sent entry to sent."""
    from display_writer import pre_sent_create, pre_sent_get, _display_path

    agent_id = ad_env["mk_agent"]()
    msg_id = uuid.uuid4().hex[:12]
    pre_sent_create(agent_id, _mk_entry(msg_id, content="ping"))

    d = _make_dispatcher()
    await d.dispatch_pending_message(agent_id)

    # Tmux send should have been invoked once.
    assert ad_env["sent"] == [("%42", "ping")]

    # DB row inserted with the same id, status=QUEUED (legacy "sent"), display_seq set.
    db = ad_env["Session"]()
    try:
        row = db.get(Message, msg_id)
        assert row is not None
        assert row.agent_id == agent_id
        assert row.role == MessageRole.USER
        assert row.status == MessageStatus.SENT
        assert row.source == "web"
        assert row.display_seq is not None
        assert row.delivered_at is None
        assert row.jsonl_uuid is None
    finally:
        db.close()

    # Pre-delivery index no longer has it.
    assert pre_sent_get(agent_id, msg_id) is None

    # File ends with a non-_pre_sent line carrying status=sent + seq.
    import json
    with open(_display_path(agent_id)) as f:
        lines = [json.loads(l) for l in f.read().splitlines() if l.strip()]
    # Last line is the sent line; the line before is the tombstone of the _pre_sent entry.
    sent_line = lines[-1]
    assert sent_line["id"] == msg_id
    assert sent_line["status"] == "sent"
    assert sent_line.get("_queued") is None
    assert sent_line.get("_pre") is None
    assert sent_line.get("_pre_sent") is None
    assert sent_line["seq"] == row.display_seq


@pytest.mark.anyio
async def test_dispatch_pending_skips_when_agent_busy(ad_env):
    """When the agent is EXECUTING, the queued entry stays untouched."""
    from display_writer import pre_sent_create, pre_sent_get

    agent_id = ad_env["mk_agent"](status=AgentStatus.EXECUTING)
    msg_id = uuid.uuid4().hex[:12]
    pre_sent_create(agent_id, _mk_entry(msg_id))

    d = _make_dispatcher()
    await d.dispatch_pending_message(agent_id)

    # Nothing sent; DB row not created; pre_sent still present.
    assert ad_env["sent"] == []
    db = ad_env["Session"]()
    try:
        assert db.get(Message, msg_id) is None
    finally:
        db.close()
    assert pre_sent_get(agent_id, msg_id) is not None


@pytest.mark.anyio
async def test_dispatch_pending_skips_scheduled_entries(ad_env):
    """Entries with scheduled_at are not touched by dispatch_pending_message."""
    from display_writer import pre_sent_create, pre_sent_get

    agent_id = ad_env["mk_agent"]()
    msg_id = uuid.uuid4().hex[:12]
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    pre_sent_create(
        agent_id,
        _mk_entry(msg_id, status="scheduled", scheduled_at=future),
    )

    d = _make_dispatcher()
    await d.dispatch_pending_message(agent_id)

    assert ad_env["sent"] == []
    assert pre_sent_get(agent_id, msg_id) is not None


# ---------------------------------------------------------------------------
# _dispatch_tmux_scheduled
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_dispatch_scheduled_picks_due_entries(ad_env):
    """_dispatch_tmux_scheduled promotes scheduled entries whose time has come.

    Marked async so an event loop is available for the `asyncio.ensure_future`
    call that ships the message_sent WS event (we stubbed the broadcast).
    """
    from display_writer import pre_sent_create, pre_sent_get

    agent_id = ad_env["mk_agent"]()
    msg_id = uuid.uuid4().hex[:12]
    past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    pre_sent_create(
        agent_id,
        _mk_entry(msg_id, content="scheduled hi", status="scheduled",
                  scheduled_at=past),
    )

    d = _make_dispatcher()
    db = ad_env["Session"]()
    try:
        d._dispatch_tmux_scheduled(db)
        db.commit()
    finally:
        db.close()

    assert ad_env["sent"] == [("%42", "scheduled hi")]
    db = ad_env["Session"]()
    try:
        row = db.get(Message, msg_id)
        assert row is not None
        assert row.status == MessageStatus.SENT
        assert row.display_seq is not None
    finally:
        db.close()
    assert pre_sent_get(agent_id, msg_id) is None


@pytest.mark.anyio
async def test_dispatch_scheduled_skips_future_entries(ad_env):
    """Entries with scheduled_at in the future stay in the index."""
    from display_writer import pre_sent_create, pre_sent_get

    agent_id = ad_env["mk_agent"]()
    msg_id = uuid.uuid4().hex[:12]
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    pre_sent_create(
        agent_id,
        _mk_entry(msg_id, status="scheduled", scheduled_at=future),
    )

    d = _make_dispatcher()
    db = ad_env["Session"]()
    try:
        d._dispatch_tmux_scheduled(db)
    finally:
        db.close()

    assert ad_env["sent"] == []
    assert pre_sent_get(agent_id, msg_id) is not None


# ---------------------------------------------------------------------------
# next_dispatch_seq
# ---------------------------------------------------------------------------

def test_next_dispatch_seq_considers_pre_sent(ad_env):
    """next_dispatch_seq returns max(db, pre_sent) + 1."""
    from display_writer import pre_sent_create
    from agent_dispatcher import AgentDispatcher

    agent_id = ad_env["mk_agent"]()

    # DB row with dispatch_seq=3.
    db = ad_env["Session"]()
    try:
        db.add(Message(
            id="dbmsgxxxxxxx",
            agent_id=agent_id,
            role=MessageRole.USER,
            content="done",
            status=MessageStatus.COMPLETED,
            source="web",
            dispatch_seq=3,
            display_seq=1,
        ))
        db.commit()
    finally:
        db.close()

    # Pre-delivery with a higher dispatch_seq=7.
    entry = _mk_entry(uuid.uuid4().hex[:12])
    entry["dispatch_seq"] = 7
    pre_sent_create(agent_id, entry)

    db = ad_env["Session"]()
    try:
        nxt = AgentDispatcher.next_dispatch_seq(db, agent_id)
        assert nxt == 8
    finally:
        db.close()


def test_next_dispatch_seq_defaults_to_one(ad_env):
    """With no rows and no pre-sent entries, next_dispatch_seq returns 1."""
    from agent_dispatcher import AgentDispatcher

    agent_id = ad_env["mk_agent"]()
    db = ad_env["Session"]()
    try:
        assert AgentDispatcher.next_dispatch_seq(db, agent_id) == 1
    finally:
        db.close()
