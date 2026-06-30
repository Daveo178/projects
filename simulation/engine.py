from .state_pension import state_pension_income
from .drawdown import drawdown_from_assets


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
    simulated year. When `monthly_contrib_pct > 0` the contribution tracks
    the (wage-inflation indexed) annual income (`pct * income / 12`); this
    is the new model. Otherwise we fall back to the legacy absolute
    `monthly_contrib` / 12 figure for backwards compatibility with
    household_data.json files that pre-date the % slider.
    """
    if person.monthly_contrib_pct > 0:
        return current_indexed_income * person.monthly_contrib_pct / 12
    return person.monthly_contrib / 12


def _indexed_earned_income(person, year):
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
    """
    if person.is_retired(year):
        return 0.0
    return person.income_until_retirement * (1 + person.income_growth_rate) ** year


def run_simulation(household, years=45):
    """
    Runs a year-by-year simulation of the household finances.
    Returns a dictionary of results for charts and AI analysis.
    """

    results = {
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
        # drop the explicit `is_retired` branch here.
        p1_earned_this_year = _indexed_earned_income(household.person1, year)
        p1_sp_year = state_pension_income(household.person1, year)
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
        # year — 0 when the partner has not yet reached `draw_age`.
        p1_db_income_year = 0.0
        if household.person1.is_db_active(year):
            p1_db_years_active = max(
                0,
                (household.person1.age + year) - household.person1.draw_age,
            )
            p1_db_income_year = (
                household.person1.db_income
                * (1 + household.person1.db_growth_rate) ** p1_db_years_active
            )
            p1_gross += p1_db_income_year
            pension_income += p1_db_income_year

        # Person 2 — same per-spouse accounting as Person 1 above.
        p2_db_income_year = 0.0
        p2_earned_this_year = _indexed_earned_income(household.person2, year)
        p2_sp_year = state_pension_income(household.person2, year)
        pension_income += p2_sp_year
        p2_gross = p2_earned_this_year + p2_sp_year
        if household.person2.is_db_active(year):
            p2_db_years_active = max(
                0,
                (household.person2.age + year) - household.person2.draw_age,
            )
            p2_db_income_year = (
                household.person2.db_income
                * (1 + household.person2.db_growth_rate) ** p2_db_years_active
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

        if household.person2.is_retired(year) and household.person2.pcls_available == 0:
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
        p2_M = _monthly_dc_contrib(household.person2, p2_earned_this_year)

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

        household.person1.dc_pot = _dc_monthly_compound(
            household.person1.dc_pot,
            household.person1.dc_growth_rate,
            p1_M_for_year,
            fraction=p1_fraction,
        )
        household.person2.dc_pot = _dc_monthly_compound(
            household.person2.dc_pot,
            household.person2.dc_growth_rate,
            p2_M_for_year,
            fraction=p2_fraction,
        )

        # -------------------------
        # 2b. Asset contributions — keep paying into ISA/GIA/Cash while
        # at least one person is still working. Stop once both partners
        # have retired (joint household convention).
        # -------------------------
        if not (household.person1.is_retired(year) and household.person2.is_retired(year)):
            for asset in household.assets:
                if asset.contribution_until_retirement > 0:
                    asset.value += asset.contribution_until_retirement

        # -------------------------
        # 3. Asset Growth
        # -------------------------
        for asset in household.assets:
            asset.grow()

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
        triggered = []

        if household.events:
            for event in household.events:
                if event.year == year:

                    # Standard life event
                    if hasattr(event, "amount"):
                        triggered.append(event.description)
                        for asset in household.assets:
                            if asset.asset_type == "Cash":
                                asset.value += event.amount
                                break

                    # Downsizing event
                    if hasattr(event, "sell_property_value"):
                        triggered.append("Downsizing")

                        # 1. Sell current property
                        for asset in household.assets:
                            if asset.asset_type == "Property":
                                sale_proceeds = event.sell_property_value
                                asset.value = event.new_property_value
                                break

                        # 2. Add sale proceeds to cash
                        for asset in household.assets:
                            if asset.asset_type == "Cash":
                                asset.value += sale_proceeds
                                break

                        # 3. Clear mortgage if present
                        if household.mortgage:
                            household.mortgage.outstanding = 0

        results["events_triggered"].append(triggered)
        results["gross_income"].append(gross_income)

        # -------------------------
        # 6. Spending (with strategy)
        # -------------------------
        strategy = getattr(household, "drawdown_strategy", "Fixed")

        if strategy == "Fixed":
            spending = household.spending_target

        elif strategy == "Inflation-adjusted":
            spending = household.spending_target * ((1 + 0.025) ** year)

        elif strategy == "Safe Withdrawal (4%)":
            total_assets = (
                sum(a.value for a in household.assets)
                + household.person1.dc_pot
                + household.person2.dc_pot
            )
            spending = total_assets * 0.04

        else:
            spending = household.spending_target

        # -------------------------
        # 7. Drawdown if needed (phantom-safe UFPLS + per-source split)
        #    Total outgoings = lifestyle spending + mortgage payment this year.
        #    Spending stays a pure lifestyle figure for plotting/Explain;
        #    mortgage payment is tracked separately in `results["mortgage_payment"]`.
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
        # -------------------------
        total_need = spending + mortgage_paid
        if income < total_need:
            required = total_need - income

            # ----- PCLS (tax-free UFPLS portion) ---------------------
            p1_remaining = (
                household.person1.pcls_available
                - household.person1.pcls_taken
            )
            p2_remaining = (
                household.person2.pcls_available
                - household.person2.pcls_taken
            )
            max_tax_free_this_year = required * 0.25
            tax_free_draw_requested = min(
                max_tax_free_this_year,
                max(0, p1_remaining + p2_remaining),
            )
            taxable_draw_requested = max(
                0, required - tax_free_draw_requested
            )
            ufpls_requested = (
                tax_free_draw_requested + taxable_draw_requested
            )

            # ----- Cap UFPLS at ACTUAL DC pot — the core fix ---------
            # Without this, the engine charged UFPLS income tax on
            # `taxable_draw_requested` £ even when DC was empty, which
            #   (a) reduced the post-tax income line on phantom draws,
            #   (b) created the double-PA illusion biasing the line UP
            #       once total_dc hit zero (see block docstring).
            total_dc_at_start = (
                household.person1.dc_pot + household.person2.dc_pot
            )
            actual_ufpls = min(ufpls_requested, total_dc_at_start)

            # Pro-rate PCLS / taxable onto the cap so the 25%-PCLS
            # preference is preserved as much as possible on a partial
            # draw. When nothing was capped (full draw possible), the
            # scaling factor is 1 and the requested values pass through
            # unchanged.
            if ufpls_requested > 0 and actual_ufpls < ufpls_requested:
                scaling = actual_ufpls / ufpls_requested
                tax_free_draw = tax_free_draw_requested * scaling
                taxable_draw = taxable_draw_requested * scaling
            else:
                tax_free_draw = tax_free_draw_requested
                taxable_draw = taxable_draw_requested

            # ----- Per-spouse share of the ACTUAL draw ----------------
            # Each partner pays tax on their own UFPLS drawdown and the
            # engine reduces their pot in the same proportion — HMRC's
            # rule is the tax follows the pension that crystallised the
            # UFPLS. Zero shares when there is nothing to draw from.
            if total_dc_at_start > 0 and actual_ufpls > 0:
                p1_share = household.person1.dc_pot / total_dc_at_start
                p2_share = household.person2.dc_pot / total_dc_at_start
                household.person1.dc_pot -= actual_ufpls * p1_share
                household.person2.dc_pot -= actual_ufpls * p2_share
                p1_taxable_taken = taxable_draw * p1_share
                p2_taxable_taken = taxable_draw * p2_share
            else:
                p1_taxable_taken = 0.0
                p2_taxable_taken = 0.0

            # ----- PCLS consumption bookkeeping -----------------------
            # `pcls_taken` advances by the (pro-rated) tax-free amount;
            # P1's allowance is used first, then P2's. `pcls_available`
            # is fixed at retirement (see step 1b above).
            if tax_free_draw > 0:
                if p1_remaining >= tax_free_draw:
                    household.person1.pcls_taken += tax_free_draw
                else:
                    household.person1.pcls_taken += max(0, p1_remaining)
                    household.person2.pcls_taken += max(
                        0, tax_free_draw - p1_remaining
                    )

            # ----- Tax recompute with ACTUAL UFPLS draw ---------------
            from .tax import uk_income_tax
            p1_tax_result = uk_income_tax(
                p1_gross, taxable_drawdown=p1_taxable_taken
            )
            p2_tax_result = uk_income_tax(
                p2_gross, taxable_drawdown=p2_taxable_taken
            )

            # Take-home contribution from UFPLS taxable portion = gross
            # draw minus the additional income tax it triggered vs the
            # top-of-year no-UFPLS baseline captured as `*_top`. This is
            # what populates the queued UFPLS segment of the stacked bar.
            p1_tax_on_ufpls = max(
                0.0, p1_tax_result["tax"] - p1_tax_result_top["tax"]
            )
            p2_tax_on_ufpls = max(
                0.0, p2_tax_result["tax"] - p2_tax_result_top["tax"]
            )
            ufpls_take_home = (
                p1_taxable_taken + p2_taxable_taken
                - p1_tax_on_ufpls - p2_tax_on_ufpls
            )

            # Reconstitute household income from REAL sources only —
            # no phantom UFPLS, no 50/50 fabrication when DC empty.
            # NI unchanged from top-of-year because it only applies to
            # earned salary (DB / SP / UFPLS are pension income).
            income = (
                p1_tax_result_top["net"]
                + p2_tax_result_top["net"]
                + tax_free_draw
                + ufpls_take_home
                - p1_ni - p2_ni
            )

            results["tax_free_income"].append(tax_free_draw)
            results["ufpls_taxable_net"].append(ufpls_take_home)
            results["ufpls_taxable_gross"].append(taxable_draw)

            # ----- Cash/ISA/GIA waterfall for residual shortfall -----
            # Use `total_need` (lifestyle + mortgage), not just spending,
            # so the mortgage payment is still covered if UFPLS alone
            # bridges the lifestyle need but falls short of the
            # combined outgoings. `drawdown_from_assets` now returns a
            # per-type breakdown dict so each component flows into its
            # own result series and the stacked bar can split ISA / GIA
            # / Cash visually.
            if income < total_need:
                remaining_needed = total_need - income
                withdrawn, breakdown = drawdown_from_assets(
                    household.assets, remaining_needed
                )
                income += withdrawn
                results["isa_draw"].append(breakdown.get("ISA", 0.0))
                results["gia_draw"].append(breakdown.get("GIA", 0.0))
                results["cash_draw"].append(breakdown.get("Cash", 0.0))
            else:
                results["isa_draw"].append(0.0)
                results["gia_draw"].append(0.0)
                results["cash_draw"].append(0.0)
        else:
            # No drawdown needed this year — every per-source series
            # advances by 0 so all series stay aligned on the year axis
            # for the Timeline stacked bar.
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
        results["net_income"].append(household_take_home)
        results["effective_tax_rate"].append(
            household_tax / gross_income if gross_income > 0 else 0.0
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
        net_worth = (
            sum(a.value for a in household.assets)
            + household.person1.dc_pot
            + household.person2.dc_pot
        )

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

        results["dc_pot"].append(
            household.person1.dc_pot + household.person2.dc_pot
        )

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
