"""Lifetime spend across all CC sessions ever owned by a xylo agent.

Source of truth: the ``cc_sessions`` DB table (populated by rotation
hooks, the sync engine, and the reconcile sweep). For agents that
pre-date the migration to that table — and therefore have no rows yet —
we fall back to the legacy file-backed history (`session_history.py`).

The per-turn pricing math is delegated to the ``pricing`` module so the
on-disk USD-per-million-token rates only live in one place.
"""
from __future__ import annotations

import logging
from typing import Any

from .pricing import compute_cost, resolve_pricing

logger = logging.getLogger(__name__)


_USAGE_KEYS = (
    "input_tokens", "output_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
)


def _empty_totals() -> dict[str, int]:
    return {k: 0 for k in _USAGE_KEYS}


def _row_usage(row) -> dict[str, int]:
    """Coerce a CCSession row into the four-key ``usage`` shape."""
    return {
        "input_tokens": int(row.total_input_tokens or 0),
        "output_tokens": int(row.total_output_tokens or 0),
        "cache_creation_input_tokens": int(row.total_cache_creation_tokens or 0),
        "cache_read_input_tokens": int(row.total_cache_read_tokens or 0),
    }


def _iso(dt) -> str | None:
    """Best-effort ISO conversion that tolerates missing values."""
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except AttributeError:
        return str(dt)


def _row_to_node(row, model_for_cost: str | None) -> dict[str, Any]:
    """Render one CCSession row as a tree-node dict for the frontend."""
    totals = _row_usage(row)
    cost = compute_cost(totals, row.model or model_for_cost)
    return {
        "session_id": row.session_id,
        "started_at": _iso(row.started_at),
        "ended_at": _iso(row.ended_at),
        "end_reason": row.end_reason,
        "model": row.model,
        "is_subagent_session": bool(row.is_subagent_session),
        "totals": totals,
        "total_tokens": sum(totals.values()),
        "cost_usd": round(cost, 6),
        "turn_count": int(row.turn_count or 0),
        "sub_sessions": [],
    }


def build_cc_session_tree(rows, model_for_cost: str | None = None) -> list[dict[str, Any]]:
    """Walk the flat list of CCSession rows and return a top-level tree.

    Top-level rows have ``parent_session_id IS NULL``. Sub-sessions are
    nested under their parent's ``sub_sessions`` array. Orphan
    sub-sessions (parent missing — e.g. parent reaped before child
    reconciled) are surfaced at the top level so they don't disappear.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_id[row.session_id] = _row_to_node(row, model_for_cost)

    top_level: list[dict[str, Any]] = []
    for row in rows:
        node = by_id[row.session_id]
        parent_id = row.parent_session_id
        if parent_id and parent_id in by_id:
            by_id[parent_id]["sub_sessions"].append(node)
        else:
            top_level.append(node)
    return top_level


def _aggregate_totals_from_rows(rows) -> tuple[dict[str, int], int, int]:
    """Sum totals across ALL rows (top-level + subs both have agent_id)."""
    totals = _empty_totals()
    turn_count = 0
    for row in rows:
        u = _row_usage(row)
        for k in _USAGE_KEYS:
            totals[k] += u[k]
        turn_count += int(row.turn_count or 0)
    top_level_count = sum(1 for r in rows if r.parent_session_id is None)
    return totals, turn_count, top_level_count


def _current_session_running_node(
    agent_id: str,
    model: str | None,
    project_path: str | None,
    worktree: str | None,
    current_session_id: str,
) -> tuple[dict[str, int], int, dict[str, Any] | None]:
    """Probe the live JSONL of the current session for an in-flight delta.

    Returns ``(totals, turn_count, node)``. If we can't resolve or read
    the JSONL we return zeros and ``None`` so the caller skips the row.
    """
    if not current_session_id or not project_path:
        return _empty_totals(), 0, None
    try:
        from agent_dispatcher import _resolve_session_jsonl as _resolve
        from session_history import sum_jsonl_usage
        jsonl = _resolve(current_session_id, project_path, worktree)
        cur = sum_jsonl_usage(jsonl)
    except Exception:
        logger.debug("lifetime: current-session scan failed", exc_info=True)
        return _empty_totals(), 0, None

    totals = {k: int(cur.get(k, 0) or 0) for k in _USAGE_KEYS}
    turn_count = int(cur.get("turn_count", 0) or 0)
    if sum(totals.values()) == 0 and turn_count == 0:
        return totals, turn_count, None

    cost = compute_cost(totals, model)
    node = {
        "session_id": current_session_id,
        "started_at": None,
        "ended_at": None,
        "end_reason": "active",
        "model": model,
        "is_subagent_session": False,
        "totals": totals,
        "total_tokens": sum(totals.values()),
        "cost_usd": round(cost, 6),
        "turn_count": turn_count,
        "sub_sessions": [],
    }
    return totals, turn_count, node


def get_lifetime(
    agent_id: str,
    model: str | None,
    project_path: str | None,
    worktree: str | None,
    current_session_id: str | None,
) -> dict[str, Any]:
    """Aggregate token + cost across all CC sessions for this agent.

    Primary source: the ``cc_sessions`` table queried by ``agent_id``.
    Includes both top-level and sub-sessions — they all carry the same
    ``agent_id`` so they sum naturally. The current session may not yet
    be in the table (first turn hasn't been synced); when missing we
    overlay its running JSONL totals as a synthetic ``end_reason='active'``
    node so the displayed lifetime stays consistent with what the user
    sees in the live chat.

    Fallback: if the ``cc_sessions`` table has zero rows for this agent
    we read the legacy file-history via ``session_history.sum_history_usage``,
    so agents that pre-date the migration still report correct totals.

    Returns a dict shaped for backwards compatibility with the existing
    frontend popover, with one new key:

    - ``cc_sessions``: list of top-level session dicts (sub-sessions
      nested under each one's ``sub_sessions`` array) for tree drill-down.
    """
    from database import SessionLocal
    from models import CCSession

    db = SessionLocal()
    try:
        rows = (
            db.query(CCSession)
            .filter(CCSession.agent_id == agent_id)
            .order_by(CCSession.started_at)
            .all()
        )
    except Exception:
        logger.warning("lifetime: cc_sessions query failed", exc_info=True)
        rows = []
    finally:
        db.close()

    cc_session_ids = {r.session_id for r in rows}
    have_db_rows = len(rows) > 0

    # --- DB-backed path ----------------------------------------------------
    if have_db_rows:
        totals, turn_count, top_level_count = _aggregate_totals_from_rows(rows)
        tree = build_cc_session_tree(rows, model)

        # If the live current session_id is not yet persisted, overlay
        # its running JSONL totals so the displayed lifetime keeps up.
        if current_session_id and current_session_id not in cc_session_ids:
            cur_totals, cur_turns, cur_node = _current_session_running_node(
                agent_id, model, project_path, worktree, current_session_id,
            )
            if cur_node is not None:
                for k in _USAGE_KEYS:
                    totals[k] += cur_totals[k]
                turn_count += cur_turns
                tree.append(cur_node)
                top_level_count += 1

        total_tokens = sum(totals.values())
        cost_usd = compute_cost(totals, model)
        pricing = resolve_pricing(model)

        return {
            "session_count": top_level_count,
            "history_session_count": top_level_count,
            "turn_count": turn_count,
            "total_tokens": total_tokens,
            "by_kind": totals,
            "estimated_cost_usd": round(cost_usd, 4),
            "pricing_model": model,
            "pricing_per_million": pricing,
            "cc_sessions": tree,
        }

    # --- Legacy file-history fallback --------------------------------------
    from session_history import sum_history_usage

    hist = sum_history_usage(agent_id)
    cur = {**_empty_totals(), "turn_count": 0}
    if current_session_id and project_path:
        try:
            from agent_dispatcher import _resolve_session_jsonl as _resolve
            from session_history import sum_jsonl_usage
            jsonl = _resolve(current_session_id, project_path, worktree)
            cur = sum_jsonl_usage(jsonl)
        except Exception:
            logger.debug("lifetime: current-session scan failed", exc_info=True)

    combined = {
        "input_tokens": hist["input_tokens"] + cur["input_tokens"],
        "output_tokens": hist["output_tokens"] + cur["output_tokens"],
        "cache_creation_input_tokens":
            hist["cache_creation_input_tokens"] + cur["cache_creation_input_tokens"],
        "cache_read_input_tokens":
            hist["cache_read_input_tokens"] + cur["cache_read_input_tokens"],
    }
    total_tokens = sum(combined.values())
    cost_usd = compute_cost(combined, model)
    pricing = resolve_pricing(model)

    return {
        "session_count": hist["sessions"] + (1 if current_session_id else 0),
        "history_session_count": hist["sessions"],
        "turn_count": hist["turn_count"] + cur["turn_count"],
        "total_tokens": total_tokens,
        "by_kind": combined,
        "estimated_cost_usd": round(cost_usd, 4),
        "pricing_model": model,
        "pricing_per_million": pricing,
        "cc_sessions": [],
    }
