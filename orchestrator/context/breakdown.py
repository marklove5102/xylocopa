"""Context breakdown — Phase 2.

Computes a 5-component approximation of how an agent's context window is
being spent, plus rule-based optimization suggestions.

Categories (ordered most → least actionable):
  1. MCP tools     — registered MCP servers (most variable, biggest target)
  2. Memory files  — CLAUDE.md / AGENT.md chain
  3. Custom Agents — .claude/agents/*.md frontmatter
  4. System overhead — built-in CC system prompt + tool definitions (~13k constant)
  5. Messages      — remainder = total - all above (absorbs tokenizer error)

The total token anchor is the JSONL `usage` value (Anthropic-tokenizer exact).
Static categories use a char/3.5 heuristic that approximates cl100k_base
average density. Errors in the heuristic flow into the Messages bucket
(which is the dominant variable category anyway), so the displayed
breakdown always sums to the JSONL total.

Note: We deliberately avoid adding `tiktoken` as a dependency — the
Messages-as-remainder strategy makes the heuristic's accuracy unimportant
for the displayed breakdown.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from .constants import (
    DEFAULT_LIMIT,
    MCP_DEFAULT_ESTIMATE,
    MCP_SERVER_ESTIMATES,
    SYSTEM_OVERHEAD_BASE,
)
from .lifetime import get_lifetime
from .suggestions import compute_suggestions
from .tokenizer import count_tokens
from .usage import get_context_usage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Memory files (CLAUDE.md / AGENT.md chain)
# ---------------------------------------------------------------------------
def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _scan_memory_files(project_path: str) -> tuple[int, list[dict]]:
    """Scan CLAUDE.md/AGENT.md chain.

    Order matches Claude Code's resolution: user-global → project root →
    project AGENT.md. We do NOT walk parent directories (rare and
    expensive); the project CLAUDE.md is the dominant case.
    """
    candidates = [
        ("~/.claude/CLAUDE.md", os.path.expanduser("~/.claude/CLAUDE.md")),
        ("CLAUDE.md", os.path.join(project_path, "CLAUDE.md")),
        ("AGENT.md", os.path.join(project_path, "AGENT.md")),
        (".claude/CLAUDE.md", os.path.join(project_path, ".claude", "CLAUDE.md")),
    ]
    breakdown = []
    total = 0
    for label, path in candidates:
        if not os.path.isfile(path):
            continue
        text = _read_text(path)
        if not text:
            continue
        toks = count_tokens(text)
        breakdown.append({
            "name": label,
            "path": path,
            "tokens": toks,
            "bytes": len(text.encode("utf-8")),
        })
        total += toks
    return total, breakdown


# ---------------------------------------------------------------------------
# Custom Agents (.claude/agents/*.md frontmatter only)
# ---------------------------------------------------------------------------
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _extract_frontmatter(md_text: str) -> str:
    """Return YAML frontmatter (without the --- delimiters), or empty."""
    m = _FRONTMATTER_RE.match(md_text)
    return m.group(1) if m else ""


def _scan_agent_dir(dir_path: str, source: str) -> list[dict]:
    out = []
    if not os.path.isdir(dir_path):
        return out
    try:
        entries = sorted(os.listdir(dir_path))
    except OSError:
        return out
    for name in entries:
        if not name.endswith(".md"):
            continue
        full = os.path.join(dir_path, name)
        text = _read_text(full)
        if not text:
            continue
        fm = _extract_frontmatter(text)
        if not fm:
            continue
        toks = count_tokens(fm)
        out.append({
            "name": name[:-3],
            "source": source,  # "personal" | "project"
            "tokens": toks,
        })
    return out


def _scan_custom_agents(project_path: str) -> tuple[int, list[dict]]:
    breakdown = (
        _scan_agent_dir(os.path.expanduser("~/.claude/agents"), "personal")
        + _scan_agent_dir(os.path.join(project_path, ".claude", "agents"), "project")
    )
    total = sum(a["tokens"] for a in breakdown)
    return total, breakdown


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------
def _scan_mcp_servers(project_path: str) -> tuple[int, list[dict]]:
    """Read .mcp.json and estimate per-server token cost.

    Real values would come from each server's tools/list response, but
    that requires spawning subprocesses. Phase 2.5 can replace these
    estimates with live introspection.
    """
    mcp_json = os.path.join(project_path, ".mcp.json")
    if not os.path.isfile(mcp_json):
        return 0, []
    text = _read_text(mcp_json)
    if not text:
        return 0, []
    try:
        config = json.loads(text)
    except json.JSONDecodeError:
        return 0, []
    servers = config.get("mcpServers", {}) or {}
    breakdown = []
    total = 0
    for server_name in sorted(servers.keys()):
        toks = MCP_SERVER_ESTIMATES.get(server_name, MCP_DEFAULT_ESTIMATE)
        breakdown.append({
            "name": server_name,
            "tokens": toks,
            "estimated": True,
        })
        total += toks
    return total, breakdown


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def get_context_breakdown(agent_id: str) -> dict[str, Any]:
    """Compute the full breakdown for an agent.

    Returns a dict with:
      total, limit, percent, model, captured_at, has_data, session_id  (from Phase 1)
      free        — int, limit - total
      components  — list of {name, tokens, percent, breakdown?, info?}
      suggestions — list of {severity, text}
    """
    from database import SessionLocal
    from models import Agent, Project

    base = get_context_usage(agent_id)
    if not base.get("has_data"):
        return {**base, "free": base.get("limit", DEFAULT_LIMIT), "components": [], "suggestions": []}

    db = SessionLocal()
    try:
        agent = db.get(Agent, agent_id)
        if agent is None:
            return {**base, "free": 0, "components": [], "suggestions": []}
        project = db.query(Project).filter(Project.name == agent.project).first()
        project_path = project.path if project else None
    finally:
        db.close()

    if not project_path:
        return {**base, "free": 0, "components": [], "suggestions": []}

    mcp_total, mcp_breakdown = _scan_mcp_servers(project_path)
    memory_total, memory_breakdown = _scan_memory_files(project_path)
    agents_total, agents_breakdown = _scan_custom_agents(project_path)

    static_sum = mcp_total + memory_total + agents_total + SYSTEM_OVERHEAD_BASE
    messages_total = max(0, base["total"] - static_sum)
    limit = base["limit"]
    free = max(0, limit - base["total"])

    def _pct(toks: int) -> float:
        return round(toks / limit * 100, 1) if limit else 0.0

    components = [
        {
            "name": "Messages",
            "tokens": messages_total,
            "percent": _pct(messages_total),
            "info": "Conversation history — user, assistant, tool calls. Run /compact to summarize.",
        },
        {
            "name": "MCP tools",
            "tokens": mcp_total,
            "percent": _pct(mcp_total),
            "breakdown": mcp_breakdown,
            "info": "Token estimates per server — actual values depend on registered tool descriptions.",
        },
        {
            "name": "Memory files",
            "tokens": memory_total,
            "percent": _pct(memory_total),
            "breakdown": memory_breakdown,
            "info": "CLAUDE.md and AGENT.md files loaded into the system prompt.",
        },
        {
            "name": "Custom Agents",
            "tokens": agents_total,
            "percent": _pct(agents_total),
            "breakdown": agents_breakdown,
            "info": "Frontmatter from .claude/agents/*.md (bodies load on invocation).",
        },
        {
            "name": "System overhead",
            "tokens": SYSTEM_OVERHEAD_BASE,
            "percent": _pct(SYSTEM_OVERHEAD_BASE),
            "info": "Built-in Claude Code system prompt + tool definitions (constant ~13k).",
        },
    ]
    suggestions = compute_suggestions(base, components)

    return {
        **base,
        "free": free,
        "free_percent": _pct(free),
        "components": components,
        "suggestions": suggestions,
        "lifetime": get_lifetime(agent_id, agent.model if agent else None,
                                 project_path, agent.worktree if agent else None,
                                 agent.session_id if agent else None),
    }
