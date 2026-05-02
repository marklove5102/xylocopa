"""Rule-based optimization warnings for an agent's context.

Pure function that takes the headline `base` dict from `usage.get_context_usage`
and the computed `components` list and returns a list of severity-tagged
suggestions. Severity: info | warn | urgent.
"""
from __future__ import annotations

from typing import Any

from .constants import DEFAULT_LIMIT


def compute_suggestions(base: dict[str, Any], components: list[dict]) -> list[dict]:
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
