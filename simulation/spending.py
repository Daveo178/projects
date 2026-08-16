"""Pure helpers for retirement spending trajectories."""

from __future__ import annotations

import math


def apply_late_life_spending_reductions(
    spending: float,
    age: float,
    *,
    step_1_age: float = 75.0,
    step_1_rate: float = 0.0,
    step_2_age: float = 85.0,
    step_2_rate: float = 0.0,
) -> float:
    """Apply up to two inclusive, age-triggered spending reductions.

    ``step_*_rate`` values are decimal fractions (``0.10`` means 10%).
    Each active step is multiplicative, so a 10% reduction followed by a
    20% reduction leaves 72% of the pre-step spending (``0.9 * 0.8``).

    The thresholds are inclusive: a step applies in the simulation year in
    which the reference age reaches the configured age. The pairs are sorted
    by age defensively, so hand-edited or legacy data with the two stages in
    reverse order still produces the expected age-based result. Rates are
    clamped to ``[0, 1]`` so malformed persisted data cannot make spending
    negative. A zero rate is a no-op, preserving existing tapered plans.
    """
    result = float(spending)
    current_age = float(age)

    reductions = []
    for raw_age, raw_rate in (
        (step_1_age, step_1_rate),
        (step_2_age, step_2_rate),
    ):
        try:
            threshold = float(raw_age)
            rate = float(raw_rate)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(threshold) or not math.isfinite(rate):
            continue
        reductions.append((threshold, min(1.0, max(0.0, rate))))

    for threshold, rate in sorted(reductions, key=lambda item: item[0]):
        if current_age >= threshold:
            result *= 1.0 - rate

    return result


__all__ = ["apply_late_life_spending_reductions"]
