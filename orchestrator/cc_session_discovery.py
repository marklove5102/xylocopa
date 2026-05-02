"""Read-only discovery of Claude Code session JSONL files.

Pure functions — no DB writes — so the discovery side stays unit-testable
without spinning up a SQLAlchemy session.

Each function operates on filesystem state under
``~/.claude/projects/<encoded_project_path>/`` (and worktree subdirs).
A "session JSONL" is a file named ``<session_id>.jsonl`` whose entries
are line-delimited JSON records with at minimum ``uuid`` and
``timestamp`` fields. The first entry of a sub-session has
``parentUuid`` pointing back at a tool_use entry in the parent session's
JSONL — that is the link we follow to reconstruct
parent→sub-session relationships.

Reuses ``session_history.sum_jsonl_usage`` for token aggregation and
``session_cache.session_source_dir`` for path encoding so the discovery
logic stays consistent with the rest of the orchestrator.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from session_cache import session_source_dir
from session_history import sum_jsonl_usage

logger = logging.getLogger(__name__)


def parse_jsonl_metadata(jsonl_path: str) -> dict | None:
    """Extract session-level metadata from a JSONL file on disk.

    Returns a dict with keys:
        session_id          - filename stem; or first entry's ``sessionId``
        parent_jsonl_uuid   - first entry's ``parentUuid`` (None for top-level)
        started_at          - ISO timestamp of the first entry, or None
        ended_at            - ISO timestamp of the last entry, or None
        model               - first assistant entry's ``message.model``, or None
        total_input_tokens, total_output_tokens,
        total_cache_creation_tokens, total_cache_read_tokens
                            - via ``sum_jsonl_usage``
        turn_count          - assistant turns counted by ``sum_jsonl_usage``

    Returns ``None`` if the file is missing or unreadable, or if it has
    zero parseable entries (empty / fully corrupt).
    """
    if not jsonl_path or not os.path.isfile(jsonl_path):
        return None

    first_entry: dict | None = None
    last_timestamp: str | None = None
    model: str | None = None

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(entry, dict):
                    continue
                if first_entry is None:
                    first_entry = entry
                ts = entry.get("timestamp")
                if isinstance(ts, str) and ts:
                    last_timestamp = ts
                if model is None and entry.get("type") == "assistant":
                    msg = entry.get("message")
                    if isinstance(msg, dict):
                        m = msg.get("model")
                        if isinstance(m, str) and m:
                            model = m
    except OSError as e:
        logger.debug("parse_jsonl_metadata: read failed for %s: %s", jsonl_path, e)
        return None

    if first_entry is None:
        # Empty or all-malformed file.
        return None

    # Detect subagent JSONLs by path: <parent_sid>/subagents/agent-<aid>.jsonl
    # CC writes the PARENT's session_id into entries' `sessionId` field for
    # these — so we can't use that. The unique key is the entry-level
    # `agentId` (matches xylocopa subagent row's `claude_agent_id`).
    fname = os.path.basename(jsonl_path)
    parent_dir = os.path.basename(os.path.dirname(jsonl_path))
    is_subagent = (parent_dir == "subagents" and fname.startswith("agent-")
                   and fname.endswith(".jsonl"))

    inferred_parent_session_id: str | None = None
    inferred_claude_agent_id: str | None = None

    if is_subagent:
        # session_id := claude_agent_id (parsed from filename)
        inferred_claude_agent_id = fname[len("agent-"):-len(".jsonl")]
        session_id = inferred_claude_agent_id
        # parent CC session = the directory ABOVE `subagents/`
        grandparent_dir = os.path.dirname(os.path.dirname(jsonl_path))
        inferred_parent_session_id = os.path.basename(grandparent_dir)
    elif fname.endswith(".jsonl"):
        session_id = fname[:-6]
    else:
        sid = first_entry.get("sessionId")
        if not isinstance(sid, str) or not sid:
            return None
        session_id = sid

    started_at = first_entry.get("timestamp") if isinstance(
        first_entry.get("timestamp"), str
    ) else None
    parent_jsonl_uuid = first_entry.get("parentUuid")
    if not isinstance(parent_jsonl_uuid, str) or not parent_jsonl_uuid:
        parent_jsonl_uuid = None

    usage = sum_jsonl_usage(jsonl_path)

    return {
        "session_id": session_id,
        "parent_jsonl_uuid": parent_jsonl_uuid,
        "started_at": started_at,
        "ended_at": last_timestamp,
        "model": model,
        "total_input_tokens": int(usage.get("input_tokens", 0) or 0),
        "total_output_tokens": int(usage.get("output_tokens", 0) or 0),
        "total_cache_creation_tokens": int(
            usage.get("cache_creation_input_tokens", 0) or 0
        ),
        "total_cache_read_tokens": int(
            usage.get("cache_read_input_tokens", 0) or 0
        ),
        "turn_count": int(usage.get("turn_count", 0) or 0),
        "jsonl_path": jsonl_path,
        # Convenience for callers that want to know which project_dir the
        # JSONL came from without re-deriving it. Callers that don't need it
        # ignore it.
        "session_dir": os.path.dirname(jsonl_path),
        # Subagent-specific fields (None for top-level sessions). When
        # `is_subagent_session` is True, callers should use
        # `parent_session_id` rather than parent_jsonl_uuid for linkage —
        # the subdir layout is authoritative.
        "is_subagent_session": is_subagent,
        "claude_agent_id": inferred_claude_agent_id,
        "parent_session_id": inferred_parent_session_id,
    }


def _list_jsonl_in_dir(session_dir: str) -> list[str]:
    """Return absolute paths of every ``*.jsonl`` directly inside *session_dir*."""
    if not session_dir or not os.path.isdir(session_dir):
        return []
    out: list[str] = []
    try:
        for fname in os.listdir(session_dir):
            if fname.endswith(".jsonl"):
                full = os.path.join(session_dir, fname)
                if os.path.isfile(full):
                    out.append(full)
    except OSError as e:
        logger.debug("_list_jsonl_in_dir: scan failed for %s: %s", session_dir, e)
    return out


def _list_subagent_jsonls(session_dir: str) -> list[str]:
    """Walk ``<session_dir>/<top_session_id>/subagents/agent-*.jsonl``.

    For each top-level session JSONL in *session_dir*, CC may write
    Agent-tool subagent JSONLs into a sibling subdirectory named after
    the parent's session_id, e.g.::

        <session_dir>/4fe864e7-.../subagents/agent-aa0024a76b421ee61.jsonl

    Returns the list of absolute paths to such subagent JSONLs.
    """
    if not session_dir or not os.path.isdir(session_dir):
        return []
    out: list[str] = []
    try:
        for entry in os.listdir(session_dir):
            sub_root = os.path.join(session_dir, entry, "subagents")
            if not os.path.isdir(sub_root):
                continue
            try:
                for fname in os.listdir(sub_root):
                    if fname.startswith("agent-") and fname.endswith(".jsonl"):
                        full = os.path.join(sub_root, fname)
                        if os.path.isfile(full):
                            out.append(full)
            except OSError as exc:
                logger.debug("_list_subagent_jsonls: scan %s failed: %s",
                             sub_root, exc)
    except OSError as e:
        logger.debug("_list_subagent_jsonls: scan failed for %s: %s",
                     session_dir, e)
    return out


def discover_project_sessions(
    project_path: str,
    worktree: str | None = None,
) -> list[dict]:
    """List every JSONL belonging to *project_path* (and worktree, if given),
    parse metadata for each.

    Looks under the project's encoded session_dir AND under any worktree
    session_dir (subdirs of ``<project_path>/.claude/worktrees/``). When a
    specific *worktree* is given, only that worktree's session_dir is
    included alongside the project root. When *worktree* is ``None`` we
    enumerate ALL worktree session dirs — useful for a full sweep.

    Returns a list of metadata dicts (same shape as
    :func:`parse_jsonl_metadata`). Files that fail to parse are silently
    skipped.
    """
    if not project_path:
        return []
    real_project = os.path.realpath(project_path)

    dirs_to_scan: list[str] = [session_source_dir(real_project)]

    wt_base = os.path.join(real_project, ".claude", "worktrees")
    if worktree:
        wt_path = os.path.join(wt_base, worktree)
        if os.path.isdir(wt_path):
            dirs_to_scan.append(session_source_dir(wt_path))
    elif os.path.isdir(wt_base):
        try:
            for name in os.listdir(wt_base):
                wt_path = os.path.join(wt_base, name)
                if os.path.isdir(wt_path):
                    dirs_to_scan.append(session_source_dir(wt_path))
        except OSError as e:
            logger.debug("discover_project_sessions: wt scan failed: %s", e)

    seen: set[str] = set()
    out: list[dict] = []
    for sdir in dirs_to_scan:
        if not sdir or sdir in seen:
            continue
        seen.add(sdir)
        for path in _list_jsonl_in_dir(sdir):
            md = parse_jsonl_metadata(path)
            if md is None:
                continue
            out.append(md)
        # Also walk per-session subagent dirs (CC writes them at
        # <session_dir>/<top_sid>/subagents/agent-*.jsonl).
        for path in _list_subagent_jsonls(sdir):
            md = parse_jsonl_metadata(path)
            if md is None:
                continue
            out.append(md)
    return out


def find_owner_for_top_session(session_id: str, session_dir: str) -> str | None:
    """Read the ``<session_dir>/<session_id>.owner`` sidecar.

    Returns the owning xylo agent_id or ``None`` if the sidecar is missing
    or malformed. Mirrors :func:`agent_dispatcher._read_session_owner` but
    kept self-contained to avoid pulling that module's heavy import graph
    into the discovery code path.
    """
    if not session_id or not session_dir:
        return None
    path = os.path.join(session_dir, f"{session_id}.owner")
    try:
        with open(path) as f:
            raw = f.read().strip()
    except (OSError, FileNotFoundError):
        return None
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        agent_id = data.get("agent_id")
        if isinstance(agent_id, str) and agent_id:
            return agent_id
        return None
    # Legacy plain-text format: bare agent_id on the first line
    return raw


def link_sub_to_parent(
    metadata: dict,
    all_metadata: list[dict],
) -> str | None:
    """Locate the parent session_id for a sub-session.

    Given *metadata* (one entry from :func:`discover_project_sessions`) with
    a non-null ``parent_jsonl_uuid``, scan each candidate JSONL in
    *all_metadata* (skipping *metadata* itself) line-by-line for an entry
    whose own ``uuid`` field matches. The first match wins.

    Returns the parent's ``session_id`` or ``None`` if no match is found.
    Returns ``None`` immediately if *metadata* is itself a top-level
    session (``parent_jsonl_uuid is None``).

    Worst case is O(N×M) — N sessions × M lines each — but typical CC
    projects have only a handful of sessions per scan and this only runs
    on the periodic reconcile sweep, not in the hot path.
    """
    target = metadata.get("parent_jsonl_uuid")
    if not target:
        return None

    self_sid = metadata.get("session_id")
    for cand in all_metadata:
        cand_sid = cand.get("session_id")
        if not cand_sid or cand_sid == self_sid:
            continue
        cand_path = cand.get("jsonl_path")
        if not cand_path or not os.path.isfile(cand_path):
            continue
        try:
            with open(cand_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Cheap substring guard before parsing JSON. ``uuid``
                    # values are 36-char UUIDs so collisions with random
                    # strings are vanishingly rare; if the literal isn't in
                    # the line, the parsed entry can't possibly contain it.
                    if target not in line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("uuid") == target:
                        return cand_sid
        except OSError as e:
            logger.debug("link_sub_to_parent: read failed for %s: %s",
                         cand_path, e)
            continue
    return None


__all__ = [
    "parse_jsonl_metadata",
    "discover_project_sessions",
    "find_owner_for_top_session",
    "link_sub_to_parent",
]
