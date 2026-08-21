"""Shared drawdown-strategy options for input pages."""

from __future__ import annotations


DRAW_DOWN_STRATEGIES = (
    "Fixed",
    "Inflation-adjusted",
    "Tapered (down with age)",
    "Spending phases",
    "Safe Withdrawal (4%)",
)


def normalize_drawdown_strategy(value: object) -> str:
    """Return a supported strategy, falling back safely to ``Fixed``."""
    if isinstance(value, str) and value in DRAW_DOWN_STRATEGIES:
        return value
    return "Fixed"


__all__ = ["DRAW_DOWN_STRATEGIES", "normalize_drawdown_strategy"]
