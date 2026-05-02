"""Model pricing lookup and cost math.

USD per 1M tokens, Anthropic published rates (subject to change).
"""
from __future__ import annotations


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


def resolve_pricing(model: str | None) -> dict[str, float]:
    """Return per-million-token rates for `model`, falling back to defaults.

    Handles version-suffixed IDs by stripping the trailing `-YYYYMMDD` and
    retrying. Unknown models get DEFAULT_PRICING.
    """
    if not model:
        return DEFAULT_PRICING
    if model in PRICING:
        return PRICING[model]
    base = model.rsplit("-", 1)[0]
    return PRICING.get(base, DEFAULT_PRICING)


def compute_cost(usage: dict[str, int], model: str | None) -> float:
    """Compute USD cost for a single Anthropic `usage` block.

    `usage` is the per-turn dict with keys: input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens. Missing keys are
    treated as 0. Result is total USD (NOT rounded).
    """
    p = resolve_pricing(model)
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_create"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
        + usage.get("output_tokens", 0) * p["output"]
    ) / 1_000_000
