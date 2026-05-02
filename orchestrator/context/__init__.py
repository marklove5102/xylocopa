"""Context window analysis package.

Public API:
    get_context_usage(agent_id)      — headline numbers (Phase 1)
    get_context_breakdown(agent_id)  — full 5-component breakdown (Phase 2)
"""
from .breakdown import get_context_breakdown
from .usage import get_context_usage

__all__ = ["get_context_usage", "get_context_breakdown"]
