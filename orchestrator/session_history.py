"""Per-agent session history — file-backed.

Each xylo agent owns multiple CC sessions over its lifetime (rotated
on /compact, /clear, manual restart). Anthropic's `usage` block is
per-turn within one CLI session; to compute xylo lifetime spend we
must persist a summary of each completed session before it gets GC'd.

Storage layout:
  ~/.xylocopa/agent-sessions/<agent_id>.jsonl
    {"session_id": "...", "project_path": "...", "worktree": "...",
     "started_at": "...", "ended_at": "...", "end_reason": "compact|clear|stopped",
     "model": "claude-opus-4-7", "usage": {input, output, cache_create, cache_read},
     "turn_count": N}

One file per agent — easy enumeration, easy cleanup on agent delete,
append-only so no locking concerns. The CURRENT session is NOT in the
file; lifetime = sum(history) + current session running total.

This is independent of Claude Code's `~/.claude/history.jsonl` (which
is project-keyed, not agent-keyed) and the `.owner` sidecar mechanism
(which only tracks the current session — old sidecars get GC'd).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


XYLOCOPA_DATA_DIR = os.path.expanduser(
    os.environ.get("XYLOCOPA_DATA_DIR", "~/.xylocopa")
)
HISTORY_DIR = os.path.join(XYLOCOPA_DATA_DIR, "agent-sessions")


def _history_file(agent_id: str) -> str:
    return os.path.join(HISTORY_DIR, f"{agent_id}.jsonl")


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
def append_ended_session(
    agent_id: str,
    session_id: str,
    project_path: str,
    worktree: str | None,
    end_reason: str,
    model: str | None,
    usage: dict[str, int],
    turn_count: int = 0,
    started_at: str | None = None,
) -> bool:
    """Append one session-ended record to the agent's history file.

    Called from `_rotate_agent_session` (compact/clear/manual rotate)
    BEFORE the agent.session_id field is overwritten. Idempotent: a
    duplicate session_id will just create a duplicate record (harmless,
    aggregation is by-row not by-key).
    """
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
    except OSError as e:
        logger.warning("session_history: mkdir failed: %s", e)
        return False

    record = {
        "session_id": session_id,
        "project_path": project_path,
        "worktree": worktree,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "end_reason": end_reason,
        "model": model,
        "usage": usage,
        "turn_count": turn_count,
    }
    try:
        with open(_history_file(agent_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except OSError as e:
        logger.warning("session_history.append failed for %s: %s",
                       agent_id[:8], e)
        return False


def remove_history(agent_id: str) -> bool:
    """Delete an agent's history file (called on agent removal).

    Best-effort — missing file is not an error.
    """
    path = _history_file(agent_id)
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return True
    except OSError as e:
        logger.warning("session_history.remove failed for %s: %s",
                       agent_id[:8], e)
        return False


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
_USAGE_KEYS = (
    "input_tokens", "output_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
)


def read_history(agent_id: str) -> list[dict[str, Any]]:
    """Read all ended-session records for an agent, oldest-first."""
    path = _history_file(agent_id)
    if not os.path.isfile(path):
        return []
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError as e:
        logger.warning("session_history.read failed for %s: %s",
                       agent_id[:8], e)
    return out


def sum_history_usage(agent_id: str) -> dict[str, int]:
    """Aggregate usage across an agent's entire ended-session history.

    Returns a dict with the four usage keys plus `sessions` (count) and
    `turn_count` (total assistant turns). Zero-init if no history.
    """
    cum: dict[str, int] = {k: 0 for k in _USAGE_KEYS}
    cum["sessions"] = 0
    cum["turn_count"] = 0
    for rec in read_history(agent_id):
        u = rec.get("usage", {}) or {}
        if not isinstance(u, dict):
            continue
        for k in _USAGE_KEYS:
            cum[k] += int(u.get(k, 0) or 0)
        cum["sessions"] += 1
        cum["turn_count"] += int(rec.get("turn_count", 0) or 0)
    return cum


def sum_jsonl_usage(jsonl_path: str) -> dict[str, int]:
    """Sum every assistant entry's `usage` block in a JSONL file.

    Used for the CURRENT session running total — it is NOT yet in the
    history file (we only write on rotation). Per-call cost is one
    sequential read; typical CC session JSONLs are <2MB.
    """
    cum: dict[str, int] = {k: 0 for k in _USAGE_KEYS}
    cum["turn_count"] = 0
    if not jsonl_path or not os.path.isfile(jsonl_path):
        return cum
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if d.get("type") != "assistant":
                    continue
                msg = d.get("message")
                if not isinstance(msg, dict):
                    continue
                u = msg.get("usage")
                if not isinstance(u, dict):
                    continue
                cum["turn_count"] += 1
                for k in _USAGE_KEYS:
                    cum[k] += int(u.get(k, 0) or 0)
    except OSError as e:
        logger.debug("sum_jsonl_usage: read failed for %s: %s", jsonl_path, e)
    return cum
