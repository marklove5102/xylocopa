"""Background tick loop that accumulates session viewing time.

Every TICK_SECONDS the loop asks the WebSocket manager which agents are
currently the "primary" view of at least one focused client, and appends
or extends a SessionViewEvent row for each distinct agent.

Multiple clients viewing the same agent are counted once (set dedup in
ws_manager.active_primary_agents()). If a client goes idle (no user
interaction within the frontend's idle threshold), it reports primary=None
and stops contributing.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from database import SessionLocal
from models import Agent, SessionViewEvent
from websocket import ws_manager

logger = logging.getLogger("orchestrator.view_tracking")

TICK_SECONDS = 10
# Gap threshold — if the last recorded event for an agent ended more than
# this many seconds ago, start a fresh event instead of extending.
GAP_SECONDS = TICK_SECONDS * 2 + 5  # 25s — one missed tick still stitches


def _record_tick(db: Session, agent_ids: set[str], now: datetime) -> None:
    """Extend or create a view event for each agent. Runs under one tx."""
    if not agent_ids:
        return
    # Cache agents → project lookup in one query
    agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
    project_of = {a.id: a.project for a in agents}
    for aid in agent_ids:
        project = project_of.get(aid)
        if not project:
            # Agent might have been deleted — skip silently
            continue
        # Find the most recent event for this agent
        last = (
            db.query(SessionViewEvent)
            .filter(SessionViewEvent.agent_id == aid)
            .order_by(SessionViewEvent.ended_at.desc())
            .first()
        )
        gap = (now - last.ended_at).total_seconds() if last else None
        if last and gap is not None and gap <= GAP_SECONDS:
            # Extend the ongoing interval
            last.ended_at = now
            last.seconds = int((last.ended_at - last.started_at).total_seconds())
        else:
            # New interval — backdate its start by one tick so a single
            # tick still registers as TICK_SECONDS of viewing.
            started = now - timedelta(seconds=TICK_SECONDS)
            db.add(SessionViewEvent(
                agent_id=aid,
                project=project,
                started_at=started,
                ended_at=now,
                seconds=TICK_SECONDS,
            ))
    db.commit()


async def run_tick_loop() -> None:
    """Run forever; one tick every TICK_SECONDS."""
    logger.info("view-tracking tick loop started (interval=%ds)", TICK_SECONDS)
    while True:
        try:
            await asyncio.sleep(TICK_SECONDS)
            agent_ids = ws_manager.active_primary_agents()
            if not agent_ids:
                continue
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db = SessionLocal()
            try:
                _record_tick(db, agent_ids, now)
            finally:
                db.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("view-tracking tick failed; continuing")
