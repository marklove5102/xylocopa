"""Context usage computation — Phase 1.

Reads the latest assistant entry's `message.usage` from a session JSONL and
returns the total token footprint (input + cache_creation + cache_read) along
with the per-model context window cap.

Phase 1 returns only headline numbers (total/limit/percent/model/captured_at).
The 6-component breakdown (System Prompt / System tools / MCP tools /
Memory files / Custom Agents / Messages) lives in a separate module to be
added in Phase 2.

Why JSONL `usage` and not `count_tokens` API: the JSONL value is the exact
number Anthropic's tokenizer computed for the prior request — already
captured server-side, free, instant. count_tokens would be a redundant
network round-trip.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# Per-model context window caps. Defaults to 200K for any model not listed.
# Opus 4.7 has a 1M native window — see the CHANGELOG entry "Fixed Opus 4.7
# sessions showing inflated /context percentages".
MODEL_LIMITS: dict[str, int] = {
    "claude-opus-4-7": 1_000_000,
    "claude-opus-4-7-20251015": 1_000_000,
    "claude-opus-4-6": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-haiku-4-5-20251001": 1_000_000,
}
DEFAULT_LIMIT = 200_000


def _resolve_limit(model: str | None) -> int:
    """Look up the context window cap for a model id.

    Handles version-suffixed IDs by stripping the `-YYYYMMDD` tail and
    retrying. Falls back to DEFAULT_LIMIT.
    """
    if not model:
        return DEFAULT_LIMIT
    if model in MODEL_LIMITS:
        return MODEL_LIMITS[model]
    # Strip date suffix, e.g. claude-opus-4-7-20260115 -> claude-opus-4-7
    base = model.rsplit("-", 1)[0]
    if base in MODEL_LIMITS:
        return MODEL_LIMITS[base]
    return DEFAULT_LIMIT


def _tail_lines(path: str, n: int = 200) -> list[str]:
    """Read the last `n` lines of a file efficiently from the end.

    Used instead of full read because session JSONLs can grow to many MB
    and we only need the tail. Reads in 64KB chunks backwards.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size == 0:
        return []

    chunk = 64 * 1024
    lines: list[bytes] = []
    pos = size
    leftover = b""
    try:
        with open(path, "rb") as f:
            while pos > 0 and len(lines) <= n:
                read_size = min(chunk, pos)
                pos -= read_size
                f.seek(pos)
                buf = f.read(read_size) + leftover
                parts = buf.split(b"\n")
                # First fragment may be incomplete; save for next iteration
                leftover = parts[0]
                lines = parts[1:] + lines
            if pos == 0 and leftover:
                lines = [leftover] + lines
    except OSError as e:
        logger.debug("_tail_lines: read failed for %s: %s", path, e)
        return []

    decoded = []
    for ln in lines[-n:]:
        try:
            decoded.append(ln.decode("utf-8", errors="replace"))
        except Exception:
            continue
    return decoded


def _last_assistant_usage(jsonl_path: str) -> dict[str, Any] | None:
    """Find the most recent assistant entry with a `message.usage` block.

    Returns dict with keys: usage, model, timestamp. None if not found.
    Iterates from the end, returns first match.
    """
    if not jsonl_path or not os.path.isfile(jsonl_path):
        return None
    lines = _tail_lines(jsonl_path, n=200)
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if d.get("type") != "assistant":
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        return {
            "usage": usage,
            "model": msg.get("model"),
            "timestamp": d.get("timestamp"),
        }
    return None


def get_context_usage(agent_id: str) -> dict[str, Any]:
    """Compute headline context usage for an agent.

    Returns a dict with:
      total       — int, sum of input + cache_creation + cache_read tokens
      limit       — int, per-model context window cap
      percent     — float (1 decimal), 0-100+
      model       — str | None, model id from latest assistant entry
      captured_at — str | None, ISO timestamp from latest assistant entry
      session_id  — str | None
      has_data    — bool, False if no assistant entry exists yet

    Empty result on missing agent / no JSONL / no assistant turn yet.
    """
    from agent_dispatcher import _resolve_session_jsonl
    from database import SessionLocal
    from models import Agent, Project

    empty = {
        "total": 0,
        "limit": DEFAULT_LIMIT,
        "percent": 0.0,
        "model": None,
        "captured_at": None,
        "session_id": None,
        "has_data": False,
    }

    db = SessionLocal()
    try:
        agent = db.get(Agent, agent_id)
        if agent is None or not agent.session_id:
            return empty
        project = db.query(Project).filter(Project.name == agent.project).first()
        if project is None:
            return empty
        jsonl_path = _resolve_session_jsonl(
            agent.session_id, project.path, agent.worktree
        )
    finally:
        db.close()

    last = _last_assistant_usage(jsonl_path)
    if last is None:
        return {**empty, "session_id": agent.session_id}

    u = last["usage"]
    total = (
        int(u.get("input_tokens", 0) or 0)
        + int(u.get("cache_creation_input_tokens", 0) or 0)
        + int(u.get("cache_read_input_tokens", 0) or 0)
    )
    model = last["model"]
    limit = _resolve_limit(model)
    percent = round(total / limit * 100, 1) if limit > 0 else 0.0

    return {
        "total": total,
        "limit": limit,
        "percent": percent,
        "model": model,
        "captured_at": last["timestamp"],
        "session_id": agent.session_id,
        "has_data": True,
    }
