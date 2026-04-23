"""Phase 2A tests: writer-site migration + sync_engine deferred flush + flag.

Focuses on the behaviour changes introduced by Phase 2A:
  - cancel_message appends a `_deleted` tombstone (soft-cancel only)
  - update_message widens status accept to PENDING/QUEUED and calls
    update_queued_entry
  - get_agent_display gates the DB fallback behind XY_QUEUED_FALLBACK
  - sync_engine defers promote_to_delivered until after db.commit
  - UserPromptSubmit hook promotes via promote_to_delivered

Each test mutates the environment or monkey-patches the display_writer
so we can observe behaviour without a live FastAPI server.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

# conftest.py has already redirected DB_PATH/DISPLAY_DIR and prepended the
# orchestrator dir to sys.path.
from database import SessionLocal, engine, init_db
from models import (
    Agent,
    AgentMode,
    AgentStatus,
    Base,
    Message,
    MessageRole,
    MessageStatus,
    Project,
)
import display_writer


def _now():
    return datetime.now(timezone.utc)


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture(scope="session", autouse=True)
def _init_schema():
    Base.metadata.drop_all(bind=engine)
    init_db()


@pytest.fixture
def clean_db():
    db = SessionLocal()
    try:
        db.query(Message).delete()
        db.query(Agent).delete()
        db.query(Project).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def agent(clean_db):
    db = SessionLocal()
    try:
        proj = Project(
            name="phase2a-tests",
            display_name="Phase 2A Tests",
            path="/tmp/phase2a-tests",
        )
        db.add(proj)
        db.flush()
        a = Agent(
            id=_short_id(),
            project="phase2a-tests",
            name="test-agent",
            mode=AgentMode.AUTO,
            status=AgentStatus.IDLE,
        )
        db.add(a)
        db.commit()
        aid = a.id
    finally:
        db.close()

    path = display_writer._display_path(aid)
    if os.path.exists(path):
        os.unlink(path)
    return aid


def _mk_message(agent_id, content="hello", status=MessageStatus.PENDING,
                role=MessageRole.USER, source="web",
                delivered=False, display_seq=None):
    db = SessionLocal()
    try:
        m = Message(
            id=_short_id(),
            agent_id=agent_id,
            role=role,
            content=content,
            status=status,
            source=source,
            delivered_at=_now() if delivered else None,
            display_seq=display_seq,
        )
        db.add(m)
        db.commit()
        return m.id
    finally:
        db.close()


def _read_raw_lines(agent_id):
    path = display_writer._display_path(agent_id)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def _read_partitioned(agent_id):
    """Same partition logic as get_agent_display, returns (displayed, queued)."""
    from schemas import DisplayEntry

    raw = _read_raw_lines(agent_id)
    seen = {}
    for obj in raw:
        try:
            entry = DisplayEntry.model_validate(obj)
        except Exception:
            continue
        seen[entry.id] = entry

    displayed, queued = [], []
    for entry in seen.values():
        if entry.deleted:
            continue
        if entry.queued:
            queued.append(entry)
        elif entry.seq is not None:
            displayed.append(entry)
    return displayed, queued


# ─────────────────────────── cancel flow ────────────────────────────

def test_cancel_appends_tombstone_and_queued_entry_vanishes(agent):
    """cancel_message soft-cancels + writes a _deleted tombstone so the
    bubble disappears from the reader's queued list."""
    msg_id = _mk_message(agent, content="to-be-cancelled",
                         status=MessageStatus.PENDING)
    display_writer.flush_queued_entry(agent, msg_id)

    _, queued = _read_partitioned(agent)
    assert len(queued) == 1

    # Simulate the cancel endpoint's post-commit step: status + mark_deleted
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        m.status = MessageStatus.CANCELLED
        db.commit()
    finally:
        db.close()
    display_writer.mark_deleted(agent, msg_id)

    _, queued = _read_partitioned(agent)
    assert queued == [], "tombstone should remove entry from queued partition"


def test_cancel_endpoint_soft_cancels_only_pre_delivery(clean_db):
    """cancel_message HTTP endpoint now rejects non-PENDING/QUEUED status.
    The old CANCELLED→hard-delete branch has been removed."""
    # We call the endpoint function directly with a stand-in db Session.
    from fastapi import HTTPException

    # Direct import of the endpoint function — it's an async def that takes
    # agent_id, message_id, db.
    from routers.agents import cancel_message

    # Seed agent + already-CANCELLED message
    db = SessionLocal()
    try:
        proj = Project(name="cancel-endpoint", display_name="x", path="/tmp/x")
        db.add(proj)
        db.flush()
        a = Agent(id=_short_id(), project="cancel-endpoint", name="a",
                  mode=AgentMode.AUTO, status=AgentStatus.IDLE)
        db.add(a)
        db.commit()
        aid = a.id

        m = Message(
            id=_short_id(),
            agent_id=aid,
            role=MessageRole.USER,
            content="already-cancelled",
            status=MessageStatus.CANCELLED,
            source="web",
        )
        db.add(m)
        db.commit()
        mid = m.id
    finally:
        db.close()

    import asyncio
    db2 = SessionLocal()
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(cancel_message(aid, mid, db2))
        assert exc.value.status_code == 400
    finally:
        db2.close()


# ─────────────────────────── modify flow ────────────────────────────

def test_update_message_appends_queued_replace(agent):
    """After the update_message endpoint commits a content edit, the
    display file gets a _queued+_replace line."""
    msg_id = _mk_message(agent, content="original",
                         status=MessageStatus.PENDING)
    display_writer.flush_queued_entry(agent, msg_id)

    # Simulate endpoint post-commit: DB content changed, then
    # update_queued_entry appends replace line.
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        m.content = "edited"
        db.commit()
    finally:
        db.close()
    display_writer.update_queued_entry(agent, msg_id)

    raw = _read_raw_lines(agent)
    assert len(raw) == 2
    assert raw[0].get("_queued") is True and raw[0].get("content") == "original"
    assert (raw[1].get("_queued") is True
            and raw[1].get("_replace") is True
            and raw[1].get("content") == "edited")

    _, queued = _read_partitioned(agent)
    assert len(queued) == 1 and queued[0].content == "edited"


def test_update_message_accepts_queued_status(agent):
    """Status check widened from PENDING-only to PENDING-or-QUEUED."""
    msg_id = _mk_message(agent, content="x", status=MessageStatus.QUEUED)
    display_writer.flush_queued_entry(agent, msg_id)

    import asyncio
    from routers.agents import update_message
    from schemas import UpdateMessage

    db = SessionLocal()
    try:
        out = asyncio.run(update_message(
            agent, msg_id,
            UpdateMessage(content="edited-while-queued"),
            db,
        ))
        assert out.content == "edited-while-queued"
    finally:
        db.close()

    _, queued = _read_partitioned(agent)
    assert len(queued) == 1
    assert queued[0].content == "edited-while-queued"


# ─────────────────────────── UserPromptSubmit promotion ────────────────────────────

def test_hook_promotes_via_promote_to_delivered(agent):
    """The UserPromptSubmit pathway: DB commit sets delivered_at, then
    promote_to_delivered tombstones the queued entry and writes a fresh
    delivered line with display_seq."""
    msg_id = _mk_message(agent, content="submitted",
                         status=MessageStatus.QUEUED)
    display_writer.flush_queued_entry(agent, msg_id)

    # Simulate hook: mark delivered + COMPLETED, then promote.
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        m.delivered_at = _now()
        m.status = MessageStatus.COMPLETED
        m.completed_at = m.delivered_at
        db.commit()
    finally:
        db.close()
    display_writer.promote_to_delivered(agent, msg_id)

    displayed, queued = _read_partitioned(agent)
    assert queued == []
    assert len(displayed) == 1
    assert displayed[0].id == msg_id
    assert displayed[0].seq == 1

    db = SessionLocal()
    try:
        assert db.get(Message, msg_id).display_seq == 1
    finally:
        db.close()


# ─────────────────────────── sync_engine deferred flush ────────────────────────────

def test_sync_engine_defers_promote_until_after_commit(agent):
    """`_promote_or_create_user_msg` must NOT call the display writer
    inline — it must append to `deferred_promotions`. The caller (import
    loop) invokes promote_to_delivered post-commit."""
    import asyncio
    from sync_engine import _promote_or_create_user_msg

    # Seed an unlinked QUEUED web message that matches by content
    msg_id = _mk_message(agent, content="sync-me",
                         status=MessageStatus.QUEUED)
    display_writer.flush_queued_entry(agent, msg_id)

    # Fake SyncContext (only .agent_id is used by this branch)
    class _Ctx:
        agent_id = agent
    ctx = _Ctx()

    deferred: list[str] = []
    promote_calls: list[tuple[str, str]] = []

    # Run inside an event loop so ensure_future (for WS emit) has a loop.
    async def _run():
        with patch("display_writer.promote_to_delivered",
                   side_effect=lambda aid, mid: promote_calls.append((aid, mid))):
            db = SessionLocal()
            try:
                return _promote_or_create_user_msg(
                    db, ctx, "sync-me", jsonl_uuid="uuid-" + _short_id(),
                    seq=0, meta=None, kind=None, jsonl_ts=None,
                    deferred_promotions=deferred,
                )
            finally:
                db.close()

    result = asyncio.run(_run())

    assert result is None, "promotion should return None (no new insert)"
    assert deferred == [msg_id], "msg id should be deferred, not flushed inline"
    assert promote_calls == [], "promote_to_delivered must NOT be called inline"


def test_sync_engine_no_deferred_when_no_match():
    """When there's no matching web message, _promote_or_create_user_msg
    creates a new CLI message and does NOT touch the deferred list."""
    from sync_engine import _promote_or_create_user_msg

    # No agent / no message to match against — use dummy ctx with random id
    fake_agent_id = _short_id()
    proj_name = "sync-no-match"
    db = SessionLocal()
    try:
        proj = Project(name=proj_name, display_name=proj_name,
                       path="/tmp/" + proj_name)
        db.add(proj)
        db.flush()
        a = Agent(id=fake_agent_id, project=proj_name, name="a",
                  mode=AgentMode.AUTO, status=AgentStatus.IDLE)
        db.add(a)
        db.commit()
    finally:
        db.close()

    class _Ctx:
        agent_id = fake_agent_id
    ctx = _Ctx()

    deferred: list[str] = []
    db = SessionLocal()
    try:
        result = _promote_or_create_user_msg(
            db, ctx, "cli-typed", jsonl_uuid="uuid-" + _short_id(),
            seq=0, meta=None, kind=None, jsonl_ts=None,
            deferred_promotions=deferred,
        )
    finally:
        db.close()

    assert result is not None, "a new CLI Message should be returned"
    assert result.source == "cli"
    assert deferred == [], "no web message was promoted"


# ─────────────────────────── feature flag ────────────────────────────

def test_flag_off_hides_db_fallback_when_file_empty(agent, monkeypatch):
    """With XY_QUEUED_FALLBACK=0 and no queued entries in the file, the
    reader must NOT fall back to the DB — returns an empty queued list."""
    _mk_message(agent, content="flagged-out", status=MessageStatus.PENDING)
    # NO flush_queued_entry — mimics a pre-migration DB row.

    # Reload config module with the flag off and re-patch the router.
    monkeypatch.setenv("XY_QUEUED_FALLBACK", "0")
    import importlib
    import config
    importlib.reload(config)
    import routers.agents as agents_router
    importlib.reload(agents_router)

    import asyncio
    from fastapi import Request
    # Build a minimal call to get_agent_display
    db = SessionLocal()
    try:
        resp = asyncio.run(agents_router.get_agent_display(
            agent, offset=0, tail_bytes=0, db=db,
        ))
    finally:
        db.close()

    # No display file yet + flag off → queued is empty.
    assert resp.queued == []

    # Reset the flag + re-reload for subsequent tests
    monkeypatch.setenv("XY_QUEUED_FALLBACK", "1")
    importlib.reload(config)
    importlib.reload(agents_router)


def test_flag_on_uses_db_fallback(agent, monkeypatch):
    """With the flag on (default) and no queued entries in the file,
    the reader falls back to the DB query."""
    _mk_message(agent, content="fallback-used", status=MessageStatus.PENDING)

    monkeypatch.setenv("XY_QUEUED_FALLBACK", "1")
    import importlib
    import config
    importlib.reload(config)
    import routers.agents as agents_router
    importlib.reload(agents_router)

    import asyncio
    db = SessionLocal()
    try:
        resp = asyncio.run(agents_router.get_agent_display(
            agent, offset=0, tail_bytes=0, db=db,
        ))
    finally:
        db.close()

    # No display file, but the DB fallback kicks in.
    assert len(resp.queued) == 1
    assert resp.queued[0].content == "fallback-used"
