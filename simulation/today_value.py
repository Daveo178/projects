"""Helpers for the "Show in today's value" engine mode.

`show_in_todays_value` is an opt-in household flag (default False) that
re-projects the simulation in TODAY's purchasing power. The engine reads
the flag in `simulation/engine.py::run_simulation` and resolves every
nominal growth rate through these helpers before applying it.

Convention (locked down by `tests/test_todays_value.py`):

  - DB pension, State Pension   → growth_rate = 0 (flat at year-0 base).
  - Property asset               → growth_rate = 0 (capital appreciation
                                          doesn't apply in today's view).
  - All other assets             → effective rate = nominal - inflation
                                          (simple subtraction, matching the
                                          user's "7% nominal at 2.5%
                                          inflation = 4.5% real" mental
                                          model).
  - DC pot growth                → same simple-subtraction rule.
  - Wage curve (earned income)   → same simple-subtraction rule.
  - Mortgage interest            → UNCHANGED. Mortgages have no
                                          inflation-linked growth in the
                                          model — the quoted `rate` keeps
                                          applying in both modes.
  - Spending (Inflation-adjusted
    / Tapered strategies)        → base flat, no `(1+inf)**year` uplift.

When the flag is OFF, every helper returns the user's nominal rate
unchanged, so back-compat with existing saved JSONs is byte-exact.
"""

from __future__ import annotations

from dataclasses import dataclass

# Default inflation rate when the household dataclass field is missing.
# Mirrors `Household.inflation_rate`'s dataclass default and is used as a
# defensive fallback for legacy saved-JSON plans.
DEFAULT_INFLATION_RATE: float = 0.025


@dataclass(frozen=True)
class TodayValueSettings:
    """Resolved rate-transformation settings for one `run_simulation` call.

    Pre-computed once per run (top of `run_simulation`) so the year loop
    reads a small immutable struct instead of re-evaluating dataclass
    lookups + boolean checks per year × per asset. The shape is small
    enough to fit easily in cache; the value is essentially a frozen
    tuple of `(show_today, inflation, person_overrides, asset_overrides)`.
    """

    enabled: bool
    inflation_rate: float


def resolve_today_value_settings(household) -> TodayValueSettings:
    """Read the household dataclass defensively and return resolved settings.

    Tolerates a legacy `Household(...)` instance without the
    `show_in_todays_value` / `inflation_rate` fields (older saved JSON
    plans) — both fields are `getattr`-read with sensible defaults so
    `run_simulation` doesn't raise on a missing-attribute fallback.

    Parameters
    ----------
    household : Household
        The household dataclass instance passed to `run_simulation`.

    Returns
    -------
    TodayValueSettings
        Immutable view of the resolved settings. `enabled=False` is the
        default for all legacy plans.
    """
    enabled = bool(getattr(household, "show_in_todays_value", False))
    inflation = float(
        getattr(household, "inflation_rate", DEFAULT_INFLATION_RATE)
    )
    return TodayValueSettings(enabled=enabled, inflation_rate=inflation)


def effective_db_growth(settings: TodayValueSettings, nominal_rate: float) -> float:
    """DB pension growth rate used by the engine.

    OFF → returns `nominal_rate` unchanged (legacy behaviour).
    ON  → returns 0.0 — DB pension payouts stay flat at the year-0
           base £ value from `draw_age` onwards (matches user intent:
           "the increase in DB index won't be applied to account for
           inflation"). Locked down by
           `tests/test_todays_value.py::test_zeros_db_growth`.
    """
    if settings.enabled:
        return 0.0
    return float(nominal_rate)


def effective_state_pension_growth(
    settings: TodayValueSettings, nominal_rate: float
) -> float:
    """State Pension growth rate used by the engine.

    OFF → `nominal_rate`. ON → 0.0 (State Pension stays flat at
    `FULL_STATE_PENSION` from `state_pension_age` onwards). Matches
    user intent ("the state pension won't be increased by inflation").
    """
    if settings.enabled:
        return 0.0
    return float(nominal_rate)


def effective_dc_growth(settings: TodayValueSettings, nominal_rate: float) -> float:
    """DC pot growth rate used by the engine.

    OFF → `nominal_rate`. ON → `nominal_rate - inflation_rate` via
    simple subtraction. Matches user mental model "7% nominal at
    2.5% inflation = 4.5% real". Simple subtraction (not Fischer's
    equation) is intentional — it's the convention the user
    described in the framing ("the growth rate would theen 'in
    todays money' be 4.5%") and keeps the math aligned with the
    intuitive subtraction.

    Negative results are NOT clamped. A nominal return of 2% with
    2.5% inflation yields -0.5% real — mathematically meaningful
    (real capital erosion) and the user would be surprised by a
    silent clamp to zero. Documented & locked down by
    `tests/test_todays_value.py`.
    """
    if settings.enabled:
        return float(nominal_rate) - settings.inflation_rate
    return float(nominal_rate)


def effective_income_growth(
    settings: TodayValueSettings, nominal_rate: float
) -> float:
    """Pre-retirement wage curve growth rate used by `_indexed_earned_income`.

    OFF → `nominal_rate`. ON → `nominal_rate - inflation_rate`. Same
    simple-subtraction rule as DC growth: a 2.5% wage growth with
    2.5% inflation yields exactly 0%, so wages stay flat in today's
    view — the intuitive outcome.
    """
    if settings.enabled:
        return float(nominal_rate) - settings.inflation_rate
    return float(nominal_rate)


def effective_asset_growth(
    settings: TodayValueSettings,
    nominal_rate: float,
    asset_type: str,
) -> float:
    """Per-asset growth rate used by the engine's `asset.grow()` loop.

    OFF → `nominal_rate`. ON → depends on `asset_type`:
      * `"Property"` → 0.0 (user-entered capital appreciation is
        zeroed out; the home's nominal £ value is frozen at its
        current figure in today's view).
      * Anything else (ISA, GIA, Cash) →
        `nominal_rate - inflation_rate` (simple subtraction,
        matching the user's "7% nominal becomes 4.5% real" example
        for assets with a 7% assumed return).

    Property is the only asset_type that gets zeroed rather than
    deflated, because the user specifically said "the property
    value growth will not be applied" — NOT "de-rate the property
    growth by inflation". The behavioural distinction is
    significant when comparing a 5% growth Property scenario vs a
    2.5% inflation scenario.
    """
    if not settings.enabled:
        return float(nominal_rate)
    if asset_type == "Property":
        return 0.0
    return float(nominal_rate) - settings.inflation_rate
