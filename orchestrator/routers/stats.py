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


def _day_bounds(day: str, tz_delta: timedelta = timedelta(0)) -> tuple[datetime, datetime]:
    """Parse YYYY-MM-DD (client-local) into [day_start, next_day_start) as UTC-naive."""
    d = datetime.strptime(day, "%Y-%m-%d")
    start_local = d.replace(tzinfo=None)
    end_local = start_local + timedelta(days=1)
    return start_local - tz_delta, end_local - tz_delta


@router.get("/viewing/week")
def viewing_week(
    end: str | None = Query(None, description="End date YYYY-MM-DD (default: today in client tz)"),
    days: int = Query(7, ge=1, le=31),
    tz_offset: int = Query(default=0, description="Client timezone offset in minutes (JS getTimezoneOffset)"),
    db: Session = Depends(get_db),
):
    """Return per-day totals and per-project totals over the last `days` days.

    ``tz_offset`` shifts day bucketing to client local time — without it the
    7-day window would start/end at UTC midnight and shift day labels for
    users outside UTC.

    Response shape:
    {
      "days": [{"date": "2026-04-14", "seconds": 1234, "by_project": {"p": 800, ...}}, ...],
      "projects": [{"project": "xylocopa", "seconds": 4500, "session_count": 3}, ...],
      "total_seconds": 12345
    }
    """
    # tz_delta: how much to add to a UTC-naive timestamp to get client local time.
    # JS getTimezoneOffset: +420 for PDT → client is UTC-7 → add -7h to UTC to get local.
    tz_delta = timedelta(minutes=-tz_offset)

    # Walk the window in client-local time, then translate bounds back to UTC for the DB query.
    if end:
        end_date_local = datetime.strptime(end, "%Y-%m-%d")
    else:
        now_local = datetime.now(timezone.utc).replace(tzinfo=None) + tz_delta
        end_date_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_date_local = end_date_local - timedelta(days=days - 1)
    window_end_local = end_date_local + timedelta(days=1)

    start_date_utc = start_date_local - tz_delta
    window_end_utc = window_end_local - tz_delta

    events = (
        db.query(SessionViewEvent)
        .filter(
            SessionViewEvent.ended_at >= start_date_utc,
            SessionViewEvent.started_at < window_end_utc,
        )
        .all()
    )

    # Bucket per day in client-local time. If an event straddles local midnight, split it.
    day_buckets: dict[str, dict] = {}
    for i in range(days):
        d = start_date_local + timedelta(days=i)
        day_buckets[d.strftime("%Y-%m-%d")] = {
            "date": d.strftime("%Y-%m-%d"),
            "seconds": 0,
            "by_project": {},
        }

    proj_totals: dict[str, int] = {}
    proj_sessions: dict[str, set[str]] = {}

    for ev in events:
        # Clip event to window (UTC-naive)
        e_start = max(ev.started_at, start_date_utc)
        e_end = min(ev.ended_at, window_end_utc)
        if e_end <= e_start:
            continue
        # Walk the days the event covers, in client-local time
        cursor_local = e_start + tz_delta
        e_end_local = e_end + tz_delta
        while cursor_local < e_end_local:
            day_key = cursor_local.strftime("%Y-%m-%d")
            next_midnight_local = (cursor_local + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
            slice_end_local = min(next_midnight_local, e_end_local)
            secs = int((slice_end_local - cursor_local).total_seconds())
            if secs > 0 and day_key in day_buckets:
                bucket = day_buckets[day_key]
                bucket["seconds"] += secs
                bucket["by_project"][ev.project] = (
                    bucket["by_project"].get(ev.project, 0) + secs
                )
                proj_totals[ev.project] = proj_totals.get(ev.project, 0) + secs
                proj_sessions.setdefault(ev.project, set()).add(ev.agent_id)
            cursor_local = slice_end_local

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
    date: str = Query(..., description="Date YYYY-MM-DD (interpreted in client local time)"),
    tz_offset: int = Query(default=0, description="Client timezone offset in minutes (JS getTimezoneOffset)"),
    db: Session = Depends(get_db),
):
    """Return the raw timeline of view intervals for a given day plus per-project totals.

    ``date`` is interpreted as a client-local calendar day; ``tz_offset`` maps it
    back to the UTC window used by the stored events.

    Response shape:
    {
      "date": "2026-04-14",
      "intervals": [{"agent_id": "...", "project": "...", "started_at": "...", "ended_at": "...", "seconds": N}, ...],
      "projects": [{"project": "p", "seconds": N, "session_count": K}, ...],
      "total_seconds": M
    }
    """
    tz_delta = timedelta(minutes=-tz_offset)
    start, end = _day_bounds(date, tz_delta)
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
