"""Char-based token approximation.

Pure function. cl100k_base averages ~3.5 chars/token for English/code; we
use a single ratio because the categories that need a tokenizer (system
files, tool definitions, frontmatter) are predominantly ASCII/code. Any
total error gets absorbed by the Messages remainder bucket downstream.

We deliberately avoid `tiktoken` as a dependency.
"""
from __future__ import annotations

from .constants import CHARS_PER_TOKEN


def count_tokens(text: str | None) -> int:
    """Estimate the token count of `text` using a char/3.5 heuristic.

    Returns 0 for empty/None input. Otherwise returns at least 1.
    """
    if not text:
        return 0
    return max(1, round(len(text) / CHARS_PER_TOKEN))
