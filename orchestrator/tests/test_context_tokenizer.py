"""Tests for context.tokenizer — char-based token approximation."""
from __future__ import annotations

from context.tokenizer import count_tokens


def test_count_tokens_empty_string_is_zero():
    assert count_tokens("") == 0


def test_count_tokens_none_is_zero():
    assert count_tokens(None) == 0


def test_count_tokens_single_char_is_one():
    """Min return for non-empty input is 1 (max(1, ...))."""
    assert count_tokens("a") == 1


def test_count_tokens_long_string_350_chars():
    # 350 / 3.5 = 100
    assert count_tokens("a" * 350) == 100


def test_count_tokens_short_string_35_chars():
    # 35 / 3.5 = 10
    assert count_tokens("a" * 35) == 10
