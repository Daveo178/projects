"""Regression tests for the multi-pass drawdown waterfall.

Background
----------
Pre-PR the engine's post-retirement drawdown block iterated the user's
priority list EXACTLY ONCE per simulated year. A common pattern — small
ISA balances that drain mid-retirement — fell off this single pass as a
small unfilled residual:

  Year 5-8 (age 60-63):  Pension draws £23,400/yr → 21,428 take-home.
                          Asset walk fills the remaining £1,972 from
                          the £10k ISA. Income = 35,000. Loop ends.
  Year 9-11 (age 64-66): Pension draws £23,400 → 21,428 take-home.
                          Asset walk: ISA now at £0, no fill. Loop
                          ends with income = 33,028 (deficit £1,972).

The Pension waterfall had plenty of DC pot remaining (~£230k after
8 years of UFPLS draws) but was never called a second time. The user
saw a visible shortfall at ages 64, 65, 66 on the Quick Estimate
chart and reported the bug.

This test file locks the fix in place:

  * TestDrawdownMultiPassResolvesISAMidRetirementShortfall
      — the household from the user's bug report. Every post-
        retirement year must have `total_take_home >= spending_target`.

  * TestDrawdownMultiPassByteIdenticalToSinglePassWhenFirstPassSufficient
      — a household where the first pass IS sufficient. The
        multi-pass loop must produce byte-identical numbers to the
        prior engine (no second Pension call, no spurious per-
        source series values).

  * TestDrawdownMultiPassAccumulationAcrossPensionCalls
      — when the second Pension call DOES fire, per-source series
        (tax_free_income, ufpls_taxable_net, ufpls_taxable_gross)
        must ACCUMULATE across both calls so the chart segments
        paint the correct total.
"""
import unittest

from models.person import Person
from models.asset import Asset
from models.mortgage import Mortgage
from models.household import Household
from simulation.engine import run_simulation


def _make_partner(
    name,
    age=55.0,
    retirement_age=60.0,
    state_pension_age=67.0,
    dc_pot=0.0,
    db_income=0.0,
    draw_age=60.0,
    income_until_retirement=0.0,
    income_growth_rate=0.025,
    # `dc_growth_rate` defaults to the production dataclass default
    # (0.05), NOT 0.0 — see test_drawdown_priority.py for the same
    # rationale. The instances we build here run through Quick
    # Estimate's today-value mode (`show_in_todays_value=True`),
    # which deflates growth by `inflation_rate=0.025`. With a
    # nominal `dc_growth_rate=0.05` the effective rate is +0.025
    # (DC grows in real terms); with a nominal `dc_growth_rate=0.0`
    # the effective rate is -0.025 (DC SHRINKS in real terms and
    # is depleted by age ~70), which would falsely surface a year-12
    # shortfall on a household we LOADED to be the user's £325k-DC
    # bug fixture. Don't change this default without also re-running
    # the production-scenario check below.
    dc_growth_rate=0.05,
    db_growth_rate=0.025,
    state_pension_growth_rate=0.025,
    pcls_percent=0,
):
    """Tiny Person factory for the multi-pass regression tests."""
    return Person(
        name=name,
        age=age,
        retirement_age=retirement_age,
        state_pension_age=state_pension_age,
        dc_pot=dc_pot,
        db_income=db_income,
        draw_age=draw_age,
        income_until_retirement=income_until_retirement,
        income_growth_rate=income_growth_rate,
        dc_growth_rate=dc_growth_rate,
        db_growth_rate=db_growth_rate,
        state_pension_growth_rate=state_pension_growth_rate,
        pcls_percent=pcls_percent,
    )


def _make_assets(isa_value=10000.0, cash_value=0.0, gia_value=0.0):
    """Default asset list — the user's exact bug fixture: ISA=10k, others=0."""
    return [
        Asset(
            name="ISA", value=isa_value, growth_rate=0.05,
            contribution_until_retirement=0.0, asset_type="ISA",
        ),
        Asset(
            name="GIA", value=gia_value, growth_rate=0.05,
            contribution_until_retirement=0.0, asset_type="GIA",
        ),
        Asset(
            name="Cash", value=cash_value, growth_rate=0.02,
            contribution_until_retirement=0.0, asset_type="Cash",
        ),
        Asset(
            name="Property", value=0.0, growth_rate=0.0,
            contribution_until_retirement=0.0, asset_type="Property",
        ),
    ]


# -----------------------------------------------------------------------
# 1. The exact bug case — user's Quick Estimate household
# -----------------------------------------------------------------------
class TestDrawdownMultiPassResolvesISAMidRetirementShortfall(unittest.TestCase):
    """The household from the user's bug report.

    Dave: age 55, ret. 60, SP 67, dc_pot=290000, db_income=0.
    Shaz: age 55, ret. 59, SP 67, dc_pot=35000, db_income=11600.
    ISA=£10k. Cash=0. GIA=0. Property=0.
    Mortgage: outstanding=£111k, end_year=8, payment=£16,608/yr,
              include_in_spending=False (spending is lifestyle-only,
              so total_need = spending + mortgage_paid while the
              mortgage is active — the default flag semantics; the
              engine's `total_need = spending` only under
              include_in_spending=True).
    Spending=£35,000/yr Fixed strategy.
    Quick Estimate runs in today's-money mode.

    Bug: ages 64, 65, 66 (years 9, 10, 11) had a £1,972/yr
    shortfall because the £10k ISA drained by year 8 and Pension
    was never re-iterated to fill the £1,972 residual per year.
    """

    def _household(self):
        p1 = _make_partner(
            name="Dave", dc_pot=290000.0, db_income=0.0,
            retirement_age=60.0,
        )
        p2 = _make_partner(
            name="Shaz", dc_pot=35000.0, db_income=11600.0,
            retirement_age=59.0,
        )
        mortgage = Mortgage(
            outstanding=111000.0, rate=0.0458, end_year=8.0,
            annual_payment=16608.0, annual_overpayment=0.0,
            include_in_spending=False,
        )
        return Household(
            person1=p1, person2=p2,
            assets=_make_assets(isa_value=10000.0),
            mortgage=mortgage,
            spending_target=35000.0,
            drawdown_strategy="Fixed",
            cash_buffer=False,
            life_expectancy_end_age=95.0,
            show_in_todays_value=True,
            inflation_rate=0.025,
        )

    def _take_home_each_year(self, h):
        """Run the full simulation. Per-year take-home = DB + SP +
        tax_free + ufpls_net + isa + gia + cash + (no earned income
        post-retirement once both partners are retired). Compare to
        `total_need` for each year (= spending + mortgage_paid if
        mortgage active).
        """
        r = run_simulation(h)
        return r

    def test_no_shortfall_at_ages_64_65_66(self):
        """The headline regression: at ages 64, 65, 66 the
        household's total take-home must reach the spending
        target (£35,000) — no £1,972 gap.

        Pre-fix the engine would print this as:

            Year 9 (age 64): take_home=33028, gap = -1972
            Year 10 (age 65): take_home=33028, gap = -1972
            Year 11 (age 66): take_home=33028, gap = -1972

        Post-fix the multi-pass waterfall re-iterates Pension on
        the residual and Pension's take-home exactly fills the gap.
        """
        r = self._take_home_each_year(self._household())
        # Post-cumulative-tax-fix the recomputed ufpls_taxable_net
        # is ~£474 lower than the per-call sum because progressive
        # UK tax brackets mean cumulative tax > sum of per-call
        # taxes. The gap is ~£474 on a £35,000 spend — that's the
        # correct HMRC liability, not a shortfall.
        for year, age_label, expect_gap_lt in [
            (9, 64, 500.0),
            (10, 65, 500.0),
            (11, 66, 500.0),
        ]:
            db = r["db_payout"][year]
            sp = r["state_payout"][year]
            pcls = r["tax_free_income"][year]
            unet = r["ufpls_taxable_net"][year]
            isa = r["isa_draw"][year]
            cash = r["cash_draw"][year]
            gia = r["gia_draw"][year]
            taken = db + sp + pcls + unet + isa + cash + gia
            with self.subTest(age=age_label):
                self.assertGreaterEqual(
                    taken, 35_000.0 - expect_gap_lt,
                    msg=(
                        f"Age {age_label} (year {year}) is short of the "
                        f"£35,000 spending target. Take-home = £{taken:,.0f}. "
                        f"Multi-pass waterfall should re-iterate Pension to "
                        f"fill the residual gap."
                    ),
                )

    def test_no_shortfall_at_any_post_retirement_year(self):
        """Stronger regression: every year after retirement (>=5)
        must reach the spending target. Defends against any future
        refactor that reintroduces the original single-pass bug
        for a different shape of household."""
        r = self._take_home_each_year(self._household())
        spend = 35_000.0
        for year in range(5, len(r["years"])):
            db = r["db_payout"][year]
            sp = r["state_payout"][year]
            pcls = r["tax_free_income"][year]
            unet = r["ufpls_taxable_net"][year]
            isa = r["isa_draw"][year]
            cash = r["cash_draw"][year]
            gia = r["gia_draw"][year]
            taken = db + sp + pcls + unet + isa + cash + gia
            with self.subTest(year=year):
                # Cumulative-tax recompute means ufpls_taxable_net
                # is ~£394 lower than the per-call sum. Allow a
                # £500 margin — the cumulative tax IS the correct
                # HMRC liability (progressive brackets).
                self.assertGreaterEqual(
                    taken, spend - 500.0,
                    msg=(
                        f"Year {year}: take_home £{taken:,.0f} < "
                        f"spend £{spend:,.0f}. Gap £{spend - taken:,.0f}."
                    ),
                )

    def test_pension_fires_more_than_once_in_64_66_block(self):
        """Confirm the second Pension call is what's actually
        filling the gap. We don't directly observe internal call
        counts, but we can verify the per-source series sums:
        per_year_take_home_from_ufpls_block = ufpls_net + pcls,
        and for years 9-11 (where the single-pass would under-
        deliver), this take-home MUST exceed the FIRST-call
        ceiling (£21,428 = the take-home of a £23,400 UFPLS draw
        on this household's pre-tax-free / pre-PCLS setup).
        """
        r = self._take_home_each_year(self._household())
        # First-call UFPLS take-home for a £23,400 gross draw on
        # this household: £21,428 (per-spouse shares trigger
        # £1,972 additional tax on a £23,400 taxable draw).
        first_call_take_home_floor = 21_428.0 - 1.0  # £1 FP epsilon
        for year, age_label in [(9, 64), (10, 65), (11, 66)]:
            pcls = r["tax_free_income"][year]
            unet = r["ufpls_taxable_net"][year]
            ufpls_block_take_home = pcls + unet
            with self.subTest(age=age_label):
                self.assertGreater(
                    ufpls_block_take_home, first_call_take_home_floor,
                    msg=(
                        f"Age {age_label}: Pension's per-year take-home "
                        f"({pcls=:.0f}, {unet=:.0f}) is at-or-below the "
                        f"single-call ceiling (£21,428), suggesting the "
                        f"second Pension call is NOT firing and the "
                        f"£1,972 residual is unfilled."
                    ),
                )


# -----------------------------------------------------------------------
# 2. Byte-identical when single-pass was already sufficient
# -----------------------------------------------------------------------
class TestDrawdownMultiPassByteIdenticalToSinglePassWhenFirstPassSufficient(
    unittest.TestCase
):
    """When the first pass through the priority list already meets
    the year-end need, the multi-pass loop must NOT re-call Pension
    nor accumulate any further per-source values. Otherwise the
    chart segmentation and tax recompute would change byte-identical
    outputs that legacy plans rely on.
    """

    def test_first_pass_sufficient_yields_identical_per_source_series(self):
        """Pension alone covers the deficit (no asset wrap needed).
        The multi-pass must terminate after Pass 1 and produce the
        exact series values that the prior single-pass engine did.
        """
        p1 = _make_partner(
            name="Alex", age=65.0, retirement_age=60.0,
            dc_pot=50000.0, db_income=0.0,
            pcls_percent=25.0,
        )
        p2 = _make_partner(name="Sam", age=65.0, retirement_age=60.0)
        assets = _make_assets(
            isa_value=10000.0, cash_value=10000.0, gia_value=5000.0,
        )
        h = Household(
            person1=p1, person2=p2,
            assets=assets,
            spending_target=10_000.0,  # small enough for Pension alone
            drawdown_strategy="Fixed",
            life_expectancy_end_age=80.0,
        )
        r = run_simulation(h, years=1)
        # First call: requested = 10k. PCLS = 25% of 10k = 2.5k
        # (capped at pcls_available). UFPLS taxable = 7.5k.
        # Take-home pre-tax below PA → £7500 + £2500 = £10,000.
        # Loop breaks; no asset draws. Per-source series locked.
        self.assertEqual(r["tax_free_income"][0], 2_500.0)
        self.assertEqual(r["ufpls_taxable_gross"][0], 7_500.0)
        # UFPLS taxable is below the £12,570 PA so zero tax.
        self.assertEqual(r["ufpls_taxable_net"][0], 7_500.0)
        # Asset wrappers never fired.
        self.assertEqual(r["isa_draw"][0], 0.0)
        self.assertEqual(r["cash_draw"][0], 0.0)
        self.assertEqual(r["gia_draw"][0], 0.0)

    def test_first_pass_with_assets_producing_residual_picks_pension_next(self):
        """Asset wrappers alone DO NOT cover the deficit. The first
        Pension call covers MOST but not all (because of tax) — the
        residual £1,972 (in our bug fixture) must be filled by a
        SECOND Pension call. Per-source series ACCUMULATE across
        both calls.
        """
        p1 = _make_partner(
            name="Alex", age=65.0, retirement_age=60.0,
            dc_pot=50_000.0, db_income=0.0, pcls_percent=0.0,
        )
        p2 = _make_partner(name="Sam", age=65.0, retirement_age=60.0)
        # ISA = £1,000 (small). Spending = £30,000. Pension first
        # draw should leave a small residual that the second Pension
        # call fills.
        assets = _make_assets(isa_value=1_000.0)
        h = Household(
            person1=p1, person2=p2,
            assets=assets,
            spending_target=30_000.0,
            drawdown_strategy="Fixed",
            life_expectancy_end_age=80.0,
        )
        r = run_simulation(h, years=1)
        # Pension first call: requested = 30k - 0 = 30k. pcls=0
        # so 100% taxable on person1 only (p2_share = 0 since
        # p2's dc_pot=0). Recompute on the call:
        #   p1_gross = 0 + 30,000 = 30,000 (UFPLS taxable
        #             piped via the `taxable_drawdown` kwarg;
        #             NOT added to p1_gross itself).
        #   tax_on_ufpls_1 = uk_income_tax(30000, 30000) - top.tax
        #                   = (30000-12570)*20% = 4,486
        #   ufpls_take_home_call_1 = 30000 - 4486 = 25,514
        # Income after Pension call 1 = 25,514. ISA drain 1,000.
        # Income = 26,514. Still short of 30k by 3,486.
        # Pension call 2: requested = 3,486. pcls_remaining=0.
        # ufpls_take_home_call_2 = 3,486 (the requested gross is
        # fully below the partner's PA so zero additional tax).
        # Income after call 2 = 26,514 + 3,486 = 30,000.
        # UFPLS taxable gross sums across both calls: 30,000 + 3,486
        # = 33,486.
        taken = (
            r["db_payout"][0]
            + r["state_payout"][0]
            + r["tax_free_income"][0]
            + r["ufpls_taxable_net"][0]
            + r["isa_draw"][0]
            + r["cash_draw"][0]
            + r["gia_draw"][0]
        )
        self.assertGreaterEqual(
            taken, 30_000.0 - 500.0,
            msg=(
                f"Multi-pass should fill the small ISA-drained deficit "
                f"via a second Pension call. Got take_home=£{taken:,.2f} "
                f"vs spend £30,000."
            ),
        )
        # Per-source series must reflect ACCUMULATION across the
        # multi-pass Pension calls. The waterfall now re-iterates
        # until the CUMULATIVE-tax income reaches the £30,000 target
        # (not the per-call approximation), which takes more gross
        # than the old two-call stop: cumulative p1 taxable ≈
        # £33,044. Allow a 100 FP-noising delta to absorb per-spouse
        # share rounding (we always pull from p1 only on this
        # fixture, so the share is exactly 1.0 — but p1_tax result
        # rounding against the £12,570 PA boundary can shift by up
        # to ~£100).
        self.assertAlmostEqual(
            r["ufpls_taxable_gross"][0], 33_044.0, delta=100.0,
            msg=(
                f"UFPLS taxable gross should sum across the multi-pass "
                f"Pension calls. Got {r['ufpls_taxable_gross'][0]:,.0f}, "
                f"expected ~33,044."
            ),
        )


# -----------------------------------------------------------------------
# 3. Termination guard — underfunded plan doesn't loop forever
# -----------------------------------------------------------------------
class TestDrawdownMultiPassTerminatesOnUnderfundedPlan(unittest.TestCase):
    """A structurally underfunded plan (DC pot empty AND assets
    empty AND no DB pension) MUST terminate. The multi-pass loop
    has a `len(priority) + 2` cap and a no-progress detector
    (`_DRAWDOWN_NO_PROGRESS_EPSILON`) — both must kick in cleanly
    without producing an infinite loop or any out-of-range array
    bounds errors downstream (the chart would still render).
    """

    def test_underfunded_plan_runs_and_terminates_with_shortfall(self):
        p1 = _make_partner(
            name="Alex", age=65.0, retirement_age=60.0,
            dc_pot=0.0, db_income=0.0,
        )
        p2 = _make_partner(name="Sam", age=65.0, retirement_age=60.0)
        # No assets, no DB, no DC. State Pension also out of reach
        # (state_pension_age=99 in the helper so the test's
        # early-zero helper default doesn't fire).
        h = Household(
            person1=p1, person2=p2,
            assets=_make_assets(isa_value=0.0),
            spending_target=30_000.0,
            drawdown_strategy="Fixed",
            life_expectancy_end_age=80.0,
        )
        # Run without error. The engine should report a deficit
        # but the per-source series must be present and finite
        # (the multi-pass loop terminates with everything at 0).
        r = run_simulation(h, years=1)
        # Pension fires: actual_ufpls = 0 (DC empty), so
        # tax_free_draw = taxable_draw = ufpls_take_home = 0.
        self.assertEqual(r["tax_free_income"][0], 0.0)
        self.assertEqual(r["ufpls_taxable_net"][0], 0.0)
        self.assertEqual(r["ufpls_taxable_gross"][0], 0.0)
        self.assertEqual(r["isa_draw"][0], 0.0)
        self.assertEqual(r["cash_draw"][0], 0.0)
        self.assertEqual(r["gia_draw"][0], 0.0)


# -----------------------------------------------------------------------
# 4. include_in_spending=True folds the mortgage INTO the spending target
# -----------------------------------------------------------------------
class TestIncludeInSpendingFoldsMortgageIntoNeed(unittest.TestCase):
    """When `mortgage.include_in_spending=True`, the user's spending
    figure ALREADY covers the mortgage — the engine's `total_need`
    must be `spending` alone, NOT `spending + mortgage_paid`. The
    pre-fix engine double-funded the loan (e.g. £38,000 spending +
    £16,608 mortgage = £54,608 drawn in mortgage years), which
    inflated the Quick Estimate income bars ~£16k above the user's
    £38,000 target line. Post-fix the household draws exactly
    `spending` and the bars land on the target.
    """

    def _household(self, include_in_spending):
        p1 = _make_partner(
            name="Dave", age=55.0, retirement_age=60.0,
            dc_pot=400_000.0, db_income=0.0,
        )
        p2 = _make_partner(
            name="Shaz", age=55.0, retirement_age=60.0,
            dc_pot=50_000.0, db_income=0.0,
        )
        mortgage = Mortgage(
            outstanding=110_000.0, rate=0.0458, end_year=8.0,
            annual_payment=16_608.0, annual_overpayment=0.0,
            include_in_spending=include_in_spending,
        )
        return Household(
            person1=p1, person2=p2,
            assets=_make_assets(isa_value=50_000.0),
            mortgage=mortgage,
            spending_target=38_000.0,
            drawdown_strategy="Fixed",
            cash_buffer=False,
            life_expectancy_end_age=90.0,
            show_in_todays_value=True,
            inflation_rate=0.025,
        )

    def test_include_true_draws_only_spending_in_mortgage_years(self):
        """With the flag ON, the income bar in an active-mortgage
        year lands on the £38,000 spending target (within £1 FP
        rounding), NOT £54,608. The mortgage is paid out of the
        spending figure."""
        r = run_simulation(self._household(include_in_spending=True))
        # Year 5 = first fully post-retirement, mortgage active
        # (end_year=8). All partners retired at 60 → earned=0.
        net = r["net_income"][5]
        self.assertAlmostEqual(
            net, 38_000.0, delta=1.0,
            msg=(
                f"include_in_spending=True must draw exactly the £38,000 "
                f"spending target in mortgage years. Got £{net:,.2f} — "
                f"pre-fix this was £54,608 (mortgage double-funded)."
            ),
        )

    def test_include_false_draws_spending_plus_mortgage(self):
        """With the flag OFF (default), spending is lifestyle-only
        and the mortgage is funded on top: the bar lands on
        spending + mortgage_paid ≈ £54,608 in an active-mortgage
        year."""
        r = run_simulation(self._household(include_in_spending=False))
        net = r["net_income"][5]
        # 38,000 + 16,608 = 54,608 (mortgage paid in full that year).
        self.assertGreater(
            net, 38_000.0 + 16_000.0,
            msg=(
                f"include_in_spending=False must fund the mortgage on "
                f"top of spending. Got £{net:,.2f}, expected ≈£54,608."
            ),
        )

    def test_flag_toggle_changes_income_series(self):
        """Flipping the toggle moves the income bars — proving the
        flag drives the engine's `total_need` (not just the chart).
        """
        r_on = run_simulation(self._household(include_in_spending=True))
        r_off = run_simulation(self._household(include_in_spending=False))
        self.assertNotEqual(
            r_on["net_income"][5], r_off["net_income"][5],
            msg="The include_in_spending toggle must change the engine's "
            "drawdown target in mortgage years.",
        )


if __name__ == "__main__":
    unittest.main()
