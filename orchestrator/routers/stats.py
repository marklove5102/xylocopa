"""Session-viewing time statistics — how long the user spent in each project."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Agent, SessionViewEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _day_bounds(day: str) -> tuple[datetime, datetime]:
    """Parse YYYY-MM-DD into [day_start, next_day_start) in UTC."""
    d = datetime.strptime(day, "%Y-%m-%d")
    start = d.replace(tzinfo=None)
    end = start + timedelta(days=1)
    return start, end


@router.get("/viewing/week")
def viewing_week(
    end: str | None = Query(None, description="End date YYYY-MM-DD (default: today)"),
    days: int = Query(7, ge=1, le=31),
    db: Session = Depends(get_db),
):
    """Return per-day totals and per-project totals over the last `days` days.

    Response shape:
    {
      "days": [{"date": "2026-04-14", "seconds": 1234, "by_project": {"p": 800, ...}}, ...],
      "projects": [{"project": "xylocopa", "seconds": 4500, "session_count": 3}, ...],
      "total_seconds": 12345
    }
    """
    if end:
        end_date = datetime.strptime(end, "%Y-%m-%d")
    else:
        end_date = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=None,
        )
    start_date = end_date - timedelta(days=days - 1)
    window_end = end_date + timedelta(days=1)

    events = (
        db.query(SessionViewEvent)
        .filter(
            SessionViewEvent.ended_at >= start_date,
            SessionViewEvent.started_at < window_end,
        )
        .all()
    )

    # Bucket per day (UTC). If an event straddles midnight, split it.
    day_buckets: dict[str, dict] = {}
    for i in range(days):
        d = start_date + timedelta(days=i)
        day_buckets[d.strftime("%Y-%m-%d")] = {
            "date": d.strftime("%Y-%m-%d"),
            "seconds": 0,
            "by_project": {},
        }

    proj_totals: dict[str, int] = {}
    proj_sessions: dict[str, set[str]] = {}

    for ev in events:
        # Clip event to window
        e_start = max(ev.started_at, start_date)
        e_end = min(ev.ended_at, window_end)
        if e_end <= e_start:
            continue
        # Walk days the event covers
        cursor = e_start
        while cursor < e_end:
            day_key = cursor.strftime("%Y-%m-%d")
            next_midnight = (cursor + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
            slice_end = min(next_midnight, e_end)
            secs = int((slice_end - cursor).total_seconds())
            if secs > 0 and day_key in day_buckets:
                bucket = day_buckets[day_key]
                bucket["seconds"] += secs
                bucket["by_project"][ev.project] = (
                    bucket["by_project"].get(ev.project, 0) + secs
                )
                proj_totals[ev.project] = proj_totals.get(ev.project, 0) + secs
                proj_sessions.setdefault(ev.project, set()).add(ev.agent_id)
            cursor = slice_end

    projects = sorted(
        [
            {
                "project": p,
                "seconds": s,
                "session_count": len(proj_sessions.get(p, set())),
            }
            for p, s in proj_totals.items()
        ],
        key=lambda r: -r["seconds"],
    )

    return {
        "days": [day_buckets[k] for k in sorted(day_buckets.keys())],
        "projects": projects,
        "total_seconds": sum(proj_totals.values()),
    }


@router.get("/viewing/day")
def viewing_day(
    date: str = Query(..., description="Date YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """Return the raw timeline of view intervals for a given day plus per-project totals.

    Response shape:
    {
      "date": "2026-04-14",
      "intervals": [{"agent_id": "...", "project": "...", "started_at": "...", "ended_at": "...", "seconds": N}, ...],
      "projects": [{"project": "p", "seconds": N, "session_count": K}, ...],
      "total_seconds": M
    }
    """
    start, end = _day_bounds(date)
    events = (
        db.query(SessionViewEvent)
        .filter(
            SessionViewEvent.ended_at >= start,
            SessionViewEvent.started_at < end,
        )
        .order_by(SessionViewEvent.started_at.asc())
        .all()
    )

    intervals = []
    proj_totals: dict[str, int] = {}
    proj_sessions: dict[str, set[str]] = {}
    total = 0
    for ev in events:
        e_start = max(ev.started_at, start)
        e_end = min(ev.ended_at, end)
        if e_end <= e_start:
            continue
        secs = int((e_end - e_start).total_seconds())
        intervals.append({
            "agent_id": ev.agent_id,
            "project": ev.project,
            "started_at": e_start.isoformat() + "Z",
            "ended_at": e_end.isoformat() + "Z",
            "seconds": secs,
        })
        proj_totals[ev.project] = proj_totals.get(ev.project, 0) + secs
        proj_sessions.setdefault(ev.project, set()).add(ev.agent_id)
        total += secs

    projects = sorted(
        [
            {
                "project": p,
                "seconds": s,
                "session_count": len(proj_sessions.get(p, set())),
            }
            for p, s in proj_totals.items()
        ],
        key=lambda r: -r["seconds"],
    )

    return {
        "date": date,
        "intervals": intervals,
        "projects": projects,
        "total_seconds": total,
    }
