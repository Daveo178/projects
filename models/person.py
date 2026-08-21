from dataclasses import dataclass, field
from typing import List, Union
from .events import LifeEvent

@dataclass
class Person:
    """One partner in the household.

    Field semantics
    ---------------
    `name`                : display name. Normally "Person 1" / "Person 2" but the
                            engine doesn't depend on either string.
    `age`                 : current age in years (float, accepts months
                            via the Pension page's `years_and_months_input`
                            widget — e.g. `55 years 6 months` →
                            `55.5`). The simulation loop starts at year 0
                            and adds this to get absolute age for pension
                            kick-in / mortality hooks. Legacy `int`-typed
                            saved JSONs still construct cleanly via
                            Python duck-typing.
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
    `state_pension_age`   : float. Age at which State Pension begins
                            paying for this partner. Float-typed to keep
                            the type system uniform with the other
                            Person ages; in practice the user enters
                            whole-year values, but the years+months
                            widget on the Pensions page now lets the
                            user enter a fractional value if the
                            underlying government threshold is ever
                            approximated to a half-year. The engine
                            math is duck-typed and unchanged.
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
    `draw_age`            : float. Age at which DB pension begins paying.
                            Defaults to 60.0. Independent of
                            `retirement_age` so a partner can stop
                            working earlier than they start DB drawdown
                            (or later). Float-typed for uniformity with
                            the other Person ages; the Pensions page
                            renders the years+months widget for this
                            field too.

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
    # Months precision — same model as `retirement_age` and the
    # `Mortgage.end_year` field. Lets a user enter "55 years 6 months"
    # for `age` (or "67 years 3 months" for `state_pension_age`)
    # instead of being forced to pick a whole-year integer. The
    # Pensions page now pairs each of these fields with a years+
    # months widget so the partial-year-precision round-trips
    # through the form. Engine math is duck-typed float
    # (e.g. `(age + year) >= retirement_age` works for any int/float
    # mix on either side) so no engine changes are needed for the
    # new contract. `state_pension_age` and `draw_age` were
    # historically kept as int because the underlying government /
    # scheme thresholds don't have a "half a year" semantic in real
    # life; we float them so the months widget renders uniformly
    # across all four Person fields, accepting that the persisted
    # whole-year values are now stored with a `.0` suffix in JSON.
    # Legacy int saved JSONs still construct cleanly.
    age: float
    retirement_age: float
    state_pension_age: float
    dc_pot: float
    # Back-compat defaults: legacy saved plans without these keys still
    # construct and behave like a base-rate, no-DB, no-contributions
    # partner. NOTE: defaults are listed AFTER the required fields
    # above so Python's "non-default after default" rule is honoured
    # for `Person(**data)` unpacking anywhere in the codebase.
    db_income: float = 0.0
    draw_age: float = 60.0           # age at which DB pension begins paying
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

    # Legacy contribution fields — kept for BC. The Quick Estimate
    # page now writes the new `personal_contrib_pct` +
    # `employer_contrib_pct` split instead; the Pensions page
    # still binds these for users who haven't visited Quick
    # Estimate. The engine prefers the new fields when ANY of
    # them is set, and falls back to the legacy fields when all
    # three are 0.0 so existing saved plans (which have only
    # monthly_contrib_pct set) continue to behave exactly as
    # before.
    monthly_contrib_pct: float = 0.0

    # Personal (employee) DC contribution split — the employee
    # side of the pension contribution. Entered EITHER as a % of
    # (wage-inflation indexed) annual income OR as a flat
    # £-per-month amount, NOT both. Precedence rules (engine &
    # AA projection): `% > £` — when `personal_contrib_pct > 0`
    # the engine ignores `personal_contrib_flat_monthly` so a
    # legacy user saving both fields still sees the % honoured.
    # Defaults 0.0 reflect the fact that the Quick Estimate page
    # ALWAYS writes these explicitly; 0 is a defensive "neither
    # field set, fall back to legacy" signal rather than a
    # meaningful empty default.
    personal_contrib_pct: float = 0.0
    personal_contrib_flat_monthly: float = 0.0

    # Employer DC contribution — typically a match-contribution
    # percentage of (wage-inflation indexed) annual income
    # (e.g. 3% is a common UK private-sector baseline, public
    # sector and civil-service schemes regularly run 5-15%).
    # Always £/yr in the engine / AA; the Quick Estimate page
    # exposes ONLY a % slider (no flat £ amount option — employers
    # are contracted as % of qualifying earnings in real life).
    # Default 0.0 keeps BC with Plans saved before the feature
    # existed (the engine treats 0 as "no employer contribution,
    # personal contribution stands alone").
    employer_contrib_pct: float = 0.0

    # Monte Carlo per-year growth paths. When NON-EMPTY, the engine
    # uses `path[year]` (mapped through the today's-value transform)
    # instead of the scalar `*_growth_rate` field for that year's
    # calculation. This is what lets the Monte Carlo sampler give each
    # simulation year its own market return / indexation rate instead of
    # holding one rate fixed for the whole run. Deterministic runs and
    # legacy saved plans never set these (they default to empty lists),
    # so the scalar fields remain authoritative there — byte-for-byte
    # identical behaviour. The paths are simulation-internal: they are
    # attached to the dataclass instance by the MC sampler and are never
    # serialised into saved plans (which round-trip through the
    # `household_data` dict, not these instance attributes).
    dc_growth_path: List[float] = field(default_factory=list)
    db_growth_path: List[float] = field(default_factory=list)
    state_pension_growth_path: List[float] = field(default_factory=list)

    life_events: List[Union[LifeEvent, dict]] = field(default_factory=list)

    # Date-of-birth + retirement date (ISO strings like "1970-03-15").
    # Added alongside the existing float `age` / `retirement_age` fields
    # so the Pensions page can persist date-picker values and pre-fill
    # them on the next visit. The engine reads `age` / `retirement_age`
    # as floats (unchanged) — these strings are purely for UI round-
    # tripping. Legacy saved JSONs without these keys construct cleanly
    # because both default to "".
    dob: str = ""
    retirement_date: str = ""

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
