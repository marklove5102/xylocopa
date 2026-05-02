"""Tests for context.suggestions — rule-based optimization warnings."""
from __future__ import annotations

from context.suggestions import compute_suggestions


def _base(total: int, limit: int = 200_000) -> dict:
    return {"total": total, "limit": limit}


def _component(
    name: str,
    tokens: int,
    *,
    breakdown: list[dict] | None = None,
) -> dict:
    c: dict = {"name": name, "tokens": tokens, "percent": 0}
    if breakdown is not None:
        c["breakdown"] = breakdown
    return c


def test_92_percent_total_fires_urgent():
    out = compute_suggestions(_base(184_000), [])
    assert any(s["severity"] == "urgent" for s in out)


def test_80_percent_total_fires_warn_not_urgent():
    """80% is between 75 and 90 — warn, not urgent."""
    out = compute_suggestions(_base(160_000), [])
    severities = [s["severity"] for s in out]
    assert "warn" in severities
    assert "urgent" not in severities


def test_50_percent_total_no_capacity_warning():
    out = compute_suggestions(_base(100_000), [])
    assert all(
        "capacity" not in s["text"].lower() for s in out
    )


def test_mcp_server_above_10_percent_fires_warn():
    """Heaviest MCP server in breakdown gets called out by name."""
    components = [
        _component(
            "MCP tools",
            25_000,
            breakdown=[
                {"name": "playwright", "tokens": 20_000},
                {"name": "fetch", "tokens": 5_000},
            ],
        ),
    ]
    out = compute_suggestions(_base(50_000), components)
    mcp_msgs = [s for s in out if "MCP server" in s["text"]]
    assert len(mcp_msgs) == 1
    assert "playwright" in mcp_msgs[0]["text"]
    assert mcp_msgs[0]["severity"] == "warn"


def test_memory_file_above_50kb_fires_info():
    """A memory file >50KB earns a single info suggestion."""
    components = [
        _component(
            "Memory files",
            20_000,
            breakdown=[
                {"name": "CLAUDE.md", "bytes": 80_000, "tokens": 22_857},
            ],
        ),
    ]
    out = compute_suggestions(_base(40_000), components)
    info_msgs = [s for s in out if s["severity"] == "info"]
    assert len(info_msgs) == 1
    assert "CLAUDE.md" in info_msgs[0]["text"]


def test_no_data_no_suggestions():
    """0% total + no components → no suggestions."""
    out = compute_suggestions(_base(0), [])
    assert out == []


def test_multiple_thresholds_fire_simultaneously():
    """Urgent + MCP warn + memory info — all three present."""
    components = [
        _component(
            "MCP tools",
            30_000,
            breakdown=[{"name": "playwright", "tokens": 30_000}],
        ),
        _component(
            "Memory files",
            22_000,
            breakdown=[{"name": "CLAUDE.md", "bytes": 80_000, "tokens": 22_000}],
        ),
    ]
    out = compute_suggestions(_base(190_000), components)
    severities = {s["severity"] for s in out}
    assert "urgent" in severities
    assert "warn" in severities
    assert "info" in severities


def test_custom_agents_zero_tokens_never_warns():
    """Custom Agents component is not gated by suggestions; with 0 tokens, no suggestion fires."""
    components = [_component("Custom Agents", 0, breakdown=[])]
    out = compute_suggestions(_base(50_000), components)
    assert all("Custom Agents" not in s["text"] for s in out)
