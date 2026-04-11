"""Comprehensive tests for agent dispatcher internals."""

import pytest

from models import Agent, AgentMode, AgentStatus, Message, MessageRole, MessageStatus, Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyWorkerManager:
    """Stub WorkerManager that should never be called in these tests."""

    def ensure_project_ready(self, _project):
        raise AssertionError("DummyWorkerManager.ensure_project_ready should not be called")



# ===========================================================================
# Liveness check tests (_reap_dead_agents)
# ===========================================================================


@pytest.mark.anyio
async def test_liveness_check_stops_idle_agents_without_sync_task(db_engine, monkeypatch):
    """IDLE tmux agents without a sync task should be stopped by _reap_dead_agents."""
    from sqlalchemy.orm import sessionmaker
    from agent_dispatcher import AgentDispatcher

    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    db.add(Project(name="idle-proj2", display_name="IP2", path="/tmp/ip2"))
    db.flush()
    agent = Agent(
        id="idlenosync11",
        project="idle-proj2",
        name="Idle No Sync",
        status=AgentStatus.IDLE,
        cli_sync=True,
    )
    db.add(agent)
    db.commit()

    dispatcher = AgentDispatcher(DummyWorkerManager())

    def _drop_coro(coro):
        try:
            coro.close()
        except Exception:
            pass

    dispatcher._emit = _drop_coro

    monkeypatch.setattr(
        "agent_dispatcher._build_tmux_claude_map",
        lambda: {},
    )
    dispatcher._tmux_map_cache = None

    dispatcher._reap_dead_agents(db)
    db.flush()

    # IDLE agent without sync task should be stopped
    assert agent.status == AgentStatus.STOPPED
    db.close()


@pytest.mark.anyio
async def test_liveness_check_skips_stopped_agents(db_engine, monkeypatch):
    """STOPPED agents should not be re-processed by _reap_dead_agents."""
    from sqlalchemy.orm import sessionmaker
    from agent_dispatcher import AgentDispatcher

    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    db.add(Project(name="stop-proj", display_name="SP", path="/tmp/sp"))
    db.flush()
    agent = Agent(
        id="stopped11111",
        project="stop-proj",
        name="Stopped Agent",
        status=AgentStatus.STOPPED,
        cli_sync=True,
    )
    db.add(agent)
    db.commit()

    dispatcher = AgentDispatcher(DummyWorkerManager())

    def _drop_coro(coro):
        try:
            coro.close()
        except Exception:
            pass

    dispatcher._emit = _drop_coro

    monkeypatch.setattr(
        "agent_dispatcher._build_tmux_claude_map",
        lambda: {},
    )
    dispatcher._tmux_map_cache = None

    dispatcher._reap_dead_agents(db)
    db.flush()

    # STOPPED agent should remain STOPPED (not re-processed)
    assert agent.status == AgentStatus.STOPPED
    db.close()




# ===========================================================================
# Pane matching
# ===========================================================================


def test_agent_session_name_format():
    """Session name should be ah-{agent_id[:8]}."""
    agent_id = "abcdef123456"
    session_name = f"ah-{agent_id[:8]}"
    assert session_name == "ah-abcdef12"
    assert session_name.startswith("ah-")
    assert len(session_name) == 11  # "ah-" (3) + 8 chars


# ===========================================================================
# Model-level tests
# ===========================================================================


def test_agent_cli_sync_default_true(db_engine):
    """Model-level default cli_sync is True."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    db.add(Project(name="cs-proj", display_name="CS", path="/tmp/cs"))
    db.flush()
    agent = Agent(
        id="clisyncdef11",
        project="cs-proj",
        name="CLI Default Agent",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    assert agent.cli_sync is True
    db.close()


def test_agent_tmux_pane_nullable(db_engine):
    """tmux_pane can be None."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    db.add(Project(name="tp-proj", display_name="TP", path="/tmp/tp"))
    db.flush()
    agent = Agent(
        id="tmuxpanenu11",
        project="tp-proj",
        name="No Pane Agent",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    assert agent.tmux_pane is None
    db.close()


def test_agent_session_id_nullable(db_engine):
    """session_id can be None."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    db.add(Project(name="si-proj", display_name="SI", path="/tmp/si"))
    db.flush()
    agent = Agent(
        id="sessidnull11",
        project="si-proj",
        name="No Session Agent",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    assert agent.session_id is None
    db.close()


def test_agent_timeout_default(db_engine):
    """Default timeout_seconds=1800."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    db.add(Project(name="to-proj", display_name="TO", path="/tmp/to"))
    db.flush()
    agent = Agent(
        id="timeoutdef11",
        project="to-proj",
        name="Timeout Agent",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    assert agent.timeout_seconds == 1800
    db.close()


def test_agent_parent_child_relationship(db_engine):
    """parent_id links to another agent."""
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = Session()
    db.add(Project(name="pc-proj", display_name="PC", path="/tmp/pc"))
    db.flush()
    parent = Agent(
        id="parentag1111",
        project="pc-proj",
        name="Parent Agent",
        status=AgentStatus.IDLE,
    )
    db.add(parent)
    db.commit()

    child = Agent(
        id="childag11111",
        project="pc-proj",
        name="Child Agent",
        status=AgentStatus.IDLE,
        parent_id=parent.id,
        is_subagent=True,
    )
    db.add(child)
    db.commit()
    db.refresh(child)

    assert child.parent_id == "parentag1111"
    assert child.is_subagent is True

    # Verify the parent exists and can be loaded
    loaded_parent = db.get(Agent, child.parent_id)
    assert loaded_parent is not None
    assert loaded_parent.id == parent.id
    assert loaded_parent.name == "Parent Agent"
    db.close()
