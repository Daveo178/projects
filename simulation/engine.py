from .state_pension import state_pension_income
from .drawdown import drain_single_asset_class
from .spending import (
    apply_late_life_spending_reductions,
    spending_for_age,
)
from .ufpls import _resolve_priority_list, _draw_pension_for_amount
from .today_value import (
    TodayValueSettings,
    effective_asset_growth,
    effective_db_growth,
    effective_dc_growth,
    effective_income_growth,
    effective_state_pension_growth,
    resolve_today_value_settings,
)


def _dc_monthly_compound(pot, dc_rate, monthly_contrib, fraction: float = 1.0):
    """
    Compound `pot` for `12 * fraction` months, with `monthly_contrib` added
    at the END of each compounded month (annuity-due convention).

    For `fraction == 1.0` (default) this is the standard full-year cadence
    of TWELVE monthly iterations:

        pot = pot * (1 + dc_rate / 12) + monthly_contrib

    repeated 12 times. Contributions added AFTER the growth step earn
    growth in months 2..12 — so the first contribution earns growth in 11
    of the 12 months, the eleventh earns growth only in month 12, the
    twelfth earns none.

    For `fraction < 1.0` (partial-year-of-contributions edge case), the
    iteration count scales to `round(12 * fraction)` months — so a
    partner contributing only the first half of the year (fraction=0.5)
    pays growth for SIX monthly iterations rather than the full twelve,
    and only the first six monthly contributions land in the pot. This
    mirrors the partial-year scaling applied to mortgage amortisation in
    step 4 (where a 9y6m mortgage ends mid-year-9 instead of paying a
    full extra year of interest and payment).

    The closed-form equivalent for any number of months `n` is:

        pot_end = pot_start * (1 + r/12) ** n
                + M * ((1 + r/12) ** n - 1) / (r/12)         (r ≠ 0)
        pot_end = pot_start + n * M                          (r == 0)

    Edge cases:
      - `fraction <= 0`      → returns `pot` unchanged. Used by callers
        that want to skip the year's step entirely (e.g., a future
        "skip-this-year" override).
      - `r == 0`             → closed-form `(1+r/12)**n - 1)/(r/12)` is
        0/0; iteration helper naturally avoids it (each step is
        `pot = pot + M`).
      - small fractions      → effectively below ~1/24 (= 0.0416...,
        meaning any sub-month worth of contributions) round to zero
        months, so the helper returns `pot` unchanged for those.
        Python's `round` uses banker's rounding (`round(0.5) == 0`)
        in general — though at the exact 1/24 boundary the result
        is also 0 because `12*(1/24)` falls (very slightly) under
        0.5 in FP, triggering plain rounding-down rather than
        banker's. Either way: 0 months. Documented behaviour:
        sub-month contributions pay no growth. Future callers
        should not pass fractions this small unless they explicitly
        mean "no growth".
      - `fraction > 1.0`     → mathematically extrapolates (more than
        a year of growth in one call). Not expected from any caller
        but the loop handles it cleanly.

    Lifted to module level so test code can import it directly.
    """
    if fraction <= 0:
        return pot
    monthly_rate = dc_rate / 12
    n_months = round(12 * fraction)
    for _ in range(n_months):
        pot = pot * (1 + monthly_rate) + monthly_contrib
    return pot


def _monthly_dc_contrib(person, current_indexed_income):
    """
    Compute the £-per-month DC contribution for one partner for a single
    simulated year.

    Two contribution models are supported, with strict precedence:

      1. New split model (Quick Estimate + any user who has touched the
         new fields). When ANY of the three new fields is set —
             personal_contrib_pct > 0
             personal_contrib_flat_monthly > 0
             employer_contrib_pct > 0
         — the engine sums the personal (£) contribution and the
         employer (£) contribution, both derived from the
         (wage-inflation indexed) annual income where applicable,
         and IGNORES the two legacy fields entirely.

         Precedence within the personal side: `% > £`. When
         `personal_contrib_pct > 0` the engine ignores the flat £
         amount. This matches the existing engine behaviour for the
         legacy fields, so a legacy user saving BOTH the legacy % and
         the new flat £ amount still sees the % honoured (rather than
         silently doubling the contribution).

         Returns:
             personal = (pct > 0)
                 ? indexed_income * personal_contrib_pct / 12
                 : personal_contrib_flat_monthly
             employer = indexed_income * employer_contrib_pct / 12
             M = personal + employer

      2. Legacy model (any saved plan that predates the Quick
         Estimate split). When ALL THREE new fields are zero, fall
         back to the bytes-for-bytes behaviour preserved for
         backwards compatibility — `monthly_contrib_pct > 0` yields
         `indexed_income * monthly_contrib_pct / 12`; otherwise the
         legacy `monthly_contrib / 12` figure is used.

    `getattr(person, ..., 0.0)` defensives on every new field so a
    legacy `Person(...)` instance constructed without them (e.g. a
    unit test passing `Person(name=..., age=..., ...)` with the
    historical positional shape) does NOT raise `AttributeError` — it
    just transparently behaves like the legacy model.
    """
    personal_pct = getattr(person, "personal_contrib_pct", 0.0)
    personal_flat = getattr(person, "personal_contrib_flat_monthly", 0.0)
    employer_pct = getattr(person, "employer_contrib_pct", 0.0)
    if (personal_pct > 0) or (personal_flat > 0) or (employer_pct > 0):
        # New split model — the legacy fields are ignored entirely.
        personal_monthly = (
            current_indexed_income * personal_pct / 12
            if personal_pct > 0
            else personal_flat
        )
        employer_monthly = (
            current_indexed_income * employer_pct / 12
        )
        return personal_monthly + employer_monthly
    # Legacy model — preserved byte-for-byte for BC saved plans
    # that pre-date the Quick Estimate split.
    if person.monthly_contrib_pct > 0:
        return current_indexed_income * person.monthly_contrib_pct / 12
    return person.monthly_contrib / 12


def _indexed_earned_income(person, year, growth_rate_override=None):
    """
    Compute one partner's wage-inflation-indexed earned income for the
    given simulated year. Used to populate `results["earned_income"]` and
    to drive the `% of income` monthly DC contribution calculation.

    Closed form:
        earned(y) = income_until_retirement * (1 + income_growth_rate) ** y
                                                      while (age + y) < retirement_age
        earned(y) = 0                              otherwise

    Year 0 is the baseline (compounded by `(1+r)**0 == 1`). Year N is the
    baseline grown by `(1+r)**N`. Compounding STOPS at retirement, so
    this also implicitly defines the wage curve ending at retirement age.
    Negative `income_growth_rate` is permitted (wage deflation) and does
    not raise — defensive on its own, but the Monte Carlo sampler clamps
    severe negatives via DC_RATE_FLOOR-style logic on a per-year basis.
    Lifted to module level so tests can import it directly.

    `growth_rate_override` (optional): pass a non-None float to bypass
    the person's stored `income_growth_rate`. Used by the "Show in
    today's value" engine mode (`simulation/engine.py::run_simulation`)
    so the wage curve deflates by inflation in today's view (a 2.5%
    nominal wage growth with 2.5% inflation reads as exactly flat
    wages). Defaults to None to preserve the legacy single-argument
    call shape that `tests/test_earned_income_indexing.py` still uses.
    """
    if person.is_retired(year):
        return 0.0
    rate = (
        growth_rate_override
        if growth_rate_override is not None
        else person.income_growth_rate
    )
    return person.income_until_retirement * (1 + rate) ** year


def _effective_rate_series(settings, effective_fn, rate_path):
    """Map a Monte Carlo per-year nominal growth path through the
    today's-value transform, or return None when no path is attached.

    Deterministic runs and legacy plans never attach a path, so the
    scalar effective rate computed once at the top of `run_simulation`
    remains authoritative there (byte-identical output). When the MC
    sampler supplies `rate_path` (a list with one nominal rate per
    simulation year), each element is transformed by `effective_fn` —
    e.g. `effective_state_pension_growth` turns every element into 0.0
    in today's-value mode, which is exactly what keeps State Pension
    flat in today's view even with a stochastic path attached.
    """
    if isinstance(rate_path, (list, tuple)) and len(rate_path):
        return [effective_fn(settings, float(r)) for r in rate_path]
    return None


def _indexed_payout(base, years_active, rate, rate_path, first_active_year):
    """Apply an indexed income stream's growth for one simulation year.

    Scalar mode (no `rate_path`): `base * (1 + rate) ** years_active` —
    the legacy formula used for DB pensions. Path mode (Monte Carlo):
    a cumulative product over the per-year effective rates actually
    active since the stream started paying, so year-to-year indexation
    variation compounds correctly instead of being approximated by a
    single exponent.
    """
    if years_active <= 0:
        return base
    if rate_path is not None:
        start = max(0, int(round(first_active_year)))
        factor = 1.0
        for r in rate_path[start : start + int(years_active)]:
            factor *= (1 + float(r))
        return base * factor
    return base * (1 + rate) ** years_active




def run_simulation(household, years=None):
    """
    Runs a year-by-year simulation of the household finances.
    Returns a dictionary of results for charts and AI analysis.

    `years` resolution (latest wins):
        - explicit caller override (`run_simulation(h, years=N)`) wins
          — used by the Monte Carlo sampler and the What If page's
          slider so those callers can test alternative horizons
          without touching the saved Household.
        - otherwise (`years=None`, the default), the engine reads
          `household.life_expectancy_end_age` (default 95.0,
          configurable on Page 2 → "Plan until age") and computes
          the horizon from there.
        - legacy `Household(...)` instances without the new
          dataclass field fall back to 95.0 via `getattr(...,
          "life_expectancy_end_age", 95.0)`, so older saved JSON
          plans continue to run.

    Joint-life (last-to-die) horizon math: the simulation runs for
    `max(end_age - p1.age, end_age - p2.age)` years so the plan
    funds BOTH partners through the target age. A pair aged 55 + 60
    with `life_expectancy_end_age=95` runs 40 years (the older
    partner drives the horizon). A floor of 5 years protects the
    engine when both partners are already past the target (avoids
    0-length or negative-length axis sequences on the chart
    series, which crash `np.array(all_paths)` in the Monte Carlo
    percentile step).
    """

    # `years` resolution — caller override wins, else compute from
    # `life_expectancy_end_age` so the saved plan's horizon
    # propagates everywhere (Page 1 Home, Page 6 Scenarios, Page 8
    # Monte Carlo) without each caller having to perform the same
    # remaining-life math. In single-retiree mode Person 2 is not an
    # active life and therefore cannot extend the horizon.
    single_retiree = bool(getattr(household, "single_retiree", False))
    if years is None:
        end_age = float(
            getattr(household, "life_expectancy_end_age", 95.0)
        )
        p1_age = float(getattr(household.person1, "age", 55.0))
        p2_age = float(getattr(household.person2, "age", 55.0))
        remaining_years = [int(round(end_age - p1_age))]
        if not single_retiree:
            remaining_years.append(int(round(end_age - p2_age)))
        years = max(remaining_years)
        years = max(5, years)

    # ---- "Show in today's value" — effective-rate resolution ----
    # Read the household dataclass flags once, defensively (`getattr`
    # tolerates legacy `Household(...)` instances without the new
    # fields). All today's-value rate overrides below read from
    # `settings` rather than re-reading the dataclass per year, so
    # the year-loop body stays a clean transform of nominal rates.
    # Mirror docs (and rationale per field) live in
    # `simulation/today_value.py`; this block is the engine-side
    # side of that contract.
    settings: TodayValueSettings = resolve_today_value_settings(household)
    p1_db_eff = effective_db_growth(
        settings, household.person1.db_growth_rate
    )
    p2_db_eff = effective_db_growth(
        settings, household.person2.db_growth_rate
    )
    p1_sp_eff = effective_state_pension_growth(
        settings, household.person1.state_pension_growth_rate
    )
    p2_sp_eff = effective_state_pension_growth(
        settings, household.person2.state_pension_growth_rate
    )
    p1_dc_eff = effective_dc_growth(
        settings, household.person1.dc_growth_rate
    )
    p2_dc_eff = effective_dc_growth(
        settings, household.person2.dc_growth_rate
    )
    p1_inc_eff = effective_income_growth(
        settings, household.person1.income_growth_rate
    )
    p2_inc_eff = effective_income_growth(
        settings, household.person2.income_growth_rate
    )

    # Monte Carlo per-year growth paths (optional). When the MC sampler
    # attaches `dc_growth_path` / `db_growth_path` /
    # `state_pension_growth_path` to a person, each year of the loop uses
    # that year's effective rate instead of the scalar above — this is
    # what gives every simulation year its own market return / indexation
    # instead of one fixed rate for the whole run. `None` for
    # deterministic runs and legacy plans, preserving the scalar path
    # byte-for-byte. Precomputed here (once, outside the year loop) so
    # the loop body stays a cheap lookup.
    p1_dc_eff_path = _effective_rate_series(
        settings,
        effective_dc_growth,
        getattr(household.person1, "dc_growth_path", None),
    )
    p2_dc_eff_path = _effective_rate_series(
        settings,
        effective_dc_growth,
        getattr(household.person2, "dc_growth_path", None),
    )
    p1_db_eff_path = _effective_rate_series(
        settings,
        effective_db_growth,
        getattr(household.person1, "db_growth_path", None),
    )
    p2_db_eff_path = _effective_rate_series(
        settings,
        effective_db_growth,
        getattr(household.person2, "db_growth_path", None),
    )
    p1_sp_eff_path = _effective_rate_series(
        settings,
        effective_state_pension_growth,
        getattr(household.person1, "state_pension_growth_path", None),
    )
    p2_sp_eff_path = _effective_rate_series(
        settings,
        effective_state_pension_growth,
        getattr(household.person2, "state_pension_growth_path", None),
    )

    results = {
        # Top-level view-mode badge. Either "today" (showing in today's
        # value, with inflation stripped) or "nominal" (default, with
        # all growth rates compounding in current-£ terms). Used by
        # downstream pages (Page 1 caption, Page 11 Timeline label,
        # Page 10 Tax View subtitle) to display the appropriate
        # badge so the user is never confused about which view they're
        # looking at. Set ONCE at the top of `run_simulation` so
        # every result series can be uniformly self-labeled without a
        # second session-state lookup.
        "view_mode": "today" if settings.enabled else "nominal",
        "inflation_rate": settings.inflation_rate,
        "tax": [],
        "net_income": [],
        "gross_income": [],
        "effective_tax_rate": [],
        "years": [],
        "net_worth": [],
        "income": [],
        "spending": [],
        "dc_pot": [],
        "isa_value": [],
        "gia_value": [],
        "cash_value": [],
        "property_value": [],
        "mortgage_balance": [],
        "mortgage_payment": [],
        "tax_free_income": [],
        "events_triggered": [],
        "pension_income": [],
        "earned_income": [],
        # Per-spouse tax breakdowns. The four "household" keys above
        # (`gross_income`, `tax`, `net_income`, `effective_tax_rate`) are
        # kept as HOUSEHOLD sums (= p1 + p2) so downstream pages 10/11 and
        # Timeline continue to consume identical numeric shapes — only the
        # household TAX line moves from "joint single-taxpayer call" to
        # "sum of two per-spouse calls". The per-spouse series below
        # enable the AI Analysis page to quote spousal tax figures.
        "p1_gross_income": [],
        "p2_gross_income": [],
        "p1_tax": [],
        "p2_tax": [],
        # Per-spouse National Insurance. Same per-spouse rationale as
        # the income-tax series above — NI applies to each partner's
        # earned salary independently, with their own £12,570 primary
        # threshold and £50,270 upper earnings limit. Pension income
        # (DB, SP, UFPLS) is NOT subject to NI; `p1_ni`/`p2_ni` are
        # £0 once a partner retires because the engine's
        # `_indexed_earned_income` helper returns 0 then.
        "ni": [],
        "p1_ni": [],
        "p2_ni": [],
        # Per-source funding breakdown — drives the Timeline page's
        # stacked-bar visualisation. Each entry lists the £ contributed by
        # one source to fund this year's spending:
        #   * db_payout / state_payout — pre-tax income the household
        #     actually received from DB pension / State Pension that year.
        #     Their sum per year equals the existing `pension_income`
        #     household total.
        #   * ufpls_taxable_gross — pre-tax £ drawn from the DC pot as
        #     UFPLS (capped at the actual remaining pot).
        #   * ufpls_taxable_net   — post-tax take-home from that UFPLS
        #     drawdown (i.e. `gross` minus the additional income tax it
        #     triggered). Older saved results may not have this; the
        #     Timeline page falls back to zeros.
        #   * tax_free_income     — PCLS take-home (tax-free by
        #     construction). Pre-existing field.
        #   * isa_draw / gia_draw / cash_draw — £ withdrawn from each
        #     asset class to fund any residual shortfall after UFPLS.
        #     `isa_draw` and `cash_draw` are zero-tax assumed at the
        #     household level; `gia_draw` keeps a placeholder for a
        #     future CGT layer. Pre-existing drawdown waterfall (Cash
        #     → ISA → GIA) is unchanged.
        "ufpls_taxable_net": [],
        "ufpls_taxable_gross": [],
        "db_payout": [],
        "state_payout": [],
        "isa_draw": [],
        "gia_draw": [],
        "cash_draw": [],
    }

    for year in range(years):
        results["years"].append(year)

        # -------------------------
        # 1. Income (earned, DB, state pension)
        # -------------------------
        income = 0
        gross_income = 0
        # PCLS (tax-free drawdown) accumulator — initialised at the top
        # of the year loop so the `net_income` calculation below can
        # reference it regardless of whether drawdown fired this year.
        # When UFPLS/PCLS drawdown does fire, the block below increments
        # this via `tax_free_draw += tax_free_draw_call`.
        tax_free_draw = 0.0
        taxable_draw = 0.0  # needed by ETR denominator — UFPLS taxable
        ufpls_take_home = 0.0  # post-tax UFPLS take-home; recomputed after waterfall
        # Per-source asset-draw accumulators — populated by the
        # drawdown blocks below (Cash / ISA / GIA). Initialised at the
        # year-loop top so `net_income` can sum them regardless of which
        # branch (any_retired / cash_buffer / else) fires this year.
        per_source = {"Cash": 0.0, "ISA": 0.0, "GIA": 0.0}
        pension_income = 0  # sum of indexed DB + State Pension income for
                            # both partners; saved separately so the
                            # Timeline page can show how pension income
                            # creeps up over the retirement horizon.

        # Person 1 — pre-retirement earned income is wage-inflation indexed
        # from "now" (year 0) via `income_growth_rate` (default 2.5%). The same
        # indexed figure is also stored in `earned_income` for charting and
        # AI analysis, so the indexed wage curve is visible without having to
        # back-calculate from gross_income minus pension_income. The closed-
        # form helper `_indexed_earned_income` returns 0.0 from retirement
        # onwards, which is additive-identity for `gross_income` and lets us
        # drop the explicit `is_retired` branch here. When the household is
        # in today's-value mode (`settings.enabled`), the wage curve deflates
        # by inflation via `p1_inc_eff` so a 2.5% nominal growth with 2.5%
        # inflation reads as exactly 0% real.
        p1_earned_this_year = _indexed_earned_income(
            household.person1, year, growth_rate_override=p1_inc_eff
        )
        p1_sp_year = state_pension_income(
            household.person1,
            year,
            growth_rate_override=p1_sp_eff,
            growth_path=p1_sp_eff_path,
        )
        pension_income += p1_sp_year
        p1_gross = p1_earned_this_year + p1_sp_year
        # DB pension only begins paying at draw_age, not at retirement_age.
        # Once active, the income grows each year by the person's
        # `db_growth_rate` (default 2.5% — typical RPI / CPI indexation), so
        # the value at year N is `base * (1+r) ** (N - draw_age)`. The base
        # `db_income` field stays untouched — only the effective payout
        # increases with each year of payment. The same value also flows
        # into `pension_income` (the indexed-pension-only series).
        # `p1_db_income_year` / `p2_db_income_year` are referenced at year-
        # end by the `db_payout` series, so they must be defined for every
        # year — 0 when the partner has not yet reached `draw_age`. In
        # today's-value mode, `p1_db_eff` is 0% so the payout stays flat at
        # `db_income` from `draw_age` onwards.
        p1_db_income_year = 0.0
        if household.person1.is_db_active(year):
            p1_db_years_active = max(
                0,
                (household.person1.age + year) - household.person1.draw_age,
            )
            p1_db_income_year = _indexed_payout(
                household.person1.db_income,
                p1_db_years_active,
                p1_db_eff,
                p1_db_eff_path,
                household.person1.draw_age - household.person1.age,
            )
            p1_gross += p1_db_income_year
            pension_income += p1_db_income_year

        # Person 2 — same accounting as Person 1 in couple mode. In
        # single-retiree mode every Person 2 income source is explicitly
        # zeroed, including State Pension; this is stronger than relying
        # on a sentinel retirement/state-pension age and prevents stale or
        # manually entered Person 2 data from leaking into the projection.
        p2_db_income_year = 0.0
        if single_retiree:
            p2_earned_this_year = 0.0
            p2_sp_year = 0.0
            p2_gross = 0.0
        else:
            p2_earned_this_year = _indexed_earned_income(
                household.person2, year, growth_rate_override=p2_inc_eff
            )
            p2_sp_year = state_pension_income(
                household.person2,
                year,
                growth_rate_override=p2_sp_eff,
                growth_path=p2_sp_eff_path,
            )
            pension_income += p2_sp_year
            p2_gross = p2_earned_this_year + p2_sp_year
            if household.person2.is_db_active(year):
                p2_db_years_active = max(
                    0,
                    (household.person2.age + year) - household.person2.draw_age,
                )
                p2_db_income_year = _indexed_payout(
                    household.person2.db_income,
                    p2_db_years_active,
                    p2_db_eff,
                    p2_db_eff_path,
                    household.person2.draw_age - household.person2.age,
                )
                p2_gross += p2_db_income_year
                pension_income += p2_db_income_year

        # UK taxes spouses separately on their own income — each partner
        # gets their own £12,570 PA and their own £100k taper. Sum the two
        # per-spouse tax calls to get household net. `gross_income` stays as
        # the household SUM (= p1_gross + p2_gross), so downstream pages
        # 10/11 and Timeline consume the same numeric shape they always did.
        # Only the household TAX line moves from "single joint call" to
        # "p1_tax + p2_tax". See tests/test_tax.py for the math.
        gross_income = p1_gross + p2_gross
        from .tax import uk_income_tax
        p1_tax_result = uk_income_tax(p1_gross)
        p2_tax_result = uk_income_tax(p2_gross)
        # NI applies ONLY to earned salary — never to DB, SP, or UFPLS.
        # The `_indexed_earned_income` helper already returns 0 from
        # retirement, so this naturally yields £0 NI for retirees.
        from .tax import uk_national_insurance
        p1_ni = uk_national_insurance(p1_earned_this_year)
        p2_ni = uk_national_insurance(p2_earned_this_year)
        income = p1_tax_result["net"] + p2_tax_result["net"] - p1_ni - p2_ni
        # Snapshot the no-UFPLS tax results so the drawdown block later
        # can compute "how much additional tax did the UFPLS draw trigger"
        # by subtracting post-UFPLS `.tax` from `*_top.tax`. The block
        # re-binds `p1_tax_result` / `p2_tax_result` when drawdown is
        # needed; this anchor must stay untouched.
        p1_tax_result_top = p1_tax_result
        p2_tax_result_top = p2_tax_result

        # ---------------------------------------------------------
        # 1b. Calculate total PCLS allowance at retirement (once)
        # ---------------------------------------------------------
        if household.person1.is_retired(year) and household.person1.pcls_available == 0:
            household.person1.pcls_available = (
                household.person1.dc_pot * (household.person1.pcls_percent / 100)
            )

        if (
            not single_retiree
            and household.person2.is_retired(year)
            and household.person2.pcls_available == 0
        ):
            household.person2.pcls_available = (
                household.person2.dc_pot * (household.person2.pcls_percent / 100)
            )

        # -------------------------
        # 2a/2b. DC pot — MONTHLY compounding of growth plus MONTHLY
        #    contributions within each simulated year. Helpers live at module
        #    level (`_dc_monthly_compound`, `_monthly_dc_contrib`) so unit
        #    tests can import them directly.
        #
        #    Partial-year-of-contributions wiring: `retirement_offset =
        #    retirement_age - age` is the partner's years-to-retirement.
        #    When it has a fractional component (e.g. retirement_age=60.5,
        #    age=55, offset=5.5), only the fractional slice of the closing
        #    simulation year (`floor(retirement_offset)`) actually carries
        #    contributions / growth. The engine computes
        #    `fraction = min(1.0, retirement_offset - year)` for every PRE-
        #    retirement year and passes it as the 4th arg to
        #    `_dc_monthly_compound`. The helper then iterates the partial
        #    slice (`round(12 * fraction)` months) instead of the full 12.
        #    After retirement (`year >= retirement_offset`), contributions
        #    stop (M=0) but the pot KEEPS compounding for the full 12
        #    months at `fraction=1.0` — preserving the existing post-
        #    retirement behaviour. This conditional avoids handing the
        #    helper a negative fraction, which would otherwise trigger its
        #    `if fraction <= 0: return pot` short-circuit and silently
        #    cancel post-retirement growth.
        #
        #    BC guarantee: when `retirement_age` is an integer (legacy saved
        #    JSON), `retirement_offset` is an integer, and
        #    `min(1.0, retirement_offset - year)` evaluates to 1.0 for
        #    every pre-retirement year — so the helper still runs the same
        #    12 iterations with the same per-step ops on the same operands
        #    in the same order as pre-PR. Byte-identical output for all
        #    existing scenarios (locked down by
        #    `TestEngineDcEndToEnd.test_ten_year_pct_path_matches_closed_form`
        #    in tests/test_dc_compound.py).
        #
        #    Mirrors the partial-year scaling applied to mortgage
        #    amortisation in step 4. The Mortgage partial-year slices
        #    `end_year` into (years, months); this Retirement partial-year
        #    slice mirrors the same conceptual "what fraction of this
        #    year remains" pattern.
        # -------------------------
        p1_M = _monthly_dc_contrib(household.person1, p1_earned_this_year)
        p2_M = (
            0.0
            if single_retiree
            else _monthly_dc_contrib(household.person2, p2_earned_this_year)
        )

        p1_retirement_offset = (
            household.person1.retirement_age - household.person1.age
        )
        p2_retirement_offset = (
            household.person2.retirement_age - household.person2.age
        )

        if year < p1_retirement_offset:
            p1_fraction = min(1.0, p1_retirement_offset - year)
            p1_M_for_year = p1_M
        else:
            # Post-retirement: no contributions, full 12 months of
            # compound growth so the pot still appreciates during the
            # drawdown horizon. Same shape as the pre-PR post-retirement
            # path.
            p1_fraction = 1.0
            p1_M_for_year = 0.0
        if year < p2_retirement_offset:
            p2_fraction = min(1.0, p2_retirement_offset - year)
            p2_M_for_year = p2_M
        else:
            p2_fraction = 1.0
            p2_M_for_year = 0.0

        # DC pot growth uses the effective rate (`p1_dc_eff` / `p2_dc_eff`)
        # so today's-value mode deflates growth by inflation. The
        # contribution £-amount is also deflated: `p1_M` /
        # `p2_M` were computed via `income * pct / 12` from the
        # already-deflated `p1_earned_this_year` /
        # `p2_earned_this_year`, so a pct-of-income contribution
        # tracks the real wages naturally. The legacy absolute-£
        # `monthly_contrib` (used when `monthly_contrib_pct == 0`)
        # is declared flat in today's-money terms too — the user
        # typically intends "£200/mo into the pension" as a real
        # figure, so it stays as-is (no deflator applied).
        # Monte Carlo per-year DC rates: use `path[year]` when the sampler
        # attached one (with a defensive length check), otherwise the
        # scalar effective rate — identical behaviour for deterministic
        # runs and legacy plans.
        p1_dc_rate = (
            p1_dc_eff_path[year]
            if p1_dc_eff_path is not None and year < len(p1_dc_eff_path)
            else p1_dc_eff
        )
        p2_dc_rate = (
            p2_dc_eff_path[year]
            if p2_dc_eff_path is not None and year < len(p2_dc_eff_path)
            else p2_dc_eff
        )
        household.person1.dc_pot = _dc_monthly_compound(
            household.person1.dc_pot,
            p1_dc_rate,
            p1_M_for_year,
            fraction=p1_fraction,
        )
        if not single_retiree:
            household.person2.dc_pot = _dc_monthly_compound(
                household.person2.dc_pot,
                p2_dc_rate,
                p2_M_for_year,
                fraction=p2_fraction,
            )

        # -------------------------
        # 2b. Asset contributions — keep paying into ISA/GIA/Cash while
        # at least one person is still working. Stop once both partners
        # have retired (joint household convention).
        # -------------------------
        household_retired = household.person1.is_retired(year)
        if not single_retiree:
            household_retired = household_retired and household.person2.is_retired(year)
        if not household_retired:
            for asset in household.assets:
                if asset.contribution_until_retirement > 0:
                    asset.value += asset.contribution_until_retirement

        # -------------------------
        # 3. Asset Growth
        # -------------------------
        # Today's-value mode zeros Property appreciation and deflates
        # ISA / GIA / Cash growth by inflation (see
        # `simulation/today_value.py::effective_asset_growth`). The
        # `Asset.grow()` method itself is unchanged so a hand-built
        # Asset instance from a test (which calls `.grow()` directly)
        # still sees the user's stored nominal rate — the override
        # is applied AT THE ENGINE'S CALL SITE, not in
        # `Asset.grow()`. Bit-reversed: flipping the toggle back to
        # OFF takes us back to the original 5%-on-Property growth
        # without any further changes.
        for asset in household.assets:
            # Monte Carlo per-year asset returns: when the sampler attached
            # `asset.growth_path`, use that year's rate so each simulation
            # year gets its own sampled return (sequence-of-returns risk).
            # Deterministic runs leave the path empty and use the scalar
            # `growth_rate`, unchanged.
            rate = asset.growth_rate
            asset_growth_path = getattr(asset, "growth_path", None)
            if (
                isinstance(asset_growth_path, (list, tuple))
                and year < len(asset_growth_path)
            ):
                rate = asset_growth_path[year]
            asset.value *= (
                1 + effective_asset_growth(settings, rate, asset.asset_type)
            )

        # -------------------------
        # 4. Mortgage — reducing-balance amortisation.
        #    Order: accrue interest ON the outstanding balance at the quoted
        #    annual rate, then take the payment+overpayment off the (now
        #    higher) balance, capped so it can never go negative. This is the
        #    standard UK repayment-mortgage cadence: interest compounds on
        #    whatever balance is left, then the regular payment (plus any
        #    voluntary overpayment) reduces capital for NEXT year's interest
        #    calculation. `mortgage_paid` is the AMOUNT actually paid (capped
        #    when the debt is cleared mid-year) — it is folded into the
        #    household's total outflow requirement below so drawdown covers
        #    the mortgage as well as living expenses.
        #
        #    Partial-year scaling: `Mortgage.end_year` is a float, so a
        #    9y6m mortgage has end_year=9.5. In the closing simulation
        #    year (year=9), only half a year of interest accrues and half
        #    a year of payment is due. `fraction = min(1.0, end_year -
        #    year)` collapses this to <1.0 for the closing year and
        #    stays 1.0 for every interior year. Sub-fraction scaling is
        #    applied to BOTH the interest accrual (via
        #    `apply_interest(fraction)`) and the planned payment so the
        #    loan actually closes mid-year-9 instead of finishing a
        #    full extra year of interest and payment. Years where the
        #    mortgage isn't `is_active` (year >= end_year) skip the
        #    whole block via `is_active`'s `year < end_year` gate.
        # -------------------------
        mortgage_paid = 0.0
        if household.mortgage and household.mortgage.is_active(year):
            fraction = min(1.0, household.mortgage.end_year - year)
            household.mortgage.apply_interest(fraction)
            planned = (
                household.mortgage.annual_payment
                + household.mortgage.annual_overpayment
            ) * fraction
            mortgage_paid = min(planned, household.mortgage.outstanding)
            household.mortgage.outstanding -= mortgage_paid

        # -------------------------
        # 5. Life Events (including downsizing)
        # -------------------------
        # Pre-refactor this loop was: TWO separate `if hasattr(...)`
        # blocks — the old engine duck-typed `hasattr(event, "amount")`
        # vs `hasattr(event, "sell_property_value")` and dispatched each
        # event into either the cash branch OR the downsizing branch.
        # The two predicates were always mutually exclusive because the
        # two dataclasses (LifeEvent vs DownsizingEvent) were disjoint.
        #
        # Post-refactor EVERY event is a `LifeEvent` and has BOTH
        # `amount` and `sell_property_value` as dataclass fields (with
        # default 0.0). The two `hasattr(...)` checks would have
        # always returned True, so the loop would have fired BOTH
        # branches — silently double-triggering (description + "Downsizing")
        # and double-counting the cash add. Switched to VALUE-based
        # predicates, which are coprime because cash events have
        # `amount != 0` AND `sell_property_value == 0` (dataclass
        # default), while downsizing events have `amount == 0` (no
        # `amount` key in the saved JSON, fills dataclass default) AND
        # `sell_property_value > 0`. The conditional structure below
        # explicitly guarantees mutual exclusion:
        #
        #   1) Downsizing branch (event.sell_property_value > 0) — the
        #      first branch precisely because it MUTATES state
        #      (property value, cash, mortgage). Anything else falls
        #      through to the standard `else` cash/memo branch, which
        #      only adds to cash when amount != 0 (i.e. a real cash
        #      event, not a memo with amount=0).
        #
        # Memos (amount=0, sell=0, no money moving) still log their
        # description to `triggered` so the audit trail shows a row
        # fired this year, even though no £ movement occurred — same
        # shape as the pre-refactor behaviour.
        triggered = []

        if household.events:
            for event in household.events:
                if event.year == year:
                    if event.sell_property_value > 0:
                        # Downsizing event.
                        triggered.append("Downsizing")

                        # 1. Sell current property at sell_property_value
                        #    and replace with new_property_value.
                        for asset in household.assets:
                            if asset.asset_type == "Property":
                                sale_proceeds = event.sell_property_value
                                asset.value = event.new_property_value
                                break

                        # 2. Add sale proceeds to cash.
                        for asset in household.assets:
                            if asset.asset_type == "Cash":
                                asset.value += sale_proceeds
                                break

                        # 3. Clear mortgage if present.
                        if household.mortgage:
                            household.mortgage.outstanding = 0
                    else:
                        # Standard life event — cash inflow (amount > 0),
                        # cash outflow (amount < 0), or memo (amount = 0
                        # with a description). Memo events still log to
                        # `triggered` for the audit trail without any
                        # cash mutation.
                        triggered.append(event.description)
                        if event.amount != 0:
                            for asset in household.assets:
                                if asset.asset_type == "Cash":
                                    asset.value += event.amount
                                    break

        results["events_triggered"].append(triggered)
        results["gross_income"].append(gross_income)

        # -------------------------
        # 6. Spending (with strategy)
        # -------------------------
        strategy = getattr(household, "drawdown_strategy", "Fixed")
        spending_target_path = getattr(
            household, "spending_target_path", None
        )

        # Monte Carlo supplies a nominal, inflation-indexed spending path.
        # Use it when present so sampled inflation affects both spending and
        # the eventual wealth path. Normal deterministic runs do not carry
        # this optional attribute and retain the strategy logic below.
        if (
            isinstance(spending_target_path, (list, tuple))
            and year < len(spending_target_path)
            and strategy != "Safe Withdrawal (4%)"
        ):
            spending = float(spending_target_path[year])
        elif strategy == "Spending phases":
            # Explicit age bands are intentionally easier to audit than a
            # percentage taper. The amounts are stored in today's money and
            # therefore stay flat within each band in today's-value mode.
            # They also remain absolute amounts in nominal mode: this is the
            # same simple contract users see on Quick Estimate.
            spending = spending_for_age(
                household.person1.age + year,
                getattr(household, "spending_phases", []),
                fallback_spending=household.spending_target,
            )

        elif strategy == "Fixed":
            spending = household.spending_target

        elif strategy == "Inflation-adjusted":
            # Today's-value mode skips the inflation uplift — base
            # £ stays flat year-over-year. Match the user's mental
            # model: "all calculations displayed without inflation".
            if settings.enabled:
                spending = household.spending_target
            else:
                spending = household.spending_target * ((1 + 0.025) ** year)

        elif strategy == "Tapered (down with age)":
            # Inflation-adjusted BASE so the taper is REAL-terms
            # (each 1-yr step compounds (1 - rate) on a base that
            # ALSO uplifts with inflation), not nominal. A 2% taper
            # over a 2.5%-inflation horizon would otherwise drop
            # real purchasing power by ~4.5%/yr — not what the user
            # means when they say "later life will probably spend
            # less" (the canonical "go-go → slow-go" curve).
            #
            # Optional go-go bump (opt-in via `gogo_bump_pct`,
            # default 0.0 so legacy users see the original
            # pure-taper behaviour byte-identically). When non-zero,
            # the trajectory becomes a hump-shape: spends RAMP UP
            # by `gogo_bump%/yr` from retirement age to
            # `taper_start_age` (= peak), then ramps DOWN by
            # `taper_rate/yr`. Math is exactly the inverse of Phase 2:
            #
            #   Phase 1 (years_into_retirement < start_age - ret):
            #     base_nominal * (1 + gogo_bump)**years_into_ret
            #   Phase 2 (age >= start_age):
            #     base_nominal
            #       * (1 + gogo_bump)**(years_at_peak)
            #       * (1 - taper_rate)**(years_past_peak)
            #
            # Anchored on person1's retirement_age (matches the
            # existing pre-retirement code-path on partial-year
            # DC contributions, mortgage amortisation, etc.).
            # Pre-retirement years (year < years_to_retirement) see
            # only the straight inflation-adjusted base — working
            # years usually don't exhibit a "go-go" pattern (you
            # can't spend more travel money when you still have a
            # mortgage and children in school), so the bump is
            # deliberately scoped to post-retirement only.
            #
            # Floor caps the asymptotic approach to zero in late
            # life. Default £10k approximates State Pension level
            # — below which most UK retirees would still have SP
            # topping up. Tunable via `taper_floor_gbp`.
            base_nominal = (
                household.spending_target
                if settings.enabled
                else household.spending_target * ((1 + 0.025) ** year)
            )
            start_age = float(getattr(household, "taper_start_age", 75.0))
            rate = float(getattr(household, "taper_rate", 0.02))
            gogo_bump = float(
                getattr(household, "gogo_bump_pct", 0.0)
            ) / 100.0
            age_p1_at_year = household.person1.age + year
            years_to_retirement = max(
                0.0,
                household.person1.retirement_age - household.person1.age,
            )
            if year < years_to_retirement:
                # Pre-retirement — straight inflation-adjusted
                # base. No gogo, no taper (working years).
                spending = base_nominal
            elif age_p1_at_year < start_age:
                # Phase 1 (go-go) — ramp UP by gogo_bump per year
                # past retirement_age, peaking at `taper_start_age`.
                years_into_retirement = year - years_to_retirement
                gogo_factor = (1.0 + gogo_bump) ** years_into_retirement
                spending = base_nominal * gogo_factor
            else:
                # Phase 2 (post-peak) — ramp DOWN by taper_rate
                # per year past `taper_start_age`. Anchor at the
                # Phase-1 peak value so the trajectory is continuous
                # at the peak (no jump discontinuity at the
                # boundary year).
                years_at_peak = max(
                    0.0, start_age - household.person1.retirement_age
                )
                peak_factor = (1.0 + gogo_bump) ** years_at_peak
                years_past_peak = age_p1_at_year - start_age
                spending = (
                    base_nominal * peak_factor
                    * ((1.0 - rate) ** years_past_peak)
                )
            # Optional age-based step-downs are applied after the existing
            # continuous taper. They are deliberately separate from
            # `taper_rate`: users can model a sharper reduction at (for
            # example) 75 and another at 85 without changing the gradual
            # year-on-year curve. The helper sorts the stages by age and
            # clamps malformed rates defensively.
            if year >= years_to_retirement:
                # These are explicitly post-retirement reductions. The
                # defensive gate matters if hand-edited data sets a step
                # age below retirement_age: working-life spending must not
                # be reduced by a late-life assumption.
                spending = apply_late_life_spending_reductions(
                    spending,
                    age_p1_at_year,
                    step_1_age=getattr(
                        household, "late_life_step_1_age", 75.0
                    ),
                    step_1_rate=getattr(
                        household, "late_life_step_1_rate", 0.0
                    ),
                    step_2_age=getattr(
                        household, "late_life_step_2_age", 85.0
                    ),
                    step_2_rate=getattr(
                        household, "late_life_step_2_rate", 0.0
                    ),
                )
            taper_floor = float(
                getattr(household, "taper_floor_gbp", 10_000.0)
            )
            spending = max(spending, taper_floor)

        elif strategy == "Safe Withdrawal (4%)":
            total_assets = sum(a.value for a in household.assets) + household.person1.dc_pot
            if not single_retiree:
                total_assets += household.person2.dc_pot
            spending = total_assets * 0.04

        else:
            spending = household.spending_target

        # -------------------------
        # 7. Drawdown if needed (phantom-safe UFPLS + per-source split)
        #    Total outgoings = spending target + mortgage payment this year —
        #    UNLESS the user has folded the mortgage into their spending
        #    figure (`include_in_spending=True`, the Assets-page toggle
        #    "Include mortgage payment in spending"). In that case their
        #    `spending` figure ALREADY covers the mortgage, so adding
        #    `mortgage_paid` on top would double-fund the loan and make the
        #    income bars over-shoot the user's spending target (the £54,608
        #    bars vs the user's £38,000 target on the Quick Estimate chart:
        #    38,000 spending + 16,608 mortgage = 54,608). With the flag ON,
        #    `total_need = spending` (mortgage comes out of the spending
        #    figure); with the flag OFF (default), spending is lifestyle-only
        #    and the mortgage is funded on top. `results["spending"]` stays
        #    the user's entered figure either way; the mortgage is still
        #    tracked separately in `results["mortgage_payment"]`.
        #
        #    The pre-fix path computed a `taxable_draw = required -
        #    tax_free_draw`, and then allocated that full amount
        #    proportionally to the partners' DC pots every year — including
        #    years when the pots had been exhausted. With `total_dc == 0`
        #    the engine slipped into a "default 50/50 split" branch that
        #    pretended each partner had drawn a chunk of UFPLS even though
        #    no money actually moved pools. The phantom drawdown hit
        #    `uk_income_tax(gross + taxable_drawdown)` and bias-ed the
        #    per-spouse taxes DOWN (each partner got their own £12,570 PA
        #    on a £17.5k slice), which then biased `p1_tax.net +
        #    p2_tax.net + tax_free_draw` UP at the precise year the pot
        #    actually emptied — producing the £30,514 → £32,714 jump on
        #    the Timeline Income line.
        #
        #    Fix: cap `actual_ufpls` at the ACTUAL `total_dc_at_start`;
        #    pro-rate the PCLS/taxable split on the cap; per-spouse tax
        #    is computed only on each partner's REAL taxable drawdown;
        #    any residual shortfall after UFPLS routes through Cash →
        #    ISA → GIA via `drawdown_from_assets` (whose return shape
        #    now includes a per-type breakdown dict so the engine can
        #    populate `isa_draw` / `gia_draw` / `cash_draw`).
        #
        #    Pre-retirement gate: drawdown is a post-retirement
        #    activity. While at least one partner is still working,
        #    the engine MUST NOT touch retirement assets (DC / ISA /
        #    GIA / Cash) for drawdown — even if `income_until_retirement`
        #    has been set to £0 and the household is in cash-flow
        #    deficit on paper. The Timeline page's annual-funding-sources
        #    stacked bar would otherwise show DC draw / ISA draw bars
        #    before the user has even retired, which is both
        #    semantically wrong (you don't normally draw your pension
        #    while still working) AND misleading (it hides the real
        #    planning problem of an under-funded pre-retirement cash
        #    flow). The Income line will sit BELOW `spending +
        #    mortgage_paid` in pre-retirement deficit years — that's
        #    the correct visual signal that the plan needs an earned
        #    income boost, longer working, or a spending cut. Post-
        #    retirement (`any_retired` flips True) the gate opens and
        #    drawdown runs as before. Locked down by
        #    `TestDrawdownSuppressedPreRetirement` in tests/test_drawdown.py.
        #
        #    Mortgage caveat: step 4 (above) reduces
        #    `mortgage.outstanding` regardless of whether the
        #    household has the cash, so pre-retirement deficit years
        #    CAN still show `net_worth` going UP by `mortgage_paid`
        #    even with `income == 0` IF the cash_buffer household-
        #    level flag is OFF (the model's pre-existing convention
        #    that the household magically has the cash to service
        #    the mortgage as scheduled). When `cash_buffer=True`,
        #    the pre-retirement `elif cash_buffer_enabled and income <
        #    total_need:` branch (below) routes both the mortgage
        #    shortfall AND the lifestyle shortfall through
        #    `drawdown_from_assets` — Cash → ISA → GIA — restoring
        #    correct net-worth accounting (Cash dip exactly offsets
        #    debt reduction). PCLS / UFPLS / DB drawdown remain
        #    strictly retired-gated. See `models/household.py` for the
        #    field-level docs and `tests/test_cash_buffer.py` for
        #    the locked-down regression contract.
        # -------------------------
        mortgage_in_spending = bool(
            household.mortgage and household.mortgage.include_in_spending
        )
        total_need = spending + (
            0.0 if mortgage_in_spending else mortgage_paid
        )
        any_retired = household.person1.is_retired(year)
        if not single_retiree:
            any_retired = any_retired or household.person2.is_retired(year)
        # `Household.cash_buffer` is opt-in (defaults to False). The
        # `getattr(..., False)` defensive read means older saved
        # household_data.json files without the key construct
        # cleanly: `Household(**legacy_data)` skips the field at the
        # dataclass level, and the engine reads False for them so the
        # pre-retirement asset drawdown `elif` below cannot fire.
        cash_buffer_enabled = bool(
            getattr(household, "cash_buffer", False)
        )
        if any_retired and income < total_need:
            # User-configurable wrapper priority. The user can move
            # "Pension" to the tail of the list to defer DC draws
            # (preserves outside-IHT inheritance) or drop it entirely
            # to live purely off Cash / ISA / GIA. The default
            # `["Pension", "Cash", "ISA", "GIA"]` (from the Household
            # dataclass default + `_resolve_priority_list` fallback)
            # preserves the pre-PR engine's behaviour byte-for-byte
            # for legacy plans that never touched the new widget.
            priority = _resolve_priority_list(household)
            # Cumulative per-spouse taxable UFPLS across all
            # Pension calls in the multi-pass waterfall. Each
            # `_draw_pension_for_amount` call returns the
            # incremental p1/p2 taxable for THIS call. We sum
            # them here, then do ONE correct tax recompute after
            # the waterfall — prevents later-pass incremental-
            # amount tax results (often £0 when below PA) from
            # overwriting earlier-pass correct tax.
            cumulative_p1_taxable = 0.0
            cumulative_p2_taxable = 0.0
            # Re-zero the year-loop-top dict (the waterfall below
            # accumulates into it via per_source[wrapper] += ...).
            per_source["Cash"] = per_source["ISA"] = per_source["GIA"] = 0.0

            # Cumulative-tax income recompute. The per-call
            # `_draw_pension_for_amount` take-home UNDERSTATES the
            # tax on later passes' slices (each slice is taxed against
            # the base `*_gross` as if the earlier slices never
            # consumed the personal allowance / basic-rate band), so
            # a termination check based on the per-call sums stops
            # the loop ~£170-£1,200 short of the true post-tax
            # target (e.g. the £514 gap at ages 64-66 on the user's
            # £38k Quick Estimate plan — reported as "why does the
            # bar fall short of the spending line?"). Recomputing
            # `income` from the CUMULATIVE per-spouse taxable
            # drawdown keeps the waterfall drawing until the
            # household actually receives `total_need` after tax.
            def _cumulative_take_home() -> float:
                p1t = uk_income_tax(
                    p1_gross, taxable_drawdown=cumulative_p1_taxable
                )
                p2t = uk_income_tax(
                    p2_gross, taxable_drawdown=cumulative_p2_taxable
                )
                take_home = taxable_draw - (
                    max(0.0, p1t["tax"] - p1_tax_result_top["tax"])
                    + max(0.0, p2t["tax"] - p2_tax_result_top["tax"])
                )
                return (
                    p1_tax_result_top["net"]
                    + p2_tax_result_top["net"]
                    - p1_ni - p2_ni
                    + tax_free_draw + take_home
                    + per_source["Cash"] + per_source["ISA"]
                    + per_source["GIA"]
                )

            # Multi-pass waterfall: re-iterate the priority list
            # until either the year-end need is met OR a pass made
            # no progress (defensive termination cap). The original
            # single-pass loop left small residuals unfilled when
            # e.g. the user's ISA drained mid-retirement BEFORE
            # Pension could fully cover the deficit — Pension still
            # had plenty of DC pot but the engine never asked for
            # more. Each re-pass drains whichever wrapper still has
            # capacity; a cap of `len(priority) + 2` passes (max 6
            # for the default 4-wrapper list) plus a 1e-6 no-progress
            # detector guarantees termination on both healthy plans
            # and structurally-underfunded ones.
            #
            # PCLS semantics on the SECOND Pension call within one
            # year: `_draw_pension_for_amount` advances `pcls_taken`
            # on the first call (up to the 25%-gross preference).
            # On the second call `p1_remaining + p2_remaining == 0`
            # so 100% of the residual draw is UFPLS taxable — the
            # correct per-year PCLS cap (no doubled-up tax-free).
            # Per-spouse tax recompute uses the unchanged `*_top`
            # baseline, so the second call's `tax_on_ufpls` correctly
            # reflects ONLY the additional UFPLS from that call.
            # Pass cap: the waterfall converges geometrically — each
            # Pension pass draws the residual gross but nets only ~80%
            # of it after tax, so the remaining shortfall shrinks by
            # roughly the marginal rate each pass. `len(priority) + 2`
            # (6 for the default list) truncates that tail at ~£1 on a
            # £38k need (the user's 37,999.18 vs 38,000 on the Quick
            # Estimate chart). 24 passes drives the residual below
            # 1e-6 before the no-progress detector fires.
            max_passes = 24
            for _pass in range(max_passes):
                if income >= total_need:
                    break
                income_before_this_pass = income
                # Walk the priority list IN ORDER. Each iteration
                # within a pass handles ONE wrapper (Pension or one
                # asset class), drawing up to `remaining =
                # total_need - income` from that wrapper. The inner
                # loop breaks as soon as `income >= total_need`, so
                # a wrapper that's NOT first in the list only fires
                # for the RESIDUAL after the earlier wrappers on
                # this pass — achieving the "defer pension until
                # assets exhausted" semantic the user-facing caption
                # promises. Pension's cap-at-DC / PCLS preference /
                # per-spouse tax recompute logic stays inside
                # `_draw_pension_for_amount` so the fire-ordering and
                # tax math are co-located.
                for wrapper in priority:
                    if income >= total_need:
                        break
                    remaining = total_need - income
                    if wrapper == "Pension":
                        (
                            tax_free_draw_call,
                            taxable_draw_call,
                            ufpls_take_home_call,
                            p1_taxable_call,
                            p2_taxable_call,
                            _p1_tax_inc,
                            _p2_tax_inc,
                        ) = _draw_pension_for_amount(
                            household,
                            remaining,
                            p1_gross,
                            p2_gross,
                            p1_tax_result_top,
                            p2_tax_result_top,
                        )
                        # ACCUMULATE across multiple Pension calls
                        # (rather than overwriting). First call
                        # consumes up to 25%-gross PCLS; on the
                        # second call `pcls_remaining == 0` so the
                        # residual draw is 100% taxable. Both calls'
                        # contributions roll into the per-year series
                        # so the Quick Estimate / Timeline stacked bar
                        # reports the total Asset Drawdown that
                        # actually arrived in the household's bank.
                        tax_free_draw += tax_free_draw_call
                        taxable_draw += taxable_draw_call
                        ufpls_take_home += ufpls_take_home_call
                        cumulative_p1_taxable += p1_taxable_call
                        cumulative_p2_taxable += p2_taxable_call
                        # Recompute `income` from the CUMULATIVE
                        # per-spouse taxable drawdown (see
                        # `_cumulative_take_home` above) instead of
                        # adding this call's per-call take-home, so
                        # the waterfall's termination check reflects
                        # the true post-tax position and keeps
                        # drawing until the target is actually met
                        # rather than stopping ~£500 short.
                        income = _cumulative_take_home()
                    elif wrapper in ("Cash", "ISA", "GIA"):
                        # Single-class drain — matched pool
                        # semantics (multiple Cash entries drain in
                        # the order they appear in the assets list).
                        # Mutates assets in place so cumulative draws
                        # roll forward across years. Subsequent passes
                        # call `drain_single_asset_class` again on the
                        # now-£0 class, returning 0 immediately and
                        # contributing nothing to `income` — triggers
                        # the no-progress detector on the next pass.
                        withdrawn, breakdown = drain_single_asset_class(
                            household.assets, remaining, wrapper
                        )
                        per_source[wrapper] += breakdown.get(
                            wrapper, 0.0
                        )
                        income += withdrawn
                # No progress this pass — every wrapper hit a cap
                # (PCLS exhausted, asset class at £0, DC pot empty).
                # Stop iterating to avoid hanging on a structurally-
                # underfunded plan. 1e-6 epsilon is conservative vs
                # FP rounding noise from the per-spouse tax recompute
                # inside `_draw_pension_for_amount`.
                if income - income_before_this_pass < 1e-6:
                    break

            # ---- Final tax recompute with CUMULATIVE UFPLS ----
            # The multi-pass waterfall above calls Pension
            # incrementally; each call's tax-on-UFPLS is correct
            # for that call's SLICE but `uk_income_tax(...,
            # taxable_drawdown=slice)` doesn't see the earlier-
            # pass taxable drawdown. Recomputing p1/p2 tax here
            # with the CUMULATIVE per-spouse taxable drawdown
            # from ALL Pension calls ensures `household_tax` and
            # `household_take_home` (computed after this block)
            # correctly capture the full-year income+UFPLS tax
            # liability — not just the last incremental slice.
            #
            # Also recompute `ufpls_take_home` and `income` with
            # cumulative tax, because UK income tax is progressive:
            #   tax(p1_gross + slice1) + tax(p1_gross + slice2)
            #   ≠ tax(p1_gross + slice1 + slice2)
            # The per-call accumulation used inside the multi-pass
            # loop is close enough for the termination condition
            # (~£500 error on £37k need), but the final values
            # written to `results["income"]` and the UFPLS series
            # must use the corrected cumulative tax.
            p1_tax_result = uk_income_tax(
                p1_gross, taxable_drawdown=cumulative_p1_taxable
            )
            p2_tax_result = uk_income_tax(
                p2_gross, taxable_drawdown=cumulative_p2_taxable
            )
            ufpls_take_home = taxable_draw - (
                max(0.0, p1_tax_result["tax"] - p1_tax_result_top["tax"])
                + max(0.0, p2_tax_result["tax"] - p2_tax_result_top["tax"])
            )
            income = (
                p1_tax_result_top["net"] + p2_tax_result_top["net"]
                - p1_ni - p2_ni
                + tax_free_draw + ufpls_take_home
                + per_source["Cash"] + per_source["ISA"]
                + per_source["GIA"]
            )

            results["tax_free_income"].append(tax_free_draw)
            results["ufpls_taxable_net"].append(ufpls_take_home)
            results["ufpls_taxable_gross"].append(taxable_draw)
            results["isa_draw"].append(per_source["ISA"])
            results["gia_draw"].append(per_source["GIA"])
            results["cash_draw"].append(per_source["Cash"])
        elif cash_buffer_enabled and income < total_need:
            # Pre-retirement asset-only drawdown under cash_buffer
            # mode. Pension waterfall (PCLS / UFPLS / DB) stays
            # strictly retired-gated under the original `if
            # any_retired` block above — this branch ONLY routes
            # pre-retirement cash-flow deficits through the
            # user-configurable priority list so the household's
            # liquid savings cover both the mortgage shortfall and
            # any lifestyle shortfall. "Pension" is stripped from
            # the list here because the DC pot is not drawable
            # pre-retirement (HMRC's UFPLS / PCLS rules require
            # crystallisation events, which only fire
            # post-retirement; pre-retirement DC drawdown is also
            # typically a tax/penalty disaster). The remaining
            # non-Pension wrappers (Cash / ISA / GIA) drain in
            # the user's relative order — so an ISA-first user who
            # listed `["ISA", "GIA", "Pension", "Cash"]` on Page 4
            # sees ISA drained first here too (the "Pension"
            # entry is silently skipped, the rest keep their
            # relative order). Net-worth accounting is correctly
            # restored: the per-class drain exactly offsets the
            # step-4 `mortgage.outstanding` reduction so
            # `net_worth` no longer phantom-uplifts by
            # `mortgage_paid`. The on-chart `Cash Draw` / `ISA
            # Draw` / `GIA Draw` stacked-bar segments render
            # pre-retirement dips automatically — no extra
            # funding-source chart work needed. Post-retirement
            # behaviour is unchanged because the original `if
            # any_retired` block continues to handle that path.
            priority = _resolve_priority_list(household)
            required = total_need - income
            # Re-zero the year-loop-top dict.
            per_source["Cash"] = per_source["ISA"] = per_source["GIA"] = 0.0
            for asset_class in priority:
                if asset_class == "Pension":
                    # DC is not drawable pre-retirement — silently
                    # skip. See block docstring for HMRC rationale.
                    continue
                if required <= 0:
                    break
                withdrawn, breakdown = drain_single_asset_class(
                    household.assets, required, asset_class
                )
                required -= withdrawn
                per_source[asset_class] = breakdown.get(asset_class, 0.0)
            income += (total_need - income) - max(0.0, required)
            # Equivalent to: `income += (total_need - income - required)`
            # which simplifies to `income = total_need - required` (a
            # direct wallet-fill to the household's remaining need
            # after the asset walk). The `max(0.0, required)` clamps
            # any FP noise on the post-drain residual to a
            # non-negative number so the wallet-fill never
            # over-shoots the original `total_need` (a regression
            # that would otherwise inflate `income` on years when
            # `required` rounded to a slightly-negative FP value).
            results["tax_free_income"].append(0)
            results["ufpls_taxable_net"].append(0.0)
            results["ufpls_taxable_gross"].append(0.0)
            results["isa_draw"].append(per_source["ISA"])
            results["gia_draw"].append(per_source["GIA"])
            results["cash_draw"].append(per_source["Cash"])
        else:
            # No drawdown needed this year — every per-source series
            # advances by 0 so all series stay aligned on the year axis
            # for the Timeline stacked bar. Reached when EITHER
            # `income >= total_need` (no deficit), OR
            # `cash_buffer_enabled` is False (legacy behaviour
            # pre-retirement deficit simply surfaces on the chart
            # as `Income < Spending`), OR `cash_buffer_enabled` is
            # True but the household has retired (handled by the
            # earlier `if any_retired` branch instead).
            results["tax_free_income"].append(0)
            results["ufpls_taxable_net"].append(0.0)
            results["ufpls_taxable_gross"].append(0.0)
            results["isa_draw"].append(0.0)
            results["gia_draw"].append(0.0)
            results["cash_draw"].append(0.0)

        # Defensive clamp — the chart on the Timeline page should never
        # display a negative take-home even if some unforeseen tax-on-
        # UFPLS interaction compressed the math below zero. The `income`
        # series is a wallet-fill figure; net_worth is the asset
        # depletion figure and is allowed to go negative in tests.
        income = max(0.0, income)

        # Tax / net_income / effective_rate are recorded AFTER the drawdown
        # block so they reflect any UFPLS taxable drawdown that happened this
        # year. Summed across both spouses — UK taxes each partner
        # separately — see the per-spouse tax calls above. When no drawdown
        # was needed, the top-of-year `p1_tax_result` / `p2_tax_result` are
        # still in scope (Python has no block scope) and are used here, so
        # the "tax on this year's gross" line stays correct in every case.
        household_tax = p1_tax_result["tax"] + p2_tax_result["tax"]
        household_ni = p1_ni + p2_ni
        household_take_home = (
            p1_tax_result["net"] + p2_tax_result["net"] - household_ni
        )
        results["tax"].append(household_tax)
        results["ni"].append(household_ni)
        # PCLS is tax-free by construction — `uk_income_tax` only sees
        # the taxable UFPLS portion, so `household_take_home` (which is
        # `p1.net + p2.net - ni`) misses the tax-free slice. Cash / ISA /
        # GIA draws happen AFTER the Pension tax recompute and are also
        # invisible to `p1_tax_result` / `p2_tax_result`. Adding BOTH
        # `tax_free_draw` AND the per-source asset draws reunites all
        # funding streams so the Tax View's "Net Income" column matches
        # the household's actual wallet fill (`income`).
        total_asset_draws = (
            per_source["Cash"] + per_source["ISA"] + per_source["GIA"]
        )
        results["net_income"].append(
            household_take_home + tax_free_draw + total_asset_draws
        )
        # Effective Tax Rate uses TOTAL income including drawdown
        # (not just gross_income which excludes UFPLS). Without
        # `taxable_draw + tax_free_draw` in the denominator, the
        # ETR column in the Tax View would overstate the effective
        # rate during drawdown years — e.g. "£5,694 tax on £11,600
        # gross" reads as 49% when the actual rate on total income
        # including UFPLS is much lower.
        total_income_for_etr = (
            gross_income + taxable_draw + tax_free_draw
        )
        results["effective_tax_rate"].append(
            household_tax / total_income_for_etr
            if total_income_for_etr > 0 else 0.0
        )

        # Per-spouse breakdowns — useful for the AI Analysis page to quote
        # spousal tax / NI figures when explaining the plan, and for any
        # future "what if we taxed jointly" comparison view.
        results["p1_gross_income"].append(p1_gross)
        results["p2_gross_income"].append(p2_gross)
        results["p1_tax"].append(p1_tax_result["tax"])
        results["p2_tax"].append(p2_tax_result["tax"])
        results["p1_ni"].append(p1_ni)
        results["p2_ni"].append(p2_ni)

        # -------------------------
        # 8. Net Worth
        # -------------------------
        net_worth = sum(a.value for a in household.assets) + household.person1.dc_pot
        if not single_retiree:
            net_worth += household.person2.dc_pot

        if household.mortgage:
            net_worth -= household.mortgage.outstanding

        # -------------------------
        # 9. Save results
        # -------------------------
        results["net_worth"].append(net_worth)
        results["income"].append(income)
        results["spending"].append(spending)

        # Asset breakdown
        isa = sum(a.value for a in household.assets if a.asset_type == "ISA")
        gia = sum(a.value for a in household.assets if a.asset_type == "GIA")
        cash = sum(a.value for a in household.assets if a.asset_type == "Cash")
        prop = sum(a.value for a in household.assets if a.asset_type == "Property")

        results["isa_value"].append(isa)
        results["gia_value"].append(gia)
        results["cash_value"].append(cash)
        results["property_value"].append(prop)

        if household.mortgage:
            results["mortgage_balance"].append(household.mortgage.outstanding)
        else:
            results["mortgage_balance"].append(0)

        results["mortgage_payment"].append(mortgage_paid)

        total_dc_pot = household.person1.dc_pot
        if not single_retiree:
            total_dc_pot += household.person2.dc_pot
        results["dc_pot"].append(total_dc_pot)

        results["pension_income"].append(pension_income)
        results["earned_income"].append(p1_earned_this_year + p2_earned_this_year)
        # Per-source funding breakdown that drives the Timeline stacked
        # bar. `db_payout` + `state_payout` reproduces `pension_income`
        # per year as a split into DB pension and State Pension
        # segments, so the chart can show each as its own coloured
        # slice. Both `p1_db_income_year` and `p1_sp_year` are in scope
        # here from step 1; pre-`draw_age` years contribute 0 for DB
        # because of the explicit initialisation above.
        results["db_payout"].append(p1_db_income_year + p2_db_income_year)
        results["state_payout"].append(p1_sp_year + p2_sp_year)

    return results
