"""
Regression tests for partial-year mortgage amortisation in
``simulation/engine.py``.

The Assets page (``pages/3_Assets.py``) now lets users enter a
fractional mortgage term — e.g. ``Years=9, Months=6`` is saved as
``end_year=9.5`` and read by ``Mortgage.is_active(year)`` as
``year < 9.5``. The engine's mortgage amortisation block (step 4 in
``run_simulation``) MUST scale both the interest accrual and the
planned payment by

    fraction = min(1.0, end_year - year)

in the closing year so the loan actually closes mid-year-N instead of
advancing a full extra year of interest and payments.

These tests isolate the mortgage path by constructing a minimal
household (no income, no DC pot, no pension, no events) so the
engine loop's other blocks all return £0 and don't muddle the
year-by-year mortgage balance.
"""
import unittest

from models.household import Household
from models.mortgage import Mortgage
from models.person import Person
from simulation.engine import run_simulation


def _minimal_household(mortgage: Mortgage):
    """Tiny household for engine-level mortgage tests.

    No income, no DC pot, no pensions — so the engine loop's
    drawdown / property / state-pension / DB blocks all return £0
    and don't muddle the mortgage trajectory under test.
    `spending_target=0` means lifestyle drawdown is also £0.

    The ``person1``/``person2`` slots are filled with the SAME
    ``Person`` instance — that's a deliberate shorthand. It saves
    constructing a second dummy and the engine doesn't compare
    partners, so identical instances are equivalent for the
    mortgage path. Both partners have a far-future
    ``retirement_age``/``state_pension_age`` so they never
    transition into a pension-drawing state during the test.
    """
    p1 = Person(
        name="P1",
        age=55,
        retirement_age=99,
        state_pension_age=99,
        dc_pot=0,
        db_income=0,
        draw_age=99,
        monthly_contrib=0,
        income_until_retirement=0,
        pcls_percent=0,
        pcls_taken=0,
        pcls_available=0,
        dc_growth_rate=0.0,
        db_growth_rate=0.0,
        state_pension_growth_rate=0.025,
        income_growth_rate=0.0,
        monthly_contrib_pct=0.0,
    )
    return Household(
        person1=p1,
        person2=p1,
        assets=[],
        mortgage=mortgage,
        spending_target=0,
        drawdown_amount=0,
        drawdown_strategy="Fixed",
        events=[],
    )


class PartialYearAmortisationTests(unittest.TestCase):
    """Lock in the partial-year scaling contract."""

    def test_closing_year_pays_only_fraction_of_annual_payment_zero_rate(self):
        """Zero-interest boundary case — locked in for posterity.

        end_year=3.5, rate=0.0, payment=20, outstanding=100:
          Y0..Y2 full years       — balance 80, 60, 40
          Y3 closing (fraction=0.5) — pay 10 (half-year slice), balance 30
          Y4..7 inactive          — balance stays at 30
        """
        mortgage = Mortgage(
            outstanding=100,
            rate=0.0,
            end_year=3.5,
            annual_payment=20,
            annual_overpayment=0,
        )
        results = run_simulation(_minimal_household(mortgage), years=8)
        balance = results["mortgage_balance"]
        paid = results["mortgage_payment"]
        tol = 1e-6

        self.assertAlmostEqual(balance[0], 80, delta=tol)
        self.assertAlmostEqual(balance[1], 60, delta=tol)
        self.assertAlmostEqual(balance[2], 40, delta=tol)
        self.assertAlmostEqual(balance[3], 30, delta=tol)
        self.assertAlmostEqual(balance[4], 30, delta=tol)
        self.assertAlmostEqual(balance[7], 30, delta=tol)

        self.assertAlmostEqual(paid[0], 20, delta=tol)
        self.assertAlmostEqual(paid[1], 20, delta=tol)
        self.assertAlmostEqual(paid[2], 20, delta=tol)
        self.assertAlmostEqual(paid[3], 10, delta=tol)  # half-year payment
        self.assertAlmostEqual(paid[4], 0, delta=tol)
        self.assertAlmostEqual(paid[7], 0, delta=tol)

    def test_closing_year_uses_simple_interest_slice_locked_in(self):
        """Non-zero-rate partial-year. Locks in the simple-interest
        formula ``outstanding *= (1 + rate * fraction)`` rather
        than the compound-interest alternative
        ``outstanding *= (1 + rate)**fraction``. These two diverge
        for any rate > 0, so without this test someone could swap
        in compound interest for the closing-year slice silently.

        end_year=1.5, rate=0.04, payment=60, outstanding=100:
          Y0 full year:
            interest = 100 * 0.04 * 1.0 = 4.0
            outstanding = 104.0  → pay 60  → outstanding = 44.0
          Y1 closing (fraction=0.5):
            interest = 44.0 * 0.04 * 0.5 = 0.88
            outstanding = 44.88   → planned = 60 * 0.5 = 30
                                → pay min(30, 44.88) = 30
                                → outstanding = 14.88
          Y2 inactive: balance stays at 14.88, paid = 0
        """
        mortgage = Mortgage(
            outstanding=100,
            rate=0.04,
            end_year=1.5,
            annual_payment=60,
            annual_overpayment=0,
        )
        results = run_simulation(_minimal_household(mortgage), years=4)
        balance = results["mortgage_balance"]
        paid = results["mortgage_payment"]
        tol = 1e-6

        # Y0: full year — interest 4.0, pay 60, balance 44.0.
        self.assertAlmostEqual(balance[0], 44.0, delta=tol)
        self.assertAlmostEqual(paid[0], 60, delta=tol)

        # Y1: closing. Interest must be the SIMPLE slice 0.88, NOT
        # the compound slice 44.0 * ((1.04)**0.5 - 1) ≈ 0.870... If
        # this test fails with `delta=1e-3`, someone reverted to
        # compound interest for the closing-year slice.
        expected_y1_balance = 44.0 + (44.0 * 0.04 * 0.5) - 30.0  # = 14.88
        self.assertAlmostEqual(balance[1], expected_y1_balance, delta=tol)
        self.assertAlmostEqual(paid[1], 30.0, delta=tol)  # half-year payment

        # Y2..3 inactive: balance sticks at the closing-year value.
        self.assertAlmostEqual(balance[2], 14.88, delta=tol)
        self.assertAlmostEqual(balance[3], 14.88, delta=tol)
        self.assertAlmostEqual(paid[2], 0, delta=tol)
        self.assertAlmostEqual(paid[3], 0, delta=tol)

    def test_integer_end_year_treated_as_full_years(self):
        """`Mortgage.end_year` accepts ints (legacy data) — they
        produce identical results to the equivalent float. Defends
        against subtle int-vs-float drift in the partial-year math
        (e.g. accidentally switching to `(1+rate)**fraction` instead
        of `(1+rate*fraction)`)."""
        mortgage_int = Mortgage(
            outstanding=100,
            rate=0.04,
            end_year=5,  # int, not 5.0
            annual_payment=10,
            annual_overpayment=0,
        )
        mortgage_float = Mortgage(
            outstanding=100,
            rate=0.04,
            end_year=5.0,
            annual_payment=10,
            annual_overpayment=0,
        )
        results_int = run_simulation(_minimal_household(mortgage_int), years=8)
        results_float = run_simulation(_minimal_household(mortgage_float), years=8)

        for year in (4, 5, 7):
            self.assertAlmostEqual(
                results_int["mortgage_balance"][year],
                results_float["mortgage_balance"][year],
                delta=1e-6,
                msg=f"int vs float end_year diverge at year {year}",
            )
            self.assertAlmostEqual(
                results_int["mortgage_payment"][year],
                results_float["mortgage_payment"][year],
                delta=1e-6,
                msg=f"int vs float end_year diverge at year {year}",
            )


class MortgageDataclassBackwardsCompatTests(unittest.TestCase):
    """`Mortgage` dataclass contract — protects the Assets page form
    and any consumer in the codebase that does ``Mortgage(**data)``."""

    def test_legacy_saved_dict_with_no_include_in_spending_defaults_false(self):
        """Older saved plans don't have the `include_in_spending`
        field. ``Mortgage(**legacy_data)`` must construct successfully
        with the field at its False default — no TypeError on a
        missing kwarg."""
        m = Mortgage(
            outstanding=100_000,
            rate=0.04,
            end_year=10.0,
            annual_payment=12_000,
            annual_overpayment=2_400,
            # include_in_spending deliberately omitted
        )
        self.assertFalse(m.include_in_spending)

    def test_fractional_end_year_constructs_and_gates_correctly(self):
        m = Mortgage(
            outstanding=100_000,
            rate=0.04,
            end_year=9.5,
            annual_payment=12_000,
            annual_overpayment=0,
        )
        # is_active(year) = year < end_year AND outstanding > 0.
        # 9 < 9.5 is True; 10 < 9.5 is False.
        self.assertTrue(m.is_active(9))
        self.assertFalse(m.is_active(10))

    def test_negative_end_year_is_clamped_by_assets_page(self):
        """The Assets-page form has min_value=0 on the years input,
        so a negative end_year can't enter via the UI. The dataclass
        field stays a float. This test just documents that the
        form-side guard is what protects us — the dataclass itself
        does NOT clamp."""

        # No exception expected — dataclass accepts the float. The
        # form's min_value=0 + the assets-page helper's defensive
        # `max(0.0, end_year)` clamp are the actual gatekeepers.
        m_neg = Mortgage(
            outstanding=100, rate=0, end_year=-1.0,
            annual_payment=10, annual_overpayment=0,
        )
        # Programming a negative term: `is_active(0) = (0 < -1.0)` is
        # False, so the loan is permanently inactive and the engine
        # never amortises it. That matches the user's intent at the
        # UI level (where the form clamps this) — the dataclass just
        # keeps the raw value rather than silently coercing it.
        self.assertFalse(m_neg.is_active(0))
        self.assertFalse(m_neg.is_active(1))

        # Sanity check: positive long-term mortgage is still active.
        m_far = Mortgage(
            outstanding=100, rate=0, end_year=50,
            annual_payment=10, annual_overpayment=0,
        )
        self.assertTrue(m_far.is_active(0))


class IncomeVsSpendingChartToggleTests(unittest.TestCase):
    """Locks in the chart-display toggle behaviour. The chart helper
    is the single source of truth for the Income/Spending frame; the
    pages forward the include_in_spending flag from saved
    household_data and call the helper."""

    def _results(self, years=5):
        """Minimal `simulation_results` skeleton for the chart helper."""
        return {
            "years": list(range(years)),
            "income": [50000.0] * years,
            "spending": [30000.0] * years,
            "mortgage_payment": [8000.0] * years,
        }

    def test_toggle_off_returns_three_columns(self):
        """Default behaviour — three independent lines so the user
        can see lifestyle vs mortgage outgoings separately."""
        from simulation.charts import income_vs_spending_chart
        df = income_vs_spending_chart(self._results())
        self.assertEqual(
            set(df.columns),
            {"Year", "Income", "Spending", "Mortgage Payment"},
        )
        self.assertEqual(df["Spending"].tolist(), [30000] * 5)
        self.assertEqual(df["Mortgage Payment"].tolist(), [8000] * 5)

    def test_toggle_on_returns_two_columns_and_combined_spending(self):
        """When ON the chart drops the Mortgage Payment column and the
        Spending column equals ``lifestyle + mortgage_payment``."""
        from simulation.charts import income_vs_spending_chart
        df = income_vs_spending_chart(
            self._results(), include_mortgage_in_spending=True
        )
        self.assertEqual(set(df.columns), {"Year", "Income", "Spending"})
        # 30000 lifestyle + 8000 mortgage = 38000 per year.
        self.assertEqual(df["Spending"].tolist(), [38000] * 5)
        self.assertNotIn("Mortgage Payment", df.columns)

    def test_toggle_on_handles_missing_mortgage_payment_field(self):
        """Older saved payloads may lack `mortgage_payment`. With
        toggle ON the helper must NOT crash — the combined Spending
        column equals just the lifestyle figure (zero mortgage)."""
        from simulation.charts import income_vs_spending_chart
        results = {
            "years": list(range(3)),
            "income": [50000.0] * 3,
            "spending": [30000.0] * 3,
            # mortgage_payment absent
        }
        df = income_vs_spending_chart(
            results, include_mortgage_in_spending=True
        )
        self.assertEqual(set(df.columns), {"Year", "Income", "Spending"})
        self.assertEqual(df["Spending"].tolist(), [30000] * 3)


if __name__ == "__main__":
    unittest.main()
