"""Tests for `simulation.engine.compute_pre_retirement_deficit_signal`.

This is the helper that drives the planning-signal banner on Page 4
(Spending). The banner fires only when the household's pre-retirement
cash flow is in deficit — annual spending + mortgage payment exceeds
earned income in some year while at least one partner is still
pre-retirement. Page 4 overlays the live widget values onto a shallow
copy of `data` so the banner reacts on the same rerun the user types
on; `save_household` is unaffected (only the Save button commits).

Locked-down contracts:

    * `None` returned when:
        - one or both partners is already past `retirement_age`,
        - strategy is "Safe Withdrawal (4%)"
          (asset-driven, not predictable from current inputs),
        - lifetime `spending == 0` AND no active mortgage
          (degenerate "you're saving £0" case),
        - no `person1` / `person2` blocks in saved data
          (defensive guard — Page 4 may render before the user has
          visited Page 2),
        - `need <= earned` for every pre-retirement year.
    * year-of-worst-deficit is the simulation-year index where
      `need - earned` is largest (0-indexed; first occurrence on ties).
    * cumulative shortfall = sum of per-year shortfalls (NOT multiplied
      by years-of-deficit-count); the two metrics correlate but
      decorrelate when spending / earned is non-flat.
    * fractional `retirement_age` truncates the horizon (the year
      a partner DEFINITIVELY retires is excluded).
    * mortgage math is conservative — uses full annual_payment +
      overpayment (capped at `outstanding`) while the mortgage is
      `is_active`. The banner wording reflects this with "while the
      loan is active" so users don't expect engine-fidelity from a
      planning signal.
"""

import unittest

from simulation.deficit_signal import (
    PreRetirementDeficitSignal,
    compute_pre_retirement_deficit_signal,
)


# Test fixture builders — kept tiny so each test focuses on exactly
# what it cares about. Field defaults mirror
# `models.person.Person`/`models.mortgage.Mortgage` defaults.

def _default_person(
    *,
    age=55.0,
    retirement_age=60.0,
    income=0.0,
    growth=0.025,
    state_pension_age=67.0,
    db_income=0.0,
    draw_age=60.0,
    db_growth=0.025,
    sp_growth=0.025,
):
    return {
        "age": age,
        "retirement_age": retirement_age,
        "state_pension_age": state_pension_age,
        "dc_pot": 0.0,
        "income_until_retirement": income,
        "income_growth_rate": growth,
        "db_income": db_income,
        "draw_age": draw_age,
        "db_growth_rate": db_growth,
        "state_pension_growth_rate": sp_growth,
    }


def _default_mortgage(
    *,
    outstanding=0.0,
    annual=0.0,
    overpay=0.0,
    end_year=0.0,
):
    return {
        "outstanding": outstanding,
        "rate": 0.0458,
        "end_year": end_year,
        "annual_payment": annual,
        "annual_overpayment": overpay,
    }


def _build_data(
    *,
    spending=35_000,
    strategy="Fixed",
    p1=None,
    p2=None,
    mortgage=None,
    assets=None,
    cash_buffer=False,
):
    """Return a fresh, fully-populated `data` dict.

    Tests are free to mutate the result — each call returns a fresh
    top-level dict with fresh nested-dict copies, so cross-test
    state bleed cannot happen.

    New optional kwargs (with safe defaults so existing callers
    remain unchanged):

    * `assets` — list of asset-dict definitions to populate
      `data["assets"]`. Defaults to `[]` (no assets) when None.
      The new residual-signal tests in
      `TestResidualAfterDrainSignal` pass a populated `assets`
      list so the cash_buffer drain has a real pool to operate
      against.
    * `cash_buffer` — bool flag forwarded into `data["cash_buffer"]`
      so the helper can route the residual-signal math. Defaults
      to False (matches the dataclass default; preserves legacy
      behaviour for the existing tests).
    """
    return {
        "person1": dict(p1 or _default_person()),
        "person2": dict(p2 or _default_person()),
        "assets": assets if assets is not None else [],
        "mortgage": dict(mortgage or _default_mortgage()),
        "spending": spending,
        "drawdown_strategy": strategy,
        "cash_buffer": cash_buffer,
    }


class TestPreRetirementDeficitSignalReturnsNone(unittest.TestCase):
    """The no-signal cases — every one returns ``None`` so the
    Page 4 banner stays silent."""

    def test_no_signal_when_earned_covers_need_every_year(self):
        data = _build_data(
            spending=35_000,
            p1=_default_person(income=50_000),
            p2=_default_person(income=50_000),
        )
        self.assertIsNone(compute_pre_retirement_deficit_signal(data))

    def test_no_signal_when_strategy_is_safe_withdrawal(self):
        # 4%-rule — asset-driven, not predictable from current inputs.
        # The helper returns None so Page 4 doesn't fire a misleading
        # signal that won't reflect post-simulation reality.
        data = _build_data(strategy="Safe Withdrawal (4%)")
        self.assertIsNone(compute_pre_retirement_deficit_signal(data))

    def test_no_signal_when_partner_already_retired(self):
        # p1 age 65, retirement_age 60 → `years_to_ret = -5` → horizon
        # is 0 (no pre-retirement period to check). The engine's
        # drawdown gate is already wide open for this household, so
        # the planning-signal would be redundant.
        data = _build_data(
            p1=_default_person(age=65.0, retirement_age=60.0),
            p2=_default_person(age=55.0, retirement_age=60.0),
        )
        self.assertIsNone(compute_pre_retirement_deficit_signal(data))

    def test_no_signal_when_both_partners_already_retired(self):
        data = _build_data(
            p1=_default_person(age=70.0, retirement_age=60.0),
            p2=_default_person(age=70.0, retirement_age=60.0),
        )
        self.assertIsNone(compute_pre_retirement_deficit_signal(data))

    def test_no_signal_when_spending_zero_and_no_mortgage(self):
        # Degenerate "you're saving £0" case. No benchmark to compare
        # against, so no deficit can ever be flagged.
        data = _build_data(spending=0)
        self.assertIsNone(compute_pre_retirement_deficit_signal(data))

    def test_no_signal_when_underlying_data_missing_partners(self):
        # Page 4 may render before the user has visited Page 2;
        # `household_data` may legitimately lack `person1`/`person2`.
        data = {
            "spending": 35_000,
            "drawdown_strategy": "Fixed",
        }
        self.assertIsNone(compute_pre_retirement_deficit_signal(data))

    def test_no_signal_when_earned_above_need_with_mortgage(self):
        # earned (50k) >= need (20k spending + 1k mortgage) → surplus
        # throughout. Mortgage payment is capped at outstanding (1k),
        # demonstrating the conservative-but-not-overstated cap.
        data = _build_data(
            spending=20_000,
            p1=_default_person(income=50_000),
            mortgage=_default_mortgage(
                outstanding=1_000,
                annual=10_000,
                overpay=5_000,
                end_year=10.0,
            ),
        )
        self.assertIsNone(compute_pre_retirement_deficit_signal(data))


class TestPreRetirementDeficitSignalFires(unittest.TestCase):
    """The firing cases — the helper returns a populated
    ``PreRetirementDeficitSignal`` that the Page 4 banner reads."""

    def test_signal_with_zero_incomes_and_positive_spending(self):
        # Default plan: both partners earn £0 until retirement. The
        # £35k lifestyle spend therefore exceeds earned income every
        # single year. Worst year = 0 (first found at the strict `>`
        # comparison), cumulative = 5 × £35k = £175k over the horizon.
        data = _build_data(spending=35_000)
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsInstance(signal, PreRetirementDeficitSignal)
        self.assertEqual(signal.worst_year, 0)
        self.assertAlmostEqual(signal.worst_deficit_gbp, 35_000.0)
        self.assertAlmostEqual(signal.cumulative_deficit_gbp, 175_000.0)
        self.assertEqual(signal.pre_retirement_year_count, 5)
        self.assertAlmostEqual(signal.annual_spending_gbp, 35_000.0)
        self.assertEqual(signal.strategy, "Fixed")
        # pre-retirement year count capped at the function's ``years``
        # arg (default 45). 5y here is min(5, 45). No need to test.
        self.assertIs(type(signal), PreRetirementDeficitSignal)

    def test_signal_with_mortgage_payment(self):
        # Both partners earn £15k combined; spending £30k; mortgage
        # £15k/yr (active). Need = £45k vs £15k earned → £30k deficit.
        # Cumulative = 5y × £30k = £150k.
        data = _build_data(
            spending=30_000,
            p1=_default_person(income=15_000),
            p2=_default_person(income=0.0),
            mortgage=_default_mortgage(
                outstanding=112_000,
                annual=12_000,
                overpay=3_000,
                end_year=12.0,
            ),
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertAlmostEqual(
            signal.annual_mortgage_when_active_gbp, 15_000.0
        )
        # earned(y) = 15k * 1.025**y, need(y) = 30k + 15k = 45k
        # deficit(y) = 45k - 15k * 1.025**y
        # Worst year = 0 (45k - 15k = 30k).
        # Cumulative = sum over y=0..4 of (45k - 15k * 1.025^y)
        self.assertEqual(signal.worst_year, 0)
        self.assertAlmostEqual(signal.worst_deficit_gbp, 30_000.0)
        expected_cumulative = sum(
            45_000 - 15_000 * 1.025 ** y for y in range(5)
        )
        self.assertAlmostEqual(
            signal.cumulative_deficit_gbp, expected_cumulative, places=2
        )

    def test_signal_mortgage_ends_mid_horizon_drops_need(self):
        # Mortgage ends year 3 of a 5-year pre-retirement horizon.
        # Year 0..2: need = £30k spending + £15k mortgage = £45k,
        #           earned = £35k * 1.025**y   → deficit.
        # Year 3..4: need = £30k only, earned kept growing at 2.5%
        #           → surplus, no deficit addition.
        # Worst year = 0 (deficit monotonically shrinks year-by-year
        # when earned inflates 2.5%/yr and need is constant).
        data = _build_data(
            spending=30_000,
            p1=_default_person(income=17_500),
            p2=_default_person(income=17_500),
            mortgage=_default_mortgage(
                outstanding=40_000,
                annual=12_000,
                overpay=3_000,
                end_year=3.0,
            ),
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.worst_year, 0)
        self.assertAlmostEqual(
            signal.worst_deficit_gbp, 10_000.0, places=2
        )
        # Cumulative = sum over y=0..2 of (45k - 35k * 1.025^y); year
        # 3+ contribute no deficit because the mortgage is gone and
        # need < earned.
        expected_cumulative = sum(
            45_000 - 35_000 * 1.025 ** y for y in range(3)
        )
        self.assertAlmostEqual(
            signal.cumulative_deficit_gbp, expected_cumulative, places=2
        )

    def test_signal_inflation_adjusted_strategy(self):
        # Inflation-adjusted: spending inflates 2.5%/yr. Income (zero
        # here) stays zero — so deficit grows over time and the worst
        # year is the LAST pre-retirement year (year 4).
        data = _build_data(
            spending=35_000,
            strategy="Inflation-adjusted",
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.worst_year, 4)
        self.assertAlmostEqual(
            signal.worst_deficit_gbp, 35_000 * 1.025 ** 4, places=2
        )
        self.assertEqual(signal.strategy, "Inflation-adjusted")
        expected_cumulative = sum(
            35_000 * 1.025 ** y for y in range(5)
        )
        self.assertAlmostEqual(
            signal.cumulative_deficit_gbp, expected_cumulative, places=2
        )

    def test_horizon_is_min_years_to_retirement(self):
        # p1 retires in 5y; p2 retires in 10y. Pre-retirement horizon
        # should be the MIN of the two (`any_retired` triggers on the
        # first to retire — same as the engine's drawdown gate).
        data = _build_data(
            p1=_default_person(retirement_age=60.0),  # 5y
            p2=_default_person(retirement_age=65.0),  # 10y
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.pre_retirement_year_count, 5)

    def test_fractional_retirement_age_truncates_horizon(self):
        # age 55, retirement_age 60.667 → years_to_ret = 5.667.
        # Horizon = int(5.667) = 5 — the same convention the engine
        # uses for fractional-year closing-y retirement.
        data = _build_data(
            p1=_default_person(age=55.0, retirement_age=60.667),
            p2=_default_person(age=55.0, retirement_age=60.667),
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.pre_retirement_year_count, 5)

    def test_worst_year_age_uses_person1_age(self):
        # Mixed-age household: person1 is 10y older than person2.
        # The reported age at the worst-deficit year is person1's,
        # matching other pages' "Age X → Y" header convention (which
        # keys off person1's age).
        data = _build_data(
            p1=_default_person(age=65.0, retirement_age=70.0, income=0.0),
            p2=_default_person(age=55.0, retirement_age=60.0, income=0.0),
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertAlmostEqual(signal.worst_year_age_p1, 65.0)

    def test_mortgage_payment_capped_at_outstanding(self):
        # Mortgage with £1k outstanding and a £15k/yr stated payment
        # — the helper caps at outstanding. Plan income covers need
        # under the cap so no signal fires (regression for the
        # "over-stated mortgage payment" guard).
        data = _build_data(
            spending=20_000,
            p1=_default_person(income=50_000),
            mortgage=_default_mortgage(
                outstanding=1_000,
                annual=10_000,
                overpay=5_000,
                end_year=10.0,
            ),
        )
        signal = compute_pre_retirement_deficit_signal(
            data, years=10
        )
        # earned (50k) > need (20k + 1k capped) every year → no signal.
        self.assertIsNone(signal)


class TestDbPensionClosesGap(unittest.TestCase):
    """DB pension that kicks in BEFORE retirement_age (the common
    'still working X years past draw_age' case) is included in the
    household-income side of the deficit math — otherwise the helper
    understates income and fires a spurious signal for a household
    whose DB pension alone already bridges the gap."""

    def test_db_pension_active_at_year_0_suppresses_signal(self):
        # p1 is age 60 (already active on DB at draw_age=60), will
        # retire next year. Spends £25k/yr; DB pension pays £30k/yr
        # indexed up. Without the DB-pension fix the helper's
        # `earned` sum at year 0 would be £0 (no wages configured)
        # and the signal would fire spuriously. With the fix DB
        # closes the gap and the banner stays silent.
        data = _build_data(
            spending=25_000,
            p1=_default_person(
                age=60.0,
                retirement_age=61.0,
                income=0.0,
                db_income=30_000,
                draw_age=60.0,
            ),
            p2=_default_person(age=55.0, retirement_age=60.0),
        )
        self.assertIsNone(compute_pre_retirement_deficit_signal(data))

    def test_db_pension_partial_coverage_still_fires(self):
        # DB pension is below spending — signal still fires for the
        # pre-draw_age years, but the cumulative shortfall is smaller
        # than the wages-only baseline would suggest once DB kicks in.
        # Worst year is year 0 (DB not yet active); cumulative covers
        # only the pre-draw_age years.
        data = _build_data(
            spending=30_000,
            p1=_default_person(
                age=60.0,
                retirement_age=65.0,
                income=0.0,
                db_income=20_000,
                draw_age=62.0,  # DB starts mid-horizon
            ),
            p2=_default_person(age=55.0, retirement_age=60.0),
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        # Worst year = 0 (no wages, no DB yet, deficit = 30k).
        self.assertEqual(signal.worst_year, 0)
        self.assertAlmostEqual(signal.worst_deficit_gbp, 30_000.0)


class TestStatePensionClosesGap(unittest.TestCase):
    """State Pension income, once `state_pension_age` is reached,
    counts toward household income for the deficit-signal math —
    same rationale as DB pension above."""

    def test_state_pension_active_at_year_0_suppresses_signal(self):
        # p1 is age 67 (SP active), will retire next year. Spends
        # £10k/yr; SP pays £11k/yr indexed up. With the SP fix the
        # helper's `income` sum at year 0 closes the gap and the
        # banner stays silent.
        data = _build_data(
            spending=10_000,
            p1=_default_person(
                age=67.0,
                retirement_age=68.0,
                income=0.0,
                state_pension_age=67.0,
            ),
            p2=_default_person(age=55.0, retirement_age=60.0),
        )
        self.assertIsNone(compute_pre_retirement_deficit_signal(data))


class TestHouseholdIncomeField(unittest.TestCase):
    """The `household_income_at_worst_gbp` field — was renamed from
    `earned_at_worst_gbp` so the field name matches the helper's
    full-income model (wages + DB + SP). These tests verify the
    combined figure."""

    def test_field_reflects_wages_plus_db(self):
        # p1 wage = 10k, DB = 15k (active at year 0 since
        # draw_age=55==age). Worst year = 0 (constant deficit).
        # household_income should be 10k + 15k + p2 (0) = 25k —
        # NOT just the 10k wage the old "earned_at_worst_gbp" name
        # suggested.
        data = _build_data(
            spending=40_000,
            p1=_default_person(
                age=55.0,
                retirement_age=60.0,
                income=10_000,
                db_income=15_000,
                draw_age=55.0,
            ),
            p2=_default_person(),
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertAlmostEqual(
            signal.household_income_at_worst_gbp, 25_000.0, places=2
        )


class TestPreRetirementDeficitSignalYearsCap(unittest.TestCase):
    """The `years=45` arg (default) bounds the walked horizon even if
    the user has very late retirements."""

    def test_horizon_capped_at_years_argument(self):
        # Both partners retire 30 years from "now". Horizon should
        # still be capped at years=10 (passed in by the test) — the
        # engine itself runs `years=45` by default and we want the
        # helper to be controllable for big-horizon edge cases.
        data = _build_data(
            p1=_default_person(age=30.0, retirement_age=60.0),
            p2=_default_person(age=30.0, retirement_age=60.0),
        )
        signal = compute_pre_retirement_deficit_signal(data, years=10)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.pre_retirement_year_count, 10)


class TestResidualAfterDrainSignal(unittest.TestCase):
    """The residual-after-drain signal — a second-tier planning
    banner on Page 4 (Spending) that surfaces a STRUCTURAL
    underfunding the cash_buffer opt-in mode can't bridge. Lives
    on the same `PreRetirementDeficitSignal` dataclass as the main
    deficit signal (`worst_deficit_gbp` / `cumulative_deficit_gbp`)
    but adds four fields populated only when `cash_buffer=True`:

      * `cash_buffer_at_signal: bool` — what the user's plan said.
      * `worst_residual_year: int` — 0-indexed year of the biggest
        residual shortfall AFTER drain.
      * `worst_residual_gbp: float` — £ residual at that year.
      * `cumulative_residual_gbp: float` — total residual over the
        full pre-retirement horizon.
      * `total_assets_drained_gbp: float` — cumulative drain across
        the horizon (informative; not a firing condition).

    Companion to the cash_buffer feature itself (locked in
    `tests/test_cash_buffer.py::TestCashBufferTrueDrainsAssets`)
    and to the main pre-retirement deficit signal above.

    Locked-down contracts:

    * `cash_buffer=False` → all residual fields stay 0
      (`worst_residual_year == -1`,
      `worst_residual_gbp == cumulative_residual_gbp ==
      total_assets_drained_gbp == 0.0`,
      `cash_buffer_at_signal == False`).
    * `cash_buffer=True` AND drainable pool >= cumulative deficit
      → `worst_residual_gbp == 0.0` (drain fully covers).
    * `cash_buffer=True` AND drainable pool < cumulative deficit
      → `worst_residual_gbp > 0` and residual banner fires.
    * `cash_buffer=True` AND drainable pool == 0 → residual == full
      deficit at every deficit year (`worst_residual_gbp ==
      worst_deficit_gbp`).
    """

    def test_residual_zero_when_cash_buffer_false(self):
        # cash_buffer=False → drain not attempted → residual stays 0
        # even though the main deficit signal fires. The Page 4
        # banner reads `cash_buffer_at_signal and
        # worst_residual_gbp > 0` for its firing condition, so this
        # case correctly skips the residual `st.error(...)`.
        data = _build_data(spending=35_000, cash_buffer=False)
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertFalse(signal.cash_buffer_at_signal)
        self.assertEqual(signal.worst_residual_year, -1)
        self.assertAlmostEqual(
            signal.worst_residual_year_age_p1, 0.0
        )
        self.assertAlmostEqual(signal.worst_residual_gbp, 0.0)
        self.assertAlmostEqual(signal.cumulative_residual_gbp, 0.0)
        self.assertAlmostEqual(signal.total_assets_drained_gbp, 0.0)

    def test_residual_zero_when_drain_fully_covers(self):
        # cash_buffer=True with a £500k Cash pool — pool covers the
        # full £35k × 5y = £175k cumulative deficit. residual is 0
        # at every year AND total_drained = £175k (the full drain
        # amount matches the cumulative deficit, confirming
        # `total_assets_drained_gbp` correctly tracks the magnitude).
        data = _build_data(
            spending=35_000,
            cash_buffer=True,
            assets=[
                {
                    "name": "Cash", "value": 500_000,
                    "growth_rate": 0.0, "asset_type": "Cash",
                },
            ],
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertTrue(signal.cash_buffer_at_signal)
        self.assertEqual(signal.worst_residual_year, -1)
        self.assertAlmostEqual(
            signal.worst_residual_year_age_p1, 0.0
        )
        self.assertAlmostEqual(signal.worst_residual_gbp, 0.0)
        self.assertAlmostEqual(
            signal.cumulative_residual_gbp, 0.0, places=2
        )
        # Total drained covers the full £175k deficit.
        self.assertAlmostEqual(
            signal.total_assets_drained_gbp, 175_000.0, places=2
        )

    def test_residual_fires_when_drain_partial(self):
        # cash_buffer=True with a £20k Cash pool against a £35k/yr
        # deficit across a 5-year horizon. The helper drains the
        # year-0 pool monotonically:
        #   * year 0: drain 20k, residual 15k (35 - 20 = 15)
        #   * year 1: pool empty (`drainable_pool == 0` after
        #     year-0 drain), residual 35k (no drain attempted).
        #   * years 2-4: same as year 1, residual stays 35k.
        # Worst residual = 35k (year 1 or later, pool already 0).
        # Cumulative residual = 15k + 4*35k = 155k. Total drained
        # = 20k (only year 0 has any drain to apply).
        data = _build_data(
            spending=35_000,
            cash_buffer=True,
            assets=[
                {
                    "name": "Cash", "value": 20_000,
                    "growth_rate": 0.0, "asset_type": "Cash",
                },
            ],
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertTrue(signal.cash_buffer_at_signal)
        self.assertGreater(signal.worst_residual_gbp, 0.0)
        # Worst residual occurs at year 1 (the first year where the
        # pool has been fully drained, so the full £35k deficit is
        # uncovered). Years 2-4 also have residual=£35k so any of
        # them is a valid `worst_residual_year` (1, 2, 3, or 4).
        self.assertIn(signal.worst_residual_year, (1, 2, 3, 4))
        self.assertAlmostEqual(
            signal.worst_residual_gbp, 35_000.0, places=2
        )
        # Cumulative residual = 15k (year 0) + 4 * 35k = 155k.
        self.assertAlmostEqual(
            signal.cumulative_residual_gbp, 155_000.0, places=2
        )
        # Total drained is bounded by the year-0 pool (£20k).
        self.assertAlmostEqual(
            signal.total_assets_drained_gbp, 20_000.0, places=2
        )

    def test_residual_equals_deficit_when_pool_empty(self):
        # cash_buffer=True with NO drainable assets (assets=[]).
        # `drainable_pool = 0` from the start, so the inner branch
        # `if cash_buffer_enabled and drainable_pool > 0:` never
        # fires — residual stays equal to the full deficit at
        # every year. `worst_residual_gbp` should equal
        # `worst_deficit_gbp` (both 35k — constant deficit), and
        # `total_assets_drained_gbp` stays 0 (no drain attempts).
        data = _build_data(
            spending=35_000, cash_buffer=True, assets=[]
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertTrue(signal.cash_buffer_at_signal)
        self.assertAlmostEqual(
            signal.worst_residual_gbp,
            signal.worst_deficit_gbp,
            places=2,
        )
        self.assertAlmostEqual(signal.worst_residual_gbp, 35_000.0)
        self.assertAlmostEqual(signal.total_assets_drained_gbp, 0.0)

    def test_worst_residual_year_age_uses_person1_age(self):
        # Like `test_worst_year_age_uses_person1_age` but for the
        # RESIDUAL signal: mixed-age household where p1 is 10y
        # older than p2. The reported residual year age should be
        # p1's age at the worst-residual year, so the banner
        # wording can say "age X — you'd still be £Y/year short".
        data = _build_data(
            p1=_default_person(age=65.0, retirement_age=70.0, income=0.0),
            p2=_default_person(age=55.0, retirement_age=60.0, income=0.0),
            spending=35_000,
            cash_buffer=True,
            assets=[
                {
                    "name": "Cash", "value": 20_000,
                    "growth_rate": 0.0, "asset_type": "Cash",
                },
            ],
        )
        signal = compute_pre_retirement_deficit_signal(data)
        self.assertIsNotNone(signal)
        self.assertGreater(signal.worst_residual_year, -1)
        # Worst residual year is p1's age offset by `worst_residual_year`.
        self.assertAlmostEqual(
            signal.worst_residual_year_age_p1,
            65.0 + signal.worst_residual_year,
            places=2,
        )


if __name__ == "__main__":
    unittest.main()
