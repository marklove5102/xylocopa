"""Phase 1 tests: display_writer queued-partition APIs + reader support.

Covers the 4 new writer functions and the reader's partition logic:
  - flush_queued_entry  → queued list
  - update_queued_entry → latest content only
  - mark_deleted        → entry vanishes
  - promote_to_delivered→ entry moves to displayed partition (with seq)
  - promote race guard  → no corruption when display_seq already set
  - rebuild_agent       → re-emits queued entries from DB
"""

import json
import os
import uuid
from datetime import datetime, timezone

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
    """Create all tables once per session."""
    Base.metadata.drop_all(bind=engine)
    init_db()


@pytest.fixture
def clean_db():
    """Truncate all rows between tests (schema persists)."""
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
    """Create a minimal project + agent and return the agent id."""
    db = SessionLocal()
    try:
        proj = Project(
            name="phase1-tests",
            display_name="Phase 1 Tests",
            path="/tmp/phase1-tests",
        )
        db.add(proj)
        db.flush()
        a = Agent(
            id=_short_id(),
            project="phase1-tests",
            name="test-agent",
            mode=AgentMode.AUTO,
            status=AgentStatus.IDLE,
        )
        db.add(a)
        db.commit()
        aid = a.id
    finally:
        db.close()

    # Ensure display file starts empty for this agent.
    path = display_writer._display_path(aid)
    if os.path.exists(path):
        os.unlink(path)
    return aid


def _mk_message(agent_id, content="hello", status=MessageStatus.PENDING,
                role=MessageRole.USER, source="web", meta=None,
                delivered=False, display_seq=None):
    """Create + commit a Message row and return its id."""
    db = SessionLocal()
    try:
        m = Message(
            id=_short_id(),
            agent_id=agent_id,
            role=role,
            content=content,
            status=status,
            source=source,
            meta_json=json.dumps(meta) if meta else None,
            delivered_at=_now() if delivered else None,
            display_seq=display_seq,
        )
        db.add(m)
        db.commit()
        return m.id
    finally:
        db.close()


def _read_display_response(agent_id):
    """Read the display file and partition it the same way the API does.

    Returns (displayed_entries, queued_entries) as lists of dicts.
    """
    from schemas import DisplayEntry

    path = display_writer._display_path(agent_id)
    if not os.path.exists(path):
        return [], []
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    seen = {}
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        entry = DisplayEntry.model_validate(obj)
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


# ─────────────────────────── round-trip ────────────────────────────

def test_flush_queued_entry_round_trip(agent):
    msg_id = _mk_message(agent, content="hello world", status=MessageStatus.PENDING)

    display_writer.flush_queued_entry(agent, msg_id)

    displayed, queued = _read_display_response(agent)
    assert displayed == []
    assert len(queued) == 1
    q = queued[0]
    assert q.id == msg_id
    assert q.queued is True
    assert q.seq is None
    assert q.content == "hello world"
    assert q.status == MessageStatus.PENDING
    assert q.source == "web"

    # DB row must NOT have display_seq allocated.
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        assert m.display_seq is None
    finally:
        db.close()


# ─────────────────────────── queued replace ────────────────────────────

def test_update_queued_entry_replaces_content(agent):
    msg_id = _mk_message(agent, content="first draft")
    display_writer.flush_queued_entry(agent, msg_id)

    # Mutate DB: new content + status transition
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        m.content = "edited text"
        m.status = MessageStatus.QUEUED
        db.commit()
    finally:
        db.close()

    display_writer.update_queued_entry(agent, msg_id)

    displayed, queued = _read_display_response(agent)
    assert displayed == []
    assert len(queued) == 1
    assert queued[0].id == msg_id
    assert queued[0].content == "edited text"
    assert queued[0].status == MessageStatus.QUEUED


def test_update_queued_entry_noops_after_promotion(agent, caplog):
    msg_id = _mk_message(agent, content="x")
    display_writer.flush_queued_entry(agent, msg_id)

    # Simulate concurrent promotion: set display_seq directly.
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        m.display_seq = 7
        m.delivered_at = _now()
        db.commit()
    finally:
        db.close()

    # Count lines before
    before = _line_count(agent)
    display_writer.update_queued_entry(agent, msg_id)
    # Defensive no-op: no new line appended.
    assert _line_count(agent) == before


# ─────────────────────────── delete (tombstone) ────────────────────────────

def test_mark_deleted_removes_entry(agent):
    msg_id = _mk_message(agent, content="gone")
    display_writer.flush_queued_entry(agent, msg_id)
    displayed, queued = _read_display_response(agent)
    assert len(queued) == 1

    display_writer.mark_deleted(agent, msg_id)
    displayed, queued = _read_display_response(agent)
    assert queued == []
    assert displayed == []


# ─────────────────────────── promote ────────────────────────────

def test_promote_to_delivered_moves_partition(agent):
    msg_id = _mk_message(agent, content="will be delivered")
    display_writer.flush_queued_entry(agent, msg_id)

    # Caller preconditions: delivered_at set, display_seq still NULL.
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        m.delivered_at = _now()
        m.status = MessageStatus.COMPLETED
        db.commit()
    finally:
        db.close()

    display_writer.promote_to_delivered(agent, msg_id)

    displayed, queued = _read_display_response(agent)
    assert queued == []
    assert len(displayed) == 1
    d = displayed[0]
    assert d.id == msg_id
    assert d.seq == 1
    assert d.content == "will be delivered"

    # DB row should now carry the allocated display_seq.
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        assert m.display_seq == 1
    finally:
        db.close()


def test_promote_to_delivered_allocates_next_seq_after_existing(agent):
    # Seed one already-delivered message with seq=1 via flush_agent.
    first_id = _mk_message(agent, content="first", delivered=True,
                           status=MessageStatus.COMPLETED)
    display_writer.flush_agent(agent)

    # New queued message; promote it.
    second_id = _mk_message(agent, content="second")
    display_writer.flush_queued_entry(agent, second_id)
    db = SessionLocal()
    try:
        m = db.get(Message, second_id)
        m.delivered_at = _now()
        m.status = MessageStatus.COMPLETED
        db.commit()
    finally:
        db.close()

    display_writer.promote_to_delivered(agent, second_id)

    displayed, queued = _read_display_response(agent)
    assert queued == []
    assert len(displayed) == 2
    seqs = sorted(d.seq for d in displayed)
    assert seqs == [1, 2]


def test_promote_race_guard_with_preset_display_seq(agent):
    """If display_seq is already set (another path promoted first),
    promote_to_delivered must degrade to replace-in-place — no duplicate seq,
    no corruption.
    """
    msg_id = _mk_message(agent, content="racy")
    display_writer.flush_queued_entry(agent, msg_id)

    # Simulate concurrent promotion: seq already committed by another path.
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        m.display_seq = 5
        m.delivered_at = _now()
        m.status = MessageStatus.COMPLETED
        db.commit()
    finally:
        db.close()

    # Before: file has just the _queued line.
    before_lines = _line_count(agent)

    display_writer.promote_to_delivered(agent, msg_id)

    # After: one replace line appended — no tombstone, no new seq.
    after_lines = _line_count(agent)
    assert after_lines == before_lines + 1

    # display_seq must still be 5 (not bumped / replaced).
    db = SessionLocal()
    try:
        m = db.get(Message, msg_id)
        assert m.display_seq == 5
    finally:
        db.close()

    # Reader sees the entry on the displayed side with seq=5 (the _replace
    # line has seq=5 and no _queued marker, so it wins over the earlier
    # _queued line by dedup).
    displayed, queued = _read_display_response(agent)
    assert queued == []
    assert len(displayed) == 1
    assert displayed[0].seq == 5


# ─────────────────────────── rebuild ────────────────────────────

def test_rebuild_agent_reemits_queued(agent):
    # Queued message — no prior display file write.
    queued_id = _mk_message(agent, content="pending", status=MessageStatus.PENDING)
    # Delivered message — gets a seq.
    delivered_id = _mk_message(agent, content="done", delivered=True,
                               status=MessageStatus.COMPLETED)

    display_writer.rebuild_agent(agent)

    displayed, queued = _read_display_response(agent)
    assert len(displayed) == 1
    assert displayed[0].id == delivered_id
    assert len(queued) == 1
    assert queued[0].id == queued_id
    assert queued[0].content == "pending"


def test_rebuild_skips_cancelled_queued(agent):
    # CANCELLED queued msg must not be re-emitted.
    cancelled_id = _mk_message(agent, content="nope",
                               status=MessageStatus.CANCELLED)
    live_id = _mk_message(agent, content="live", status=MessageStatus.PENDING)

    display_writer.rebuild_agent(agent)

    _, queued = _read_display_response(agent)
    ids = {q.id for q in queued}
    assert live_id in ids
    assert cancelled_id not in ids


# ─────────────────────────── helpers ────────────────────────────

def _line_count(agent_id):
    path = display_writer._display_path(agent_id)
    if not os.path.exists(path):
        return 0
    with open(path, "r") as f:
        return sum(1 for line in f if line.strip())
