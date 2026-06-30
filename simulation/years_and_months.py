"""
Shared Years+Months helpers.

Used by `pages/3_Assets.py` (mortgage term form) and `pages/2_Pensions.py`
(retirement-age form) to keep the math and English pluralisation in one
place. Each page passes its own action verb ("ends", "retires") so the
caption reads naturally:

    _split_years_into_years_and_months(9.5)
        -> (9, 6)
    _format_years_months_caption(verb="ends", noun="Mortgage",
                                 years=9, months=6)
        -> "Mortgage ends in 9 years and 6 months."

The mathematical helper is intentionally verbatim-equal to the version
that previously lived inside `pages/3_Assets.py` (same `max(0.0, ...)`
clamp, same `int()` truncation, same `round(*12)` for the months
component, same `months == 12` promotion corner case). Pulling it out
here is purely a DRY refactor — no behavioural change.
"""

from typing import Tuple


def _split_years_into_years_and_months(years_float: float) -> Tuple[int, int]:
    """Decompose a (possibly-fractional) `years_float` into whole years +
    leftover months in [0, 11]. Used by the Mortgage and Retirement-age
    forms to pre-fill the two-field UI from data that may have been
    saved with a single float (current scheme) or an integer (legacy
    scheme — older plans still round-trip cleanly because integer 10
    -> (10, 0)).

    Months are rounded to the nearest whole month; the `months == 12`
    promotion corner case (e.g. 8.99999 due to FP rounding) bumps a
    full extra year so the form never displays a disallowed 12-month
    value.

    Defensive `max(0.0, years_float)` clamp at the top: the forms'
    `min_value=0` already prevents negatives, but a future caller could
    pass a value from a different path. Silently mapping a negative
    input to (0, 0) is safer than showing a misleading "−2 years and
    −3 months" caption.

    >>> _split_years_into_years_and_months(9.5)
    (9, 6)
    >>> _split_years_into_years_and_months(10)
    (10, 0)
    >>> _split_years_into_years_and_months(9.99999)  # FP round-up edge case
    (10, 0)
    """
    years_float = max(0.0, float(years_float))
    whole_years = int(years_float)
    months = round((years_float - whole_years) * 12)
    if months == 12:
        whole_years += 1
        months = 0
    return whole_years, months


def _format_years_months_caption(
    verb: str,
    noun: str,
    years: int,
    months: int,
    empty_message: str = "",
) -> str:
    """Friendly English caption for both forms.

    Reads naturally as e.g. `"Mortgage ends in 9 years and 6 months."` or
    `"Retires in 60 years and 6 months."`, with sensible singular
    pluralisation on the noun + unit ("1 year" vs "2 years", "1 month"
    vs "2 months"). When both years and months are zero, falls back to
    a caller-supplied `empty_message` (e.g. `"Mortgage ends immediately
    (no remaining term)."` or `"Already retired today (no remaining
    working period)."`) so the message always references the right
    domain.
    """
    if years == 0 and months == 0:
        return empty_message
    # Conditional subject prefix so the noun-less retirement form reads
    # "Retires in 60 years..." without a leading-space cosmetic
    # (`{noun} {verb}` would render as a leading " retires" when
    # noun="" — visible in copy-paste and unfriendly to text-search).
    subject = f"{noun} " if noun else ""
    if years == 0:
        return f"{subject}{verb} in {months} month{'s' if months != 1 else ''}."
    if months == 0:
        return f"{subject}{verb} in {years} year{'s' if years != 1 else ''}."
    return (
        f"{subject}{verb} in {years} year{'s' if years != 1 else ''} and "
        f"{months} month{'s' if months != 1 else ''}."
    )
