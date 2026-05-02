"""Context breakdown — Phase 2.

Computes a 5-component approximation of how an agent's context window is
being spent, plus rule-based optimization suggestions.

Categories (ordered most → least actionable):
  1. MCP tools     — registered MCP servers (most variable, biggest target)
  2. Memory files  — CLAUDE.md / AGENT.md chain
  3. Custom Agents — .claude/agents/*.md frontmatter
  4. System overhead — built-in CC system prompt + tool definitions (~12k constant)
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

from context_usage import DEFAULT_LIMIT, get_context_usage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pricing — USD per 1M tokens. Anthropic published rates (subject to change).
# ---------------------------------------------------------------------------
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7":   {"input": 15.00, "cache_create": 18.75, "cache_read": 1.50, "output": 75.00},
    "claude-opus-4-6":   {"input": 15.00, "cache_create": 18.75, "cache_read": 1.50, "output": 75.00},
    "claude-opus-4-5":   {"input": 15.00, "cache_create": 18.75, "cache_read": 1.50, "output": 75.00},
    "claude-sonnet-4-6": {"input":  3.00, "cache_create":  3.75, "cache_read": 0.30, "output": 15.00},
    "claude-sonnet-4-5": {"input":  3.00, "cache_create":  3.75, "cache_read": 0.30, "output": 15.00},
    "claude-haiku-4-5":  {"input":  1.00, "cache_create":  1.25, "cache_read": 0.10, "output":  5.00},
}
DEFAULT_PRICING = {"input": 3.00, "cache_create": 3.75, "cache_read": 0.30, "output": 15.00}


def _resolve_pricing(model: str | None) -> dict[str, float]:
    if not model:
        return DEFAULT_PRICING
    if model in PRICING:
        return PRICING[model]
    base = model.rsplit("-", 1)[0]
    return PRICING.get(base, DEFAULT_PRICING)


def _compute_cost(usage: dict[str, int], model: str | None) -> float:
    p = _resolve_pricing(model)
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_create"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
        + usage.get("output_tokens", 0) * p["output"]
    ) / 1_000_000


# ---------------------------------------------------------------------------
# Token approximation
# ---------------------------------------------------------------------------
# cl100k_base averages ~3.5 chars/token for English/code, ~1.6 for CJK.
# We use a single ratio because static categories (system files, tool
# definitions) are predominantly ASCII/code. Total error gets absorbed by
# the Messages remainder.
_CHARS_PER_TOKEN = 3.5


def _count_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


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
        toks = _count_tokens(text)
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
        toks = _count_tokens(fm)
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
# Per-server token estimate. Real tool descriptions vary widely — we list
# rough ranges for known servers. Unknown servers get a conservative default.
# Numbers come from observed token costs in CC sessions, not exact lookups.
_MCP_SERVER_ESTIMATES: dict[str, int] = {
    "xylocopa": 6_500,    # ~30 tools (project_*, task_*, session_*, agent_*, system_*)
    "filesystem": 4_500,
    "github": 12_000,
    "playwright": 18_000,
    "puppeteer": 14_000,
    "memory": 1_500,
    "fetch": 1_200,
    "sqlite": 2_500,
    "postgres": 3_000,
    "git": 5_000,
    "slack": 8_000,
    "linear": 6_000,
}
_MCP_DEFAULT_ESTIMATE = 5_000


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
        toks = _MCP_SERVER_ESTIMATES.get(server_name, _MCP_DEFAULT_ESTIMATE)
        breakdown.append({
            "name": server_name,
            "tokens": toks,
            "estimated": True,
        })
        total += toks
    return total, breakdown


# ---------------------------------------------------------------------------
# System overhead
# ---------------------------------------------------------------------------
# CC's base system prompt (~3k tokens) + ~50 built-in tool descriptions
# (~10k tokens). Roughly constant per CLI version; we treat it as a single
# unsplittable bucket since the user can't optimize it.
SYSTEM_OVERHEAD_BASE = 13_000


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------
def _compute_suggestions(base: dict[str, Any], components: list[dict]) -> list[dict]:
    """Rule-based optimization warnings.

    Severity: info | warn | urgent.
    """
    out: list[dict] = []
    total = base.get("total", 0) or 0
    limit = base.get("limit", DEFAULT_LIMIT) or DEFAULT_LIMIT
    pct = (total / limit * 100) if limit else 0

    if pct >= 90:
        out.append({
            "severity": "urgent",
            "text": f"Context at {pct:.0f}% capacity — run /compact or /clear soon to avoid auto-compact disruption.",
        })
    elif pct >= 75:
        out.append({
            "severity": "warn",
            "text": f"Context at {pct:.0f}% capacity — consider /compact when convenient.",
        })

    by_name = {c["name"]: c for c in components}
    mcp = by_name.get("MCP tools")
    if mcp and limit > 0 and mcp["tokens"] / limit >= 0.10:
        heaviest = max(mcp.get("breakdown", []) or [{}], key=lambda x: x.get("tokens", 0))
        if heaviest.get("name"):
            out.append({
                "severity": "warn",
                "text": (
                    f"MCP server '{heaviest['name']}' uses ~{heaviest['tokens'] / limit * 100:.0f}% "
                    f"of context — disable with `@{heaviest['name']} disable` if not needed."
                ),
            })

    memory = by_name.get("Memory files")
    if memory and memory.get("breakdown"):
        for f in memory["breakdown"]:
            if f.get("bytes", 0) > 50_000:
                out.append({
                    "severity": "info",
                    "text": (
                        f"{f['name']} is {f['bytes'] // 1024} KB — "
                        f"review for outdated entries to free ~{f['tokens']:,} tokens."
                    ),
                })

    return out


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
    suggestions = _compute_suggestions(base, components)

    return {
        **base,
        "free": free,
        "free_percent": _pct(free),
        "components": components,
        "suggestions": suggestions,
        "lifetime": _get_lifetime(agent_id, agent.model if agent else None,
                                  project_path, agent.worktree if agent else None,
                                  agent.session_id if agent else None),
    }


# ---------------------------------------------------------------------------
# Lifetime spend across all CC sessions ever owned by this xylo agent
# ---------------------------------------------------------------------------
def _get_lifetime(
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
    cost_usd = _compute_cost(combined, model)
    pricing = _resolve_pricing(model)

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
