"""
Tests for the monthly DC pot compounding logic added in engine.py.

Covers three layers:

  1. _dc_monthly_compound          — closed-form math vs 12-iteration loop.
  2. _monthly_dc_contrib           — %-based vs legacy flat-£ toggle.
  3. End-to-end engine run         — 10 years of monthly compounding under
                                     multiple configurations must match the
                                     closed-form accumulator to within
                                     tight tolerance.

The closed-form reference used throughout:

    pot_end_year  =  pot_start_year * (1 + r/12) ** 12
                   + M * ((1 + r/12) ** 12 - 1) / (r/12)     (r != 0)
    pot_end_year  =  pot_start_year + 12 * M                  (r == 0)

where `r` is the annual DC growth rate and `M` is the £-per-month
contribution for the year. The engine's iteration order is "growth first,
contribute second" — an annuity-due convention.
"""

import unittest
from types import SimpleNamespace

from simulation.engine import (
    _dc_monthly_compound,
    _monthly_dc_contrib,
    run_simulation,
)
from models.person import Person
from models.household import Household


class TestDcMonthlyCompoundUnit(unittest.TestCase):
    """Lock down _dc_monthly_compound against the closed-form reference."""

    def _closed_form(self, pot_start, r, M):
        """Annuity-due closed form, with the r==0 limit taken care of."""
        if r == 0:
            return pot_start + 12 * M
        r_m = r / 12
        return pot_start * (1 + r_m) ** 12 + M * ((1 + r_m) ** 12 - 1) / r_m

    def test_zero_pot_with_contribution_is_pure_annuity_due(self):
        M, r = 500.0, 0.05
        actual = _dc_monthly_compound(0.0, r, M)
        self.assertAlmostEqual(actual, self._closed_form(0.0, r, M), places=6)

    def test_opening_pot_no_contribution_is_pure_compound(self):
        pot, r = 10_000.0, 0.05
        actual = _dc_monthly_compound(pot, r, 0.0)
        self.assertAlmostEqual(actual, pot * (1 + r / 12) ** 12, places=6)

    def test_combined_opening_pot_and_contributions(self):
        pot, M, r = 10_000.0, 500.0, 0.05
        actual = _dc_monthly_compound(pot, r, M)
        self.assertAlmostEqual(actual, self._closed_form(pot, r, M), places=6)

    def test_zero_rate_is_pure_accumulation_not_div_by_zero(self):
        # Critical regression guard: the closed-form `(1+r/12)**12 - 1`/(r/12)
        # is 0/0 at r=0. The iteration must NEVER divide by zero — it just
        # accumulates M twelve times. Tests for r=0 must hold to high
        # precision since the iteration cost there is trivial.
        pot, M = 10_000.0, 500.0
        actual = _dc_monthly_compound(pot, 0.0, M)
        self.assertAlmostEqual(actual, pot + 12 * M, places=6)

    def test_high_rate_compounding_exceeds_annual_compound(self):
        # Sanity check at r=0.15: monthly compounding strictly dominates
        # annual compounding on the opening balance alone.
        pot, r = 10_000.0, 0.15
        actual = _dc_monthly_compound(pot, r, 0.0)
        self.assertGreater(actual, pot * (1 + r))
        self.assertAlmostEqual(actual, pot * (1 + r / 12) ** 12, places=4)

    def test_negative_rate_no_crash(self):
        # Drawdown-year scenario: r can be small & negative in tests. Should
        # not raise. (In practice, DC_RATE_FLOOR in monte_carlo.py clamps
        # this in MC; this is just a robustness check on the helper.)
        pot, M = 1_000.0, 100.0
        actual = _dc_monthly_compound(pot, -0.02, M)
        self.assertIsInstance(actual, float)
        self.assertGreater(actual, 0.0)

    def test_zero_pot_zero_contribution_zero_growth(self):
        actual = _dc_monthly_compound(0.0, 0.0, 0.0)
        self.assertEqual(actual, 0.0)


class TestMonthlyDcContrib(unittest.TestCase):
    """Lock down the % vs flat-£ toggle for the monthly contribution."""

    def _person(self, pct=0.0, flat=0.0):
        # SimpleNamespace sidesteps the dataclass default coupling so we
        # test the helper's contract in isolation.
        return SimpleNamespace(monthly_contrib_pct=pct, monthly_contrib=flat)

    def test_pct_drives_contribution_when_set(self):
        p = self._person(pct=0.15, flat=99999.0)  # huge flat ignored
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, 60_000.0),
            60_000.0 * 0.15 / 12,
            places=6,
        )

    def test_zero_pct_falls_back_to_legacy_flat(self):
        p = self._person(pct=0.0, flat=600.0)
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, 60_000.0),
            50.0,  # 600 / 12
            places=6,
        )

    def test_both_zero_yields_zero(self):
        p = self._person(pct=0.0, flat=0.0)
        self.assertEqual(_monthly_dc_contrib(p, 60_000.0), 0.0)

    def test_indexed_income_drives_pct_contribution(self):
        # £80k wage that has been indexed 5 years at 2.5% should drive
        # an above-15% contribution.
        p = self._person(pct=0.10)
        indexed_income = 80_000.0 * (1.025 ** 5)  # ~£90,453
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, indexed_income),
            indexed_income * 0.10 / 12,
            places=4,
        )


class TestEngineDcEndToEnd(unittest.TestCase):
    """
    Lock down that a full `run_simulation` produces dc_pot series that
    exactly track the closed-form accumulator in well-defined scenarios.
    """

    def _make_household(
        self,
        dc_pot=0.0,
        dc_rate=0.05,
        income=60_000.0,
        income_growth=0.0,
        pct=0.0,
        flat=0.0,
        retirement_age=99,
        draw_age=99,
        state_pension_age=99,
        spending_target=0,
        years=10,
    ):
        p1 = Person(
            name="P1",
            age=30,
            retirement_age=retirement_age,
            state_pension_age=state_pension_age,
            dc_pot=dc_pot,
            db_income=0.0,
            monthly_contrib=flat,
            income_until_retirement=income,
            draw_age=draw_age,
            pcls_percent=0,
            income_growth_rate=income_growth,
            monthly_contrib_pct=pct,
            dc_growth_rate=dc_rate,
            db_growth_rate=0.0,
            state_pension_growth_rate=0.0,
        )
        p2 = Person(
            name="P2",
            age=30,
            retirement_age=99,
            state_pension_age=99,
            dc_pot=0.0,
            db_income=0.0,
            monthly_contrib=0.0,
            income_until_retirement=0.0,
            draw_age=99,
            pcls_percent=0,
            income_growth_rate=0.0,
            monthly_contrib_pct=0.0,
            dc_growth_rate=0.0,
            db_growth_rate=0.0,
            state_pension_growth_rate=0.0,
        )
        h = Household(
            person1=p1, person2=p2, assets=[], mortgage=None,
            spending_target=spending_target, events=[],
        )
        return h, years

    def _expected_pot_series(self, dc_pot_start, dc_rate, annual_M, years):
        """Year-by-year closed-form accumulator for the partner."""
        r_m = dc_rate / 12
        series = []
        pot = dc_pot_start
        for _ in range(years):
            if dc_rate == 0:
                pot = pot + 12 * annual_M
            else:
                pot = pot * (1 + r_m) ** 12 + annual_M * ((1 + r_m) ** 12 - 1) / r_m
            series.append(pot)
        return series

    def test_ten_year_pct_path_matches_closed_form(self):
        h, years = self._make_household(
            dc_pot=10_000, dc_rate=0.05, income=60_000, pct=0.15, years=10,
        )
        r = run_simulation(h, years=years)
        annual_M = 60_000 * 0.15 / 12
        expected = self._expected_pot_series(10_000, 0.05, annual_M, years)
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(
                    r["dc_pot"][y], exp, places=4,
                    msg=f"Year {y}: engine {r['dc_pot'][y]:.4f} vs expected {exp:.4f}",
                )

    def test_legacy_flat_contribution_path(self):
        h, years = self._make_household(
            dc_pot=10_000, dc_rate=0.05, income=60_000, flat=600.0, years=5,
        )
        r = run_simulation(h, years=years)
        annual_M = 600.0 / 12  # 50
        expected = self._expected_pot_series(10_000, 0.05, annual_M, years)
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(r["dc_pot"][y], exp, places=4)

    def test_post_retirement_is_pure_compound_no_contribution(self):
        # Both partners effectively retired year 0 (retirement_age=30). With
        # flat spending=0, drawdown never kicks in and the pot compounds
        # alone at 5%/yr on £50k. Even with huge pct and huge flat set on
        # Person 1, retirement should zero them out.
        p1 = Person(
            name="P1",
            age=30,
            retirement_age=30,
            state_pension_age=99,
            dc_pot=50_000,
            db_income=0.0,
            monthly_contrib=999.0,           # legacy flat — ignored when retired
            income_until_retirement=999_999.0,  # unused
            draw_age=99,
            pcls_percent=0,
            income_growth_rate=0.025,
            monthly_contrib_pct=0.5,         # 50% — ignored when retired
            dc_growth_rate=0.05,
            db_growth_rate=0.0,
            state_pension_growth_rate=0.0,
        )
        p2 = Person(
            name="P2",
            age=30,
            retirement_age=99,
            state_pension_age=99,
            dc_pot=0.0,
            db_income=0.0,
            monthly_contrib=0.0,
            income_until_retirement=0.0,
            draw_age=99,
            pcls_percent=0,
            income_growth_rate=0.0,
            monthly_contrib_pct=0.0,
            dc_growth_rate=0.0,
            db_growth_rate=0.0,
            state_pension_growth_rate=0.0,
        )
        h = Household(
            person1=p1, person2=p2, assets=[], mortgage=None,
            spending_target=0, events=[],  # spending=0 → no drawdown
        )
        r = run_simulation(h, years=5)
        expected = self._expected_pot_series(50_000, 0.05, 0.0, 5)
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(r["dc_pot"][y], exp, places=4)

    def test_zero_growth_rate_path(self):
        # Regression-locks the r=0 path through the engine.
        h, years = self._make_household(
            dc_pot=10_000, dc_rate=0.0, income=60_000, pct=0.15, years=3,
        )
        r = run_simulation(h, years=years)
        annual_M = 60_000 * 0.15 / 12
        expected = self._expected_pot_series(10_000, 0.0, annual_M, 3)
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(r["dc_pot"][y], exp, places=4)
        # Sanity: r=0, so 3 years = +36 * M = pure accumulation.
        self.assertAlmostEqual(
            r["dc_pot"][2] - r["dc_pot"][0], 24 * annual_M, places=4,
        )

    def test_wage_inflation_indexed_contributions_match_closed_form(self):
        # Priority regression target: per-year M=indexed_income*pct/12. The
        # engine must derive M from `_monthly_dc_contrib(person,
        # p_earned_this_year)`, which itself uses the wage-inflated income.
        # A refactor that breaks this wiring could ship undetected without
        # this end-to-end test.
        #
        # Setup: income=£60k, income_growth=2.5%/yr, pct=15%, dc_rate=5%/yr,
        # dc_pot=£10k, 6 years. At each year y:
        #   M_y = 60000 * (1.025 ** y) * 0.15 / 12
        #   pot_y = pot_{y-1} * (1+r/12)^12 + M_y * ((1+r/12)^12 - 1) / (r/12)
        h, years = self._make_household(
            dc_pot=10_000, dc_rate=0.05,
            income=60_000, income_growth=0.025,
            pct=0.15, years=6,
        )
        r = run_simulation(h, years=years)

        # Hand-derived accumulator
        r_m = 0.05 / 12
        growth_factor = (1 + r_m) ** 12
        annuity_factor = (growth_factor - 1) / r_m
        pot = 10_000.0
        for y in range(years):
            M_y = 60_000.0 * (1.025 ** y) * 0.15 / 12
            pot = pot * growth_factor + M_y * annuity_factor
            with self.subTest(year=y):
                self.assertAlmostEqual(
                    r["dc_pot"][y], pot, places=4,
                    msg=f"Y{y}: engine={r['dc_pot'][y]:.4f} expected={pot:.4f} "
                        f"(M_y={M_y:.4f})",
                )

        # Sanity: M should be strictly increasing year-on-year (because
        # income grows), and the resulting dc_pot should visibly exceed the
        # constant-M baseline at the same final M0.
        constant_M_pot = 10_000.0
        M0 = 60_000.0 * 0.15 / 12
        for _ in range(years):
            constant_M_pot = constant_M_pot * growth_factor + M0 * annuity_factor
        self.assertGreater(r["dc_pot"][-1], constant_M_pot)

    def test_double_partner_compound(self):
        # Both partners contribute via pct; verify the engine adds them
        # both and tracks the SUM into results["dc_pot"] correctly.
        p1 = Person(
            name="P1",
            age=30,
            retirement_age=99,
            state_pension_age=99,
            dc_pot=0.0,
            db_income=0.0,
            monthly_contrib=0.0,
            income_until_retirement=40_000.0,
            draw_age=99,
            pcls_percent=0,
            income_growth_rate=0.0,
            monthly_contrib_pct=0.10,        # p1 contrib = 40000*0.1/12
            dc_growth_rate=0.05,
            db_growth_rate=0.0,
            state_pension_growth_rate=0.0,
        )
        p2 = Person(
            name="P2",
            age=30,
            retirement_age=99,
            state_pension_age=99,
            dc_pot=0.0,
            db_income=0.0,
            monthly_contrib=0.0,
            income_until_retirement=20_000.0,
            draw_age=99,
            pcls_percent=0,
            income_growth_rate=0.0,
            monthly_contrib_pct=0.20,        # p2 contrib = 20000*0.2/12
            dc_growth_rate=0.05,
            db_growth_rate=0.0,
            state_pension_growth_rate=0.0,
        )
        h = Household(
            person1=p1, person2=p2, assets=[], mortgage=None,
            spending_target=0, events=[],
        )
        r = run_simulation(h, years=2)

        # p1 expected
        p1_M = 40_000 * 0.10 / 12
        p1_expected = self._expected_pot_series(0.0, 0.05, p1_M, 2)
        # p2 expected
        p2_M = 20_000 * 0.20 / 12
        p2_expected = self._expected_pot_series(0.0, 0.05, p2_M, 2)
        for y in range(2):
            with self.subTest(year=y):
                combined = p1_expected[y] + p2_expected[y]
                self.assertAlmostEqual(r["dc_pot"][y], combined, places=4)


class TestDcMonthlyCompoundPartialYear(unittest.TestCase):
    """
    Lock down `_dc_monthly_compound`'s partial-year scaling contract.

    When `_dc_monthly_compound(pot, r, M, fraction=f)` is called with
    `f < 1.0`, the helper must scale BOTH the growth AND the contributions
    to `round(12 * f)` months rather than the full twelve — so an
    edge-case partial-year-of-contributions caller pays interest for the
    right fraction of a year (the very bit that motivates this PR). The
    closed-form reference for `n = round(12 * f)` months is:

        pot_end = pot_start * (1 + r/12) ** n
                + M * ((1 + r/12) ** n - 1) / (r/12)        (r ≠ 0)
        pot_end = pot_start + n * M                          (r == 0)

    Mirrors the partial-year scaling that was rolled into mortgage
    amortisation in step 4 (where a 9y6m mortgage ends mid-year-9).

    Engine-level BC is NOT covered by this class — the engine caller in
    step 2a/2b passes three positional args and relies on the implicit
    default `fraction=1.0`, so it does not exercise the partial-year
    branch. The e2e BC guarantee for `run_simulation` output lives in
    `TestEngineDcEndToEnd` above (e.g. `test_ten_year_pct_path_matches_
    closed_form`), which measures the full engine dc_pot series against
    the 12-month closed form with `places=4`. Any unintended drift in
    the default-fraction path would be caught there.
    """

    @staticmethod
    def _closed_form_n(pot_start, r, M, n_months):
        """Annuity-due closed form for `n_months` months, with r==0 limit."""
        if r == 0:
            return pot_start + n_months * M
        r_m = r / 12
        return pot_start * (1 + r_m) ** n_months + M * ((1 + r_m) ** n_months - 1) / r_m

    def test_default_fraction_is_one_year_twelve_months(self):
        # BC regression guard. Engine caller relies on the implicit default.
        # Default must equal explicit fraction=1.0 EXACTLY (bit-identical),
        # not just numerically approximate — post-PR the loop is
        # `range(round(12 * 1.0))` which equals `range(12)` and runs the
        # same per-step ops on the same operands in the same order as
        # pre-PR, so the floats should match exactly. Using `assertEqual`
        # catches ANY accidental reordering inside the helper that
        # `assertAlmostEqual(places=6)` would let slip past. Three
        # fixtures covering distinct parameter shapes (different rate,
        # different M, different starting pot) so a reordering bug that
        # numerically happens to cancel for one triple but not others
        # is still caught.
        for pot, M, r in [
            (10_000.0, 500.0, 0.05),
            (50_000.0,    0.0, 0.10),  # no contribution, higher rate
            (1_000.0,  250.0, 0.03),   # different shape
        ]:
            with self.subTest(pot=pot, M=M, r=r):
                self.assertEqual(
                    _dc_monthly_compound(pot, r, M),  # implicit default
                    _dc_monthly_compound(pot, r, M, fraction=1.0),
                )

    def test_zero_fraction_returns_input_unchanged(self):
        # fraction<=0 short-circuits before the loop so callers can skip
        # the year's step entirely. The pot must come back UNCHANGED
        # (no growth, no contribution landed, no NaN, no crash).
        self.assertEqual(
            _dc_monthly_compound(987.654, 0.05, 500.0, fraction=0.0),
            987.654,
        )
        self.assertEqual(
            _dc_monthly_compound(0.0, 0.05, 0.0, fraction=0.0),
            0.0,
        )
        # Negative fraction: also short-circuits, also unchanged.
        self.assertEqual(
            _dc_monthly_compound(500.0, 0.05, 100.0, fraction=-0.5),
            500.0,
        )

    def test_half_year_fraction_compounds_six_months(self):
        # The headline use case: contributing only the first half of the
        # year. fraction=0.5 → 6 closed-form months.
        pot, M, r = 10_000.0, 500.0, 0.05
        actual = _dc_monthly_compound(pot, r, M, fraction=0.5)
        expected = self._closed_form_n(pot, r, M, n_months=6)
        self.assertAlmostEqual(actual, expected, places=6)
        # Sanity: half-year pot must be STRICTLY less than the full-year
        # pot (growth has had only six months to compound) and STRICTLY
        # greater than just adding six months of contribution with no
        # growth (the opening balance earns six months of interest).
        full_year = _dc_monthly_compound(pot, r, M, fraction=1.0)
        six_months_no_growth = pot + 6 * M
        self.assertLess(actual, full_year)
        self.assertGreater(actual, six_months_no_growth)

    def test_quarter_year_fraction_compounds_three_months(self):
        # Three months of growth + three months of contributions. The
        # closed-form handles both terms (compound + annuity) independently.
        M, r = 500.0, 0.05
        actual = _dc_monthly_compound(0.0, r, M, fraction=0.25)
        expected = self._closed_form_n(0.0, r, M, n_months=3)
        self.assertAlmostEqual(actual, expected, places=6)

    def test_partial_year_zero_rate_no_div_by_zero(self):
        # Critical regression guard, scaled to partial years: the closed-
        # form term `((1+r/12)**n - 1)/(r/12)` is 0/0 at r=0. The
        # iteration helper must avoid it via `pot = pot + M` each step,
        # so `pot_end == pot_start + n_months * M` for every fraction.
        pot, M = 10_000.0, 500.0
        for fraction, n_months in [
            (0.25, 3), (0.5, 6), (0.75, 9), (1.0, 12),
        ]:
            with self.subTest(fraction=fraction):
                actual = _dc_monthly_compound(pot, 0.0, M, fraction=fraction)
                self.assertAlmostEqual(actual, pot + n_months * M, places=6)

    def test_partial_year_zero_contribution_is_partial_compound_only(self):
        # M=0 + partial fraction → pure compound interest for `n_months`
        # months, no annuity accumulation term. The closed-form collapses
        # cleanly: `pot_start * (1 + r/12)**n_months`.
        pot, r = 10_000.0, 0.05
        for fraction, n_months in [(0.25, 3), (0.5, 6), (0.75, 9)]:
            with self.subTest(fraction=fraction):
                actual = _dc_monthly_compound(pot, r, 0.0, fraction=fraction)
                expected = pot * (1 + r / 12) ** n_months
                self.assertAlmostEqual(actual, expected, places=6)

    def test_sweep_matches_closed_form_across_realistic_fractions(self):
        # Convenience sweep: a future caller could plausibly pass any of
        # these fractions (half-month, quarter-year, half-year, custom
        # 0.5833, three-quarter, two-thirds-ish, full-year). All must
        # match the closed-form for their `round(12*f)` month slice.
        # Precision bumped to `places=6` (matches the rest of this class)
        # since FP drift over 12 months is well below 1e-9.
        pot, M, r = 10_000.0, 500.0, 0.05
        for fraction in [1/12, 0.25, 0.5, 0.5833, 0.75, 0.9167, 1.0]:
            with self.subTest(fraction=fraction):
                actual = _dc_monthly_compound(pot, r, M, fraction=fraction)
                n_months = round(12 * fraction)
                expected = self._closed_form_n(pot, r, M, n_months=n_months)
                self.assertAlmostEqual(actual, expected, places=6)

    def test_partial_year_negative_rate_no_crash(self):
        # Regression guard on the negative-rate path, scaled to half-year.
        # Drawdown-year scenarios or future Monte-Carlo tail-year samples
        # could pass r<0 here; the helper must not raise.
        pot, M = 1_000.0, 100.0
        actual = _dc_monthly_compound(pot, -0.02, M, fraction=0.5)
        expected = self._closed_form_n(pot, -0.02, M, n_months=6)
        self.assertIsInstance(actual, float)
        self.assertGreater(actual, 0.0)
        self.assertAlmostEqual(actual, expected, places=6)

    def test_partial_year_pot_grows_monotonically_with_fraction(self):
        # Defensive sanity: for fixed (pot, r, M>0), increasing the
        # fraction from 0 → 1 strictly grows the result. Catches a
        # regression where someone accidentally transposes growth vs
        # contribution scaling in the partial-year branch.
        pot, M, r = 10_000.0, 500.0, 0.05
        results = [
            _dc_monthly_compound(pot, r, M, fraction=f)
            for f in [0.0, 0.0833, 0.25, 0.5, 0.75, 1.0]
        ]
        for prev, nxt in zip(results, results[1:]):
            self.assertLess(
                prev, nxt,
                msg=f"Partial-year pot must grow monotonically: "
                    f"{prev:.4f} >= {nxt:.4f}",
            )


if __name__ == "__main__":
    unittest.main()
