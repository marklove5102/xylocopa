"""Lifetime spend across all CC sessions ever owned by a xylo agent.

Aggregates the persisted ended-session history (see `session_history.py`)
plus the live current session's running JSONL totals. Pricing math is
delegated to the `pricing` module.
"""
from __future__ import annotations

import logging
from typing import Any

from .pricing import compute_cost, resolve_pricing

logger = logging.getLogger(__name__)


def get_lifetime(
    agent_id: str,
    model: str | None,
    project_path: str | None,
    worktree: str | None,
    current_session_id: str | None,
) -> dict[str, Any]:
    """Aggregate token + cost across history file + current session.

    History records are written in `_rotate_agent_session` BEFORE the
    old session_id is overwritten. Current session is computed from
    its live JSONL since it has not yet ended.
    """
    from session_history import sum_history_usage, sum_jsonl_usage
    from agent_dispatcher import _resolve_session_jsonl as _resolve

    hist = sum_history_usage(agent_id)
    cur = {"input_tokens": 0, "output_tokens": 0,
           "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
           "turn_count": 0}
    if current_session_id and project_path:
        try:
            jsonl = _resolve(current_session_id, project_path, worktree)
            cur = sum_jsonl_usage(jsonl)
        except Exception:
            logger.debug("lifetime: current-session scan failed", exc_info=True)

    combined = {
        "input_tokens": hist["input_tokens"] + cur["input_tokens"],
        "output_tokens": hist["output_tokens"] + cur["output_tokens"],
        "cache_creation_input_tokens": hist["cache_creation_input_tokens"] + cur["cache_creation_input_tokens"],
        "cache_read_input_tokens": hist["cache_read_input_tokens"] + cur["cache_read_input_tokens"],
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
    }
