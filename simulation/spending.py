"""Pure helpers for retirement spending trajectories."""

from __future__ import annotations

import math


def normalize_spending_phases(
    phases,
    *,
    fallback_spending: float = 0.0,
    fallback_end_age: float = 95.0,
) -> list[dict[str, float]]:
    """Return a safe, ordered list of explicit age-based spending phases.

    A phase is stored as ``{"annual_spending": £, "until_age": age}``.
    Values are deliberately absolute amounts rather than percentage changes,
    so the resulting plan is easy to explain and round-trips cleanly through
    JSON. A zero amount represents an unused optional phase; malformed or
    empty data falls back to one constant phase.
    """
    normalized = []
    if isinstance(phases, (list, tuple)):
        for phase in phases:
            if not isinstance(phase, dict):
                continue
            try:
                amount = max(0.0, float(phase.get("annual_spending", 0.0)))
                until_age = float(phase.get("until_age"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(amount) or not math.isfinite(until_age):
                continue
            normalized.append({
                "annual_spending": amount,
                "until_age": until_age,
            })

    if not normalized:
        try:
            amount = max(0.0, float(fallback_spending))
            end_age = float(fallback_end_age)
        except (TypeError, ValueError):
            amount, end_age = 0.0, 95.0
        return [{"annual_spending": amount, "until_age": end_age}]

    # Persisted plans are user-authored in order, but sorting protects the
    # simulation from hand-edited JSON with thresholds in the wrong order.
    normalized.sort(key=lambda phase: phase["until_age"])

    # A zero amount is how the Quick Estimate UI represents an unused
    # optional phase. Remove those entries so one- and two-phase plans do
    # not accidentally become a later £0 spending phase. If every amount is
    # zero, retain the final threshold as one valid zero-spend phase.
    active = [phase for phase in normalized if phase["annual_spending"] > 0]
    return active if active else [normalized[-1]]


def spending_for_age(
    age: float,
    phases,
    *,
    fallback_spending: float = 0.0,
) -> float:
    """Return the explicit phase amount for ``age``.

    ``until_age`` is inclusive: a phase entered as "£40,000 until age 70"
    applies through age 70, and the next phase starts after that. Once the
    final threshold is passed, the final phase continues indefinitely.
    """
    normalized = normalize_spending_phases(
        phases,
        fallback_spending=fallback_spending,
        fallback_end_age=age,
    )
    current_age = float(age)
    for phase in normalized:
        if current_age <= phase["until_age"]:
            return phase["annual_spending"]
    return normalized[-1]["annual_spending"]


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


__all__ = [
    "apply_late_life_spending_reductions",
    "normalize_spending_phases",
    "spending_for_age",
]
