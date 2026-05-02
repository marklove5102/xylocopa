"""Tests for context.pricing — model rate lookup and cost math."""
from __future__ import annotations

from context.pricing import (
    DEFAULT_PRICING,
    PRICING,
    compute_cost,
    resolve_pricing,
)


# ---------------------------------------------------------------------------
# resolve_pricing
# ---------------------------------------------------------------------------
def test_resolve_pricing_opus_47_exact():
    p = resolve_pricing("claude-opus-4-7")
    assert p == PRICING["claude-opus-4-7"]
    # Opus 4.5+ rates per Anthropic (verified 2026-05-02). Opus 4 / 4.1
    # legacy were $15/$75; current generation is $5/$25.
    assert p["input"] == 5.00
    assert p["output"] == 25.00
    assert p["cache_create_5m"] == 6.25
    assert p["cache_create_1h"] == 10.00
    assert p["cache_read"] == 0.50


def test_resolve_pricing_opus_47_with_date_suffix():
    """Version-suffixed IDs strip the trailing -YYYYMMDD."""
    p = resolve_pricing("claude-opus-4-7-20251015")
    assert p == PRICING["claude-opus-4-7"]


def test_resolve_pricing_none_returns_default():
    assert resolve_pricing(None) is DEFAULT_PRICING


def test_resolve_pricing_unknown_returns_default():
    assert resolve_pricing("nonexistent-model") is DEFAULT_PRICING


def test_resolve_pricing_sonnet_rates():
    p = resolve_pricing("claude-sonnet-4-6")
    assert p["input"] == 3.00
    assert p["cache_read"] == 0.30
    assert p["output"] == 15.00


def test_resolve_pricing_haiku_rates():
    p = resolve_pricing("claude-haiku-4-5")
    assert p["input"] == 1.00
    assert p["cache_read"] == 0.10
    assert p["output"] == 5.00


def test_resolve_pricing_distinct_tiers():
    """Sonnet, Opus, Haiku rates must differ correctly."""
    opus = resolve_pricing("claude-opus-4-7")
    sonnet = resolve_pricing("claude-sonnet-4-6")
    haiku = resolve_pricing("claude-haiku-4-5")
    assert opus["input"] > sonnet["input"] > haiku["input"]
    assert opus["output"] > sonnet["output"] > haiku["output"]


# ---------------------------------------------------------------------------
# compute_cost
# ---------------------------------------------------------------------------
def test_compute_cost_opus_full_usage():
    """Opus 4.7: input × 5 + cache_create × 6.25 + cache_read × 0.5 + output × 25, / 1M.

    Legacy rollup `cache_creation_input_tokens` (no 5m/1h split) is
    treated as all-5m for back-compat — the cheaper rate.
    """
    usage = {
        "input_tokens": 1_000_000,
        "cache_creation_input_tokens": 1_000_000,
        "cache_read_input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
    }
    cost = compute_cost(usage, "claude-opus-4-7")
    expected = 5.00 + 6.25 + 0.50 + 25.00
    assert abs(cost - expected) < 1e-9


def test_compute_cost_opus_split_cache():
    """When 5m/1h split is provided, each bucket gets its own rate."""
    usage = {
        "input_tokens": 1_000_000,
        "cache_creation_5m_tokens": 1_000_000,   # 1M × $6.25
        "cache_creation_1h_tokens": 1_000_000,   # 1M × $10.00
        "cache_read_input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
    }
    cost = compute_cost(usage, "claude-opus-4-7")
    expected = 5.00 + 6.25 + 10.00 + 0.50 + 25.00
    assert abs(cost - expected) < 1e-9


def test_compute_cost_empty_usage_is_zero():
    assert compute_cost({}, "claude-opus-4-7") == 0


def test_compute_cost_missing_keys_treated_as_zero():
    """Only input present — others default to 0. Opus 4.7 input is $5/M."""
    cost = compute_cost({"input_tokens": 1_000_000}, "claude-opus-4-7")
    assert cost == 5.00


def test_compute_cost_unknown_model_uses_default_pricing():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    expected = (1_000_000 * 3.00 + 1_000_000 * 15.00) / 1_000_000
    cost = compute_cost(usage, "nonexistent-foo")
    assert abs(cost - expected) < 1e-9


def test_compute_cost_none_model_uses_default_pricing():
    cost = compute_cost({"input_tokens": 1_000_000}, None)
    assert cost == 3.00


def test_compute_cost_haiku_is_cheaper_than_opus():
    usage = {"input_tokens": 100_000, "output_tokens": 50_000}
    opus_cost = compute_cost(usage, "claude-opus-4-7")
    haiku_cost = compute_cost(usage, "claude-haiku-4-5")
    assert haiku_cost < opus_cost


def test_compute_cost_partial_usage():
    """Only cache_read populated. Opus 4.7 cache_read is $0.50/M."""
    cost = compute_cost(
        {"cache_read_input_tokens": 2_000_000}, "claude-opus-4-7"
    )
    # 2M × $0.50 / 1M = $1.00
    assert abs(cost - 1.00) < 1e-9
