from dataclasses import dataclass, field
from typing import List, Union
from .events import LifeEvent

@dataclass
class Person:
    """One partner in the household.

    Field semantics
    ---------------
    `name`                : display name. Currently "Dave" / "Shaz" but the
                            engine doesn't depend on either string.
    `age`                 : current age in years (int). The simulation loop
                            starts at year 0 and adds this to get absolute
                            age for pension kick-in / mortality hooks.
    `retirement_age`      : age at which the partner STOPS contributing to
                            their DC pot. Now a `float` so the Pensions
                            page can enter fractional values (e.g. `60
                            years 6 months` → `60.5`). Python duck typing
                            means legacy `int` values saved to JSON load
                            cleanly — every comparison below still
                            computes the right answer when the right-
                            hand side happens to be int (e.g. `55 + 5 >=
                            60` and `55 + 5 >= 60.5` both give the
                            correct interpretation). Mirrors the float-
                            typed `Mortgage.end_year` field with the same
                            partial-year contract.
    `state_pension_age`   : int. Age at which State Pension begins paying
                            for this partner. Single-year precision is
                            preserved because the State Pension is a
                            government-set threshold that doesn't have a
                            "half a year" semantic in real life.
    `dc_pot`              : £ balance of this partner's defined-contribution
                            pension pot at simulation start. Compounds
                            monthly at `dc_growth_rate` (annuity-due) and
                            receives the monthly contribution for every
                            pre-retirement year (scaled by `fraction`
                            in the closing partial year — see below).

    `db_income`           : £-per-year DB pension base income that begins
                            paying at `draw_age` (NOT at retirement_age).
                            Indexed annually by `db_growth_rate` once
                            active, so the value at year N is `base *
                            (1+r)**(N - draw_age)`.
    `draw_age`            : age at which DB pension begins paying. Defaults
                            to 60. Independent of `retirement_age` so a
                            partner can stop working earlier than they
                            start DB drawdown (or later).

    `monthly_contrib`     : legacy absolute £-per-month DC contribution.
                            Used only when `monthly_contrib_pct == 0.0`,
                            for backwards compat with plans saved before
                            the % slider was added.
    `pcls_percent` / `pcls_taken` / `pcls_available` : UFPLS-style tax-free
                            lump sum toggle (0..25 % of the pot at
                            retirement, fixed once-and-for-all in step 1b
                            of the engine).
    `dc_growth_rate`      : annual DC pot growth, decimal. Compounded
                            monthly as `(1 + r/12)`.
    `db_growth_rate`      : annual DB pension indexation once active,
                            decimal.
    `state_pension_growth_rate` : annual State Pension indexation once
                            active, decimal.
    `income_until_retirement` : £-per-year salary at year 0. Indexed
                            annually by `income_growth_rate` from year 0
                            to retirement.
    `income_growth_rate`  : annual wage inflation, decimal. Default 2.5 %
                            (typical UK).
    `monthly_contrib_pct` : new model — pension contribution as a
                            percentage of the (wage-inflation-indexed)
                            annual income, decimal. Engine: `M_y =
                            indexed_income_y * pct / 12` each pre-
                            retirement year. When 0, falls back to the
                            legacy `monthly_contrib` £ figure.
    `life_events`         : optional partner-scoped life events for
                            future extensions.

    Partial retirement (closing-year) behavior
    -----------------------------------------
    For integer `retirement_age` (legacy saved JSON), the engine treats
    contributions identically to pre-PR: 12 full months of compound +
    contributions every working year. For fractional `retirement_age`
    (e.g. 60.5), `retirement_offset = retirement_age - age` is
    fractional too, so the engine wires `fraction = min(1.0,
    retirement_offset - year)` into `_dc_monthly_compound` for every
    pre-retirement year — meaning the closing year (year = floor of
    retirement_offset) only pays interest / contributions for the
    fractional slice of that year, mirroring the partial-year scaling
    applied to mortgage amortisation in step 4.
    """
    name: str
    age: int
    retirement_age: float
    state_pension_age: int
    dc_pot: float
    # Back-compat defaults: legacy saved plans without these keys still
    # construct and behave like a base-rate, no-DB, no-contributions
    # partner. NOTE: defaults are listed AFTER the required fields
    # above so Python's "non-default after default" rule is honoured
    # for `Person(**data)` unpacking anywhere in the codebase.
    db_income: float = 0.0
    draw_age: int = 60               # age at which DB pension begins paying
    monthly_contrib: float = 0.0
    income_until_retirement: float = 0.0  # £-per-year salary at year 0; see docstring above.

    # Flexible PCLS (UFPLS-style)
    pcls_percent: int = 0          # 0–25% chosen by user
    pcls_taken: float = 0.0        # how much tax-free has been used
    pcls_available: float = 0.0    # total tax-free allowance (set at retirement)

    # Market growth assumptions. Defaults keep legacy `household_data.json`
    # files (saved before these fields existed) constructing cleanly without
    # explicitly serialised keys. Mean values are nominal:
    #   - DC: 5% (long-run balanced portfolio nominal return)
    #   - DB: 2.5% (typical RPI / CPI indexation)
    #   - State Pension: 2.5% (typical triple-lock-rate approximate)
    dc_growth_rate: float = 0.05
    db_growth_rate: float = 0.025
    state_pension_growth_rate: float = 0.025

    # Wage-inflation indexation applied to `income_until_retirement` from today
    # until the partner reaches `retirement_age`. Default 2.5% — typical UK
    # wage inflation. Compounds annually on the base figure, stops at retirement.
    income_growth_rate: float = 0.025

    # Monthly DC contribution as a percentage of (income-indexed) annual
    # earnings. The Pensions page exposes this as a slider (default 15% — a
    # realistic combined employee + employer total pension contribution). When
    # 0.0, the engine falls back to the legacy `monthly_contrib` £ figure so
    # saved plans targeting a £ amount continue to work unchanged. The
    # Pensions page performs a soft migration that auto-derives a % from a
    # legacy £ month figure the first time a user with stored data opens it.
    monthly_contrib_pct: float = 0.0

    life_events: List[Union[LifeEvent, dict]] = field(default_factory=list)

    def years_to_retirement(self):
        # Returns a `float` so callers that compute a partial-year
        # fraction directly (e.g. the engine's step 2a/2b) get the
        # same type as `retirement_age`. NOTE: this used to return
        # `int` (via `max(0, int-int)`). The change to `float` is BC-
        # safe at the call-site level — every consumer that multiplies
        # it by a float or compares it to a fractional
        # `retirement_age` now works at half-year resolution out of
        # the box — but if a future caller relies on
        # `isinstance(p.years_to_retirement(), int)` it would silently
        # get a float. `max(0.0, ...)` clamps historical / future
        # values where retirement is already in the past.
        return float(max(0, self.retirement_age - self.age))

    def is_retired(self, year_offset: int):
        # `(age + year_offset) >= retirement_age` works for int AND float
        # `retirement_age` (Python duck typing). Half-year resolution:
        # e.g. age=55, year=5, retirement_age=60.5 → 60 >= 60.5 = False
        # (still working at start of year 5), so the engine uses the
        # fractional-closing-year branch for year 5.
        return (self.age + year_offset) >= self.retirement_age

    def is_db_active(self, year_offset: int):
        """True once this person has reached their DB pension draw age."""
        return (self.age + year_offset) >= self.draw_age
