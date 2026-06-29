"""
Regression tests for the wage-inflation indexing of `earned_income`.

The engine produces `results["earned_income"][y] = sum over partners of
`person.income_until_retirement * (1 + person.income_growth_rate) ** y`,
clamped to 0 from retirement onwards. This module locks the math down at
two layers:

  1. _indexed_earned_income   — closed-form pure helper, no engine state.
  2. End-to-end run_simulation — full engine result series across both
                                 partners, including retirement edge cases.

The closed-form reference used throughout:

    earned(y) = base * (1 + r) ** y       while (age + y) < retirement_age
    earned(y) = 0                          otherwise

where `base` is `income_until_retirement` and `r` is `income_growth_rate`.
A refactor to this formula (e.g. switching the exponent base, switching the
retirement comparison, or changing the anchored year) should be caught here.
"""

import unittest

from simulation.engine import _indexed_earned_income, run_simulation
from models.person import Person
from models.household import Household


def _make_person(
    age=40,
    retirement_age=80,
    income_until_retirement=0.0,
    income_growth_rate=0.025,
    **kwargs,
):
    """Build a Person with only the fields relevant to earned_income tests
    pre-filled; pass any extras through to override."""
    defaults = dict(
        name="T",
        age=age,
        retirement_age=retirement_age,
        state_pension_age=99,
        dc_pot=0.0,
        db_income=0.0,
        monthly_contrib=0.0,
        income_until_retirement=income_until_retirement,
        draw_age=99,
        pcls_percent=0,
        income_growth_rate=income_growth_rate,
        monthly_contrib_pct=0.0,
        dc_growth_rate=0.0,
        db_growth_rate=0.0,
        state_pension_growth_rate=0.0,
    )
    defaults.update(kwargs)
    return Person(**defaults)


class TestIndexedEarnedIncomeUnit(unittest.TestCase):
    """Pure helper tests against the closed-form reference."""

    # ---- baseline / year-zero ---------------------------------------------

    def test_year_zero_is_base_income_unindexed(self):
        # Year 0 must equal the base figure exactly. This is the canonical
        # "today's salary" anchor that all future years compound from.
        p = _make_person(income_until_retirement=60_000.0, income_growth_rate=0.025)
        self.assertAlmostEqual(_indexed_earned_income(p, 0), 60_000.0, places=6)

    def test_year_zero_with_zero_growth_is_base(self):
        # The growth rate being 0 must NOT collapse year-0 to anything
        # other than the base figure.
        p = _make_person(income_until_retirement=45_000.0, income_growth_rate=0.0)
        self.assertAlmostEqual(_indexed_earned_income(p, 0), 45_000.0, places=6)

    # ---- compounding ------------------------------------------------------

    def test_year_one_is_base_plus_growth(self):
        # (1+r)^1 = 1+r, so year 1 should equal base * (1+r).
        p = _make_person(income_until_retirement=60_000.0, income_growth_rate=0.05)
        self.assertAlmostEqual(_indexed_earned_income(p, 1), 60_000.0 * 1.05, places=6)

    def test_year_n_compounds_exponentially(self):
        # Year N should equal base * (1+r)^N — direct closed-form check.
        p = _make_person(income_until_retirement=80_000.0, income_growth_rate=0.025)
        for y in range(15):
            with self.subTest(year=y):
                expected = 80_000.0 * (1.025 ** y)
                self.assertAlmostEqual(
                    _indexed_earned_income(p, y), expected, places=4,
                    msg=f"Y{y}: _indexed={_indexed_earned_income(p, y):.4f} "
                        f"expected={expected:.4f}",
                )

    def test_zero_growth_rate_is_flat_until_retirement(self):
        # r=0 must be a flat line until retirement, NOT immediately retire
        # the partner.
        p = _make_person(
            income_until_retirement=50_000.0,
            income_growth_rate=0.0,
            retirement_age=80,
        )
        for y in range(11):
            with self.subTest(year=y):
                self.assertEqual(_indexed_earned_income(p, y), 50_000.0)

    # ---- retirement boundary ---------------------------------------------

    def test_returns_zero_from_retirement_age_year_onwards(self):
        # Lockdown for the "stops at retirement" half of the formula.
        # Person aged 40, retiring at 60: years 0..19 should earn
        # compounded income; year 20 onwards (= retirement_age - age) must
        # be 0.
        p = _make_person(
            age=40, retirement_age=60,
            income_until_retirement=50_000.0, income_growth_rate=0.025,
        )
        # Just before retirement
        self.assertAlmostEqual(
            _indexed_earned_income(p, 19), 50_000.0 * (1.025 ** 19), places=4,
        )
        # At and after retirement
        for y in (20, 21, 30, 100):
            with self.subTest(year=y):
                self.assertEqual(_indexed_earned_income(p, y), 0.0)

    def test_zero_retirement_age_means_income_zero_even_year_zero(self):
        # Edge case: retirement_age == age => is retired at year 0.
        p = _make_person(
            age=65, retirement_age=65,
            income_until_retirement=99_999.0, income_growth_rate=0.05,
        )
        for y in range(5):
            with self.subTest(year=y):
                self.assertEqual(_indexed_earned_income(p, y), 0.0)

    # ---- degenerate / robustness inputs ----------------------------------

    def test_zero_base_income_is_zero_forever(self):
        # If there's no income, nothing compounds.
        p = _make_person(income_until_retirement=0.0, income_growth_rate=0.05)
        for y in range(10):
            with self.subTest(year=y):
                self.assertEqual(_indexed_earned_income(p, y), 0.0)

    def test_negative_growth_does_not_crash(self):
        # Wage deflation in stress-test scenarios. Should produce a
        # strictly lower (positive) figure at year N, not raise.
        p = _make_person(income_until_retirement=60_000.0, income_growth_rate=-0.02)
        for y in range(5):
            with self.subTest(year=y):
                value = _indexed_earned_income(p, y)
                self.assertIsInstance(value, float)
                expected = 60_000.0 * ((1 - 0.02) ** y)
                self.assertAlmostEqual(value, expected, places=6)
                self.assertGreater(value, 0.0)

    def test_person_already_past_retirement_year_zero_is_zero(self):
        # Negative year_offset wouldn't happen in our loop (year starts at 0),
        # but defensive: is_retired(0) = True when age >= retirement_age =>
        # earned_income[0] must be 0, not the base figure.
        p = _make_person(
            age=70, retirement_age=60,
            income_until_retirement=40_000.0, income_growth_rate=0.025,
        )
        self.assertEqual(_indexed_earned_income(p, 0), 0.0)


class TestEngineEarnedIncomeEndToEnd(unittest.TestCase):
    """
    Lock down that the engine's `results["earned_income"]` series exactly
    tracks the summation of `_indexed_earned_income(person, y)` over both
    partners through the simulation horizon.
    """

    def _household(self, years, p1=None, p2=None):
        if p1 is None:
            p1 = _make_person()
        if p2 is None:
            p2 = _make_person(
                income_until_retirement=0.0,
                income_growth_rate=0.0,
                retirement_age=99,
            )
        return Household(
            person1=p1, person2=p2, assets=[], mortgage=None,
            spending_target=0, events=[],
        ), years

    def _expected_series(self, persons, years):
        out = []
        for y in range(years):
            out.append(sum(_indexed_earned_income(p, y) for p in persons))
        return out

    # ---- single-partner paths --------------------------------------------

    def test_single_partner_no_retirement_matches_closed_form(self):
        # 12-year run, never retired, 2.5% indexation. Earned income must
        # equal base * (1.025)^y every year.
        p1 = _make_person(
            age=40, retirement_age=99,
            income_until_retirement=60_000.0, income_growth_rate=0.025,
        )
        h, years = self._household(12, p1=p1)
        r = run_simulation(h, years=years)
        expected = self._expected_series([p1], years)
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(
                    r["earned_income"][y], exp, places=4,
                    msg=f"Y{y}: engine={r['earned_income'][y]:.4f} vs {exp:.4f}",
                )

    def test_single_partner_retires_at_year_10_drops_to_zero(self):
        # Age 40, retirement 50 → 10 working years then flat zero. Precisely
        # year 10 must be 0 (NOT last indexed value).
        p1 = _make_person(
            age=40, retirement_age=50,
            income_until_retirement=80_000.0, income_growth_rate=0.025,
        )
        h, years = self._household(15, p1=p1)
        r = run_simulation(h, years=years)
        for y in range(10):
            with self.subTest(year=y, when="pre-retirement"):
                expected = 80_000.0 * (1.025 ** y)
                self.assertAlmostEqual(r["earned_income"][y], expected, places=4)
        for y in range(10, 15):
            with self.subTest(year=y, when="post-retirement"):
                self.assertEqual(r["earned_income"][y], 0.0)

    def test_zero_growth_end_to_end_is_constant(self):
        # r=0, 8 working years → flat 50k every year.
        p1 = _make_person(
            age=40, retirement_age=60,
            income_until_retirement=50_000.0, income_growth_rate=0.0,
        )
        h, years = self._household(8, p1=p1)
        r = run_simulation(h, years=years)
        for y in range(8):
            with self.subTest(year=y):
                self.assertEqual(r["earned_income"][y], 50_000.0)

    def test_zero_income_partner_yields_zero_earned_income(self):
        # Both partners with 0 income → earned_income is identically 0
        # regardless of growth rates set.
        p1 = _make_person(
            age=40, retirement_age=60,
            income_until_retirement=0.0, income_growth_rate=0.05,
        )
        p2 = _make_person(
            age=40, retirement_age=60,
            income_until_retirement=0.0, income_growth_rate=0.05,
        )
        h, years = self._household(10, p1=p1, p2=p2)
        r = run_simulation(h, years=years)
        for y in range(10):
            with self.subTest(year=y):
                self.assertEqual(r["earned_income"][y], 0.0)

    # ---- two-partner paths -----------------------------------------------

    def test_two_partners_sum_indexed_incomes(self):
        # Both partners working, different bases and growth rates → sum.
        p1 = _make_person(
            age=40, retirement_age=70,
            income_until_retirement=50_000.0, income_growth_rate=0.025,
        )
        p2 = _make_person(
            age=40, retirement_age=65,
            income_until_retirement=40_000.0, income_growth_rate=0.04,
        )
        h, years = self._household(12, p1=p1, p2=p2)
        r = run_simulation(h, years=years)
        expected = self._expected_series([p1, p2], years)
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                # p2 retires at year 25 (age 65) — within our 12-year run
                # both are still working; sum should be additive.
                self.assertAlmostEqual(r["earned_income"][y], exp, places=4)
        # Sanity: total at year 11 must STRICTLY EXCEED year 0 sum
        # because both partners are growing.
        self.assertGreater(r["earned_income"][11], r["earned_income"][0])

    def test_different_retirement_ages_one_drops_first(self):
        # p1 retires at year 5, p2 keeps working through year 10.
        # After year 5 the series must collapse to p2 alone.
        p1 = _make_person(
            age=40, retirement_age=45,
            income_until_retirement=60_000.0, income_growth_rate=0.025,
        )
        p2 = _make_person(
            age=40, retirement_age=60,
            income_until_retirement=30_000.0, income_growth_rate=0.025,
        )
        h, years = self._household(10, p1=p1, p2=p2)
        r = run_simulation(h, years=years)
        # Pre-retirement window: full sum.
        for y in range(5):
            with self.subTest(year=y, when="both working"):
                expected_p1 = 60_000.0 * (1.025 ** y)
                expected_p2 = 30_000.0 * (1.025 ** y)
                self.assertAlmostEqual(
                    r["earned_income"][y], expected_p1 + expected_p2, places=4,
                )
        # Post retirement of p1 — only p2 contributes.
        for y in range(5, 10):
            with self.subTest(year=y, when="only p2"):
                expected_p2 = 30_000.0 * (1.025 ** y)
                self.assertAlmostEqual(r["earned_income"][y], expected_p2, places=4)

    def test_both_retire_at_end_of_horizon_yields_zero_after(self):
        # Run the horizon past both retirements to confirm the tail
        # remains strictly 0 (no leakage of un-indexed value).
        p1 = _make_person(
            age=40, retirement_age=45,
            income_until_retirement=45_000.0, income_growth_rate=0.025,
        )
        p2 = _make_person(
            age=40, retirement_age=47,
            income_until_retirement=35_000.0, income_growth_rate=0.025,
        )
        h, years = self._household(12, p1=p1, p2=p2)
        r = run_simulation(h, years=years)
        for y in (7, 8, 9, 10, 11):  # well past both retirements
            with self.subTest(year=y):
                self.assertEqual(r["earned_income"][y], 0.0)

    # ---- behavioural coupling --------------------------------------------

    def test_earned_income_drives_pct_dc_contribution_correctly(self):
        """
        The whole point of `earned_income`: it's also the anchor for the
        `% of income` monthly DC contribution. If `earned_income` ever
        diverges from the closed-form indexation, the M_y values fed into
        the monthly compound test would drift too — so this end-to-end
        test cross-checks both layers.
        """
        p1 = _make_person(
            age=30, retirement_age=99,
            income_until_retirement=50_000.0, income_growth_rate=0.025,
            monthly_contrib_pct=0.15, dc_growth_rate=0.05,
        )
        p2 = _make_person(
            age=30, retirement_age=99,
            income_until_retirement=0.0,  # silent partner
            income_growth_rate=0.025,
        )
        h, years = self._household(6, p1=p1, p2=p2)
        r = run_simulation(h, years=years)

        expected_earned = [
            50_000.0 * (1.025 ** y) for y in range(6)
        ]
        for y, exp in enumerate(expected_earned):
            with self.subTest(year=y):
                self.assertAlmostEqual(r["earned_income"][y], exp, places=4)
                # Cross-check: M_y = earned_y * 0.15 / 12
                M_y = exp * 0.15 / 12
                # DC pot after year y compounds: pot_{y-1} * (1+r/12)^12
                # + M_y * annuity_factor. Using the same constants as
                # test_dc_compound.py: r_m = 0.05/12.
                r_m = 0.05 / 12
                growth_factor = (1 + r_m) ** 12
                annuity_factor = (growth_factor - 1) / r_m
                expected_pot = 0.0
                for inner_y in range(y + 1):
                    inner_M = 50_000.0 * (1.025 ** inner_y) * 0.15 / 12
                    expected_pot = (
                        expected_pot * growth_factor + inner_M * annuity_factor
                    )
                self.assertAlmostEqual(
                    r["dc_pot"][y], expected_pot, places=4,
                    msg=f"Y{y}: dc_pot drift implies earned_income drift",
                )


if __name__ == "__main__":
    unittest.main()
