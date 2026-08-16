"""Regression tests for the "Show in today's value" engine mode.

Locked-down invariants
=====================
The household `show_in_todays_value` flag (default False) propagates
through `simulation/engine.py::run_simulation` via
`simulation/today_value.py` rate transforms. When the flag is ON,
every growth-rate path switches to a "real" rate so the entire
projection is in TODAY's purchasing power. Specifically:

  - DB pension growth           → 0%   (payouts stay flat at year-0 base)
  - State Pension growth        → 0%   (stays flat at FULL_STATE_PENSION)
  - DC pot growth               → nominal - inflation (simple subtraction)
  - Asset growth (ISA/GIA/Cash) → nominal - inflation (simple subtraction)
  - Asset growth (Property)     → 0%   (zeroed, NOT deflated)
  - Wage curve                  → nominal - inflation (simple subtraction)
  - Mortgage interest           → UNCHANGED (real rate in both modes)
  - Spending (Inflation-adjusted
    and Tapered strategies)     → flat base, no `(1+inf)**year` uplift

Math convention: SIMPLE SUBTRACTION (not Fischer's equation). The
user's mental model is "7% nominal at 2.5% inflation = 4.5% in
today's money", which is `nominal - inflation` not
`(1+nominal) / (1+inflation) - 1`. Simple subtraction also
matches the engine's existing 2.5% hardcoded inflation
assumption across multiple code paths, so the math stays
consistent.

Index-versus-year note (the trap this suite was written to dodge)
==================================================================
The engine's year loop iterates K = 0..N-1. At iteration K the
engine:

  * Computes `spending = base * (1.025)^K` for the Inflation-
    adjusted strategy (so result[`spending`][K] = base * 1.025^K).
  * Applies asset growth (so result[`property_value`][K] =
    initial * (1+r)^(K+1), because K+1 multiplicative growth
    steps have happened by then).
  * Compounds DC pot monthly for 12 months (so result[`dc_pot`]
    [K] uses MONTHLY compounding, not annual).

So when a test asserts a year-N value, the precise expected
number depends on WHICH result series is being checked. The
test suite below uses ROOMY deltas and ratio assertions where
the exact period-by-period math is ambiguous (e.g. monthly DC
compounding), and PINs specific numbers only where the closed
form is unambiguous (e.g. Property at year 0 = initial value).
"""

from __future__ import annotations

import math
import unittest

from models.asset import Asset
from models.household import Household
from models.mortgage import Mortgage
from models.person import Person
from simulation.engine import run_simulation
from simulation.today_value import (
    effective_asset_growth,
    effective_db_growth,
    effective_dc_growth,
    effective_income_growth,
    effective_state_pension_growth,
    resolve_today_value_settings,
)


# ----------------------- Fixture builders -----------------------

def _build_baseline_household(
    *,
    show_in_todays_value: bool = False,
    strategy: str = "Fixed",
    spending_target: float = 30_000.0,
    life_expectancy_end_age: float = 75.0,
) -> Household:
    """Single-shape household fixture for the test class.

    Both partners aged 55 → 60 retirement → 60 DB draw → 67 State
    Pension start. Long-lived enough to capture every per-year
    transformation the engine performs (income → DB → SP →
    spending → assets → drawdown).
    """
    p1 = Person(
        name="Dave",
        age=55.0,
        retirement_age=60.0,
        state_pension_age=67.0,
        dc_pot=100_000.0,
        income_until_retirement=50_000.0,
        db_income=10_000.0,
        draw_age=60.0,
        pcls_percent=0,
        dc_growth_rate=0.07,
        db_growth_rate=0.025,
        state_pension_growth_rate=0.025,
        income_growth_rate=0.025,
        monthly_contrib=0.0,
        monthly_contrib_pct=0.0,
    )
    p2 = Person(
        name="Shaz",
        age=55.0,
        retirement_age=60.0,
        state_pension_age=67.0,
        dc_pot=50_000.0,
        income_until_retirement=30_000.0,
        db_income=5_000.0,
        draw_age=60.0,
        pcls_percent=0,
        dc_growth_rate=0.05,
        db_growth_rate=0.025,
        state_pension_growth_rate=0.025,
        income_growth_rate=0.025,
        monthly_contrib=0.0,
        monthly_contrib_pct=0.0,
    )
    assets = [
        Asset(name="ISA", value=50_000.0, growth_rate=0.05, asset_type="ISA"),
        Asset(name="GIA", value=20_000.0, growth_rate=0.04, asset_type="GIA"),
        Asset(name="Cash", value=10_000.0, growth_rate=0.03, asset_type="Cash"),
        Asset(name="Property", value=400_000.0, growth_rate=0.02, asset_type="Property"),
    ]
    mortgage = Mortgage(
        outstanding=100_000.0,
        rate=0.0458,
        end_year=15.0,
        annual_payment=10_000.0,
        annual_overpayment=0.0,
    )
    return Household(
        person1=p1,
        person2=p2,
        assets=assets,
        mortgage=mortgage,
        spending_target=spending_target,
        drawdown_strategy=strategy,
        events=[],
        show_in_todays_value=show_in_todays_value,
        inflation_rate=0.025,
        life_expectancy_end_age=life_expectancy_end_age,
    )


# ----------------------- TodayValue helper unit tests -----------------------

class TestTodayValueHelpers(unittest.TestCase):
    """Module-level pure helpers — no Household required."""

    def test_resolve_settings_default_off_for_legacy_household(self):
        """Legacy `Household(...)` without the new fields reads
        `enabled=False` so back-compat with predating-JSON plans is
        preserved."""
        h = Household(
            person1=Person(name="a", age=55.0, retirement_age=60.0,
                           state_pension_age=67.0, dc_pot=0.0),
            person2=Person(name="b", age=55.0, retirement_age=60.0,
                           state_pension_age=67.0, dc_pot=0.0),
        )
        s = resolve_today_value_settings(h)
        self.assertEqual(s.enabled, False)
        self.assertEqual(s.inflation_rate, 0.025)

    def test_resolve_settings_with_today_value_on(self):
        """`show_in_todays_value=True` round-trips through
        `enabled=True`."""
        h = Household(
            person1=Person(name="a", age=55.0, retirement_age=60.0,
                           state_pension_age=67.0, dc_pot=0.0),
            person2=Person(name="b", age=55.0, retirement_age=60.0,
                           state_pension_age=67.0, dc_pot=0.0),
            show_in_todays_value=True,
            inflation_rate=0.03,
        )
        s = resolve_today_value_settings(h)
        self.assertEqual(s.enabled, True)
        self.assertEqual(s.inflation_rate, 0.03)

    def test_db_growth_zeros_in_today_value(self):
        """DB pension growth reduces to 0.0 in today's-value mode."""
        from simulation.today_value import TodayValueSettings
        s = TodayValueSettings(enabled=True, inflation_rate=0.025)
        self.assertEqual(effective_db_growth(s, 0.025), 0.0)
        self.assertEqual(effective_db_growth(s, 0.10), 0.0)
        s_off = TodayValueSettings(enabled=False, inflation_rate=0.025)
        self.assertEqual(effective_db_growth(s_off, 0.025), 0.025)

    def test_state_pension_growth_zeros_in_today_value(self):
        """State Pension growth reduces to 0.0 in today's-value mode."""
        from simulation.today_value import TodayValueSettings
        s = TodayValueSettings(enabled=True, inflation_rate=0.025)
        self.assertEqual(effective_state_pension_growth(s, 0.025), 0.0)
        s_off = TodayValueSettings(enabled=False, inflation_rate=0.025)
        self.assertEqual(effective_state_pension_growth(s_off, 0.025), 0.025)

    def test_dc_growth_uses_simple_subtraction(self):
        """User's example: 7% nominal at 2.5% inflation = 4.5% real
        via SIMPLE subtraction (not Fischer). Off → unchanged."""
        from simulation.today_value import TodayValueSettings
        s = TodayValueSettings(enabled=True, inflation_rate=0.025)
        self.assertAlmostEqual(effective_dc_growth(s, 0.07), 0.045)
        s_off = TodayValueSettings(enabled=False, inflation_rate=0.025)
        self.assertEqual(effective_dc_growth(s_off, 0.07), 0.07)

    def test_dc_growth_allows_negative_real_rates(self):
        """A 2% nominal with 3% inflation yields -1% real (NOT
        clamped). Real capital erosion is mathematically real and
        the user would be surprised by a silent clamp to 0."""
        from simulation.today_value import TodayValueSettings
        s = TodayValueSettings(enabled=True, inflation_rate=0.03)
        self.assertAlmostEqual(effective_dc_growth(s, 0.02), -0.01)

    def test_income_growth_uses_simple_subtraction(self):
        """A 2.5% nominal wage growth with 2.5% inflation yields
        exactly 0% real (wages stay flat in today's view)."""
        from simulation.today_value import TodayValueSettings
        s = TodayValueSettings(enabled=True, inflation_rate=0.025)
        self.assertAlmostEqual(effective_income_growth(s, 0.025), 0.0)
        s_off = TodayValueSettings(enabled=False, inflation_rate=0.025)
        self.assertEqual(effective_income_growth(s_off, 0.025), 0.025)

    def test_asset_growth_property_zeros_in_today_value(self):
        """Property asset growth rate is zeroed (NOT deflated) when
        today's-value is ON — per user: "the property value growth
        will not be applied"."""
        from simulation.today_value import TodayValueSettings
        s = TodayValueSettings(enabled=True, inflation_rate=0.025)
        self.assertEqual(effective_asset_growth(s, 0.02, "Property"), 0.0)
        self.assertEqual(effective_asset_growth(s, 0.05, "Property"), 0.0)

    def test_asset_growth_others_use_subtraction(self):
        """ISA / GIA / Cash follow the same simple-subtraction rule
        as DC growth."""
        from simulation.today_value import TodayValueSettings
        s = TodayValueSettings(enabled=True, inflation_rate=0.025)
        self.assertAlmostEqual(effective_asset_growth(s, 0.05, "ISA"), 0.025)
        self.assertAlmostEqual(effective_asset_growth(s, 0.04, "GIA"), 0.015)
        self.assertAlmostEqual(effective_asset_growth(s, 0.03, "Cash"), 0.005)

    def test_asset_growth_off_unchanged(self):
        """All asset types pass through unchanged when today's-value
        is OFF (legacy behaviour preserved)."""
        from simulation.today_value import TodayValueSettings
        s = TodayValueSettings(enabled=False, inflation_rate=0.025)
        self.assertEqual(effective_asset_growth(s, 0.02, "Property"), 0.02)
        self.assertEqual(effective_asset_growth(s, 0.05, "ISA"), 0.05)


# ----------------------- Today-value MATH invariants -----------------------
#
# Ratio-based assertions where exact numbers depend on monthly DC
# compounding or compounding-period details that are easy to write
# wrong. Each invariant asserts the structural shape the engine
# should produce under today's-value mode.

class TestEngineTodayValueInvariants(unittest.TestCase):
    """End-to-end shape invariants: turning the toggle flips
    which way the per-year series moves."""

    def test_inflation_adjusted_spending_stays_flat_in_today_value(self):
        """Inflation-adjusted = base * (1+0.025)^year OFF; base
        unchanged ON. Year-K spending = base * 1.025^K = 32,306.72
        at K=3."""
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Inflation-adjusted"
        )
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Inflation-adjusted"
        )
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        # OFF path: K-th result is base * 1.025^K.
        self.assertAlmostEqual(r_off["spending"][3], 32_306.72, delta=1.0)
        self.assertAlmostEqual(r_off["spending"][5], 33_942.25, delta=1.0)
        # ON path: flat base £ across the entire horizon.
        for y in range(0, 20):
            self.assertAlmostEqual(
                r_on["spending"][y], 30_000.0, delta=1.0,
                msg=f"year {y}: {r_on['spending'][y]} should be 30000",
            )

    def test_fixed_strategy_unchanged_by_toggle(self):
        """Fixed-strategy spending is always base £; the toggle
        has no effect on it."""
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Fixed"
        )
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Fixed"
        )
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        for y in range(0, 20):
            self.assertAlmostEqual(
                r_off["spending"][y], r_on["spending"][y], delta=0.5
            )
            self.assertAlmostEqual(
                r_off["spending"][y], 30_000.0, delta=0.5
            )

    def test_tapered_pre_taper_stays_flat_in_today_value(self):
        """Tapered pre-peak pre-retirement uplift is skipped in
        today's-value mode — same trajectory as Fixed for that
        period."""
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Tapered (down with age)",
            life_expectancy_end_age=80.0,
        )
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Tapered (down with age)",
            life_expectancy_end_age=80.0,
        )
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        # OFF: K-th result = 30000 * 1.025^K (pre-taper because age < 75).
        self.assertAlmostEqual(r_off["spending"][5], 33_942.25, delta=1.0)
        # ON: pre-taper, no inflation uplifted base, no taper fired
        # (age 60 < 75 = taper_start_age).
        self.assertAlmostEqual(r_on["spending"][5], 30_000.0, delta=1.0)

    def test_db_payout_stays_flat_in_today_value(self):
        """DB payout stays at the year-0 base each year when ON;
        OFF it indexes by db_growth_rate after draw_age. At
        simulation year K, years_active = K + p1_age - draw_age.
        For p1 age=55, draw_age=60: years_active=K-5. So at K=8,
        years_active=3 (NOT 8 — common pitfall)."""
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Fixed"
        )
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Fixed"
        )
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        # Year K=8 → years_active=3. p1's indexed DB = 10000 * 1.025^3
        # ≈ 10,768.91; p2's = 5000 * 1.025^3 ≈ 5,384.45. Total ≈
        # 16,153.36.
        self.assertAlmostEqual(
            r_off["db_payout"][8], 15_000.0 * (1.025 ** 3), delta=2.0
        )
        # ON: stays flat at 10_000 + 5_000 = 15_000.
        for y in (8, 10, 12, 15, 18):
            self.assertAlmostEqual(
                r_on["db_payout"][y], 15_000.0, delta=0.5,
                msg=f"year {y}: {r_on['db_payout'][y]} should be 15000",
            )

    def test_state_payout_stays_flat_in_today_value(self):
        """State payout = FULL_STATE_PENSION * (1+r)^N OFF; flat at
        FULL_STATE_PENSION ON. Year K=13 = age 68 (1 year post
        state_pension_age=67) so years_active=1."""
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Fixed"
        )
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Fixed"
        )
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        # Year 13 OFF: 11000 * 1.025^1 * 2 partners = 22,550.
        self.assertAlmostEqual(
            r_off["state_payout"][13], 22_550.0, delta=2.0
        )
        # Year 13 ON: flat at 11000 * 2 = 22,000.
        self.assertAlmostEqual(
            r_on["state_payout"][13], 22_000.0, delta=1.0
        )
        # Year 18 (6 years post state-pension) ON: still flat.
        self.assertAlmostEqual(
            r_on["state_payout"][18], 22_000.0, delta=1.0
        )

    def test_property_value_zero_growth_in_today_value(self):
        """Property asset value is frozen at year-0 nominal (£400,000)
        when ON (per user intent: "the property value growth will
        not be applied"). OFF it compounds at 2%/yr."""
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Fixed"
        )
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Fixed"
        )
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        # OFF: at iteration K, value = initial * (1.02)^(K+1).
        # At K=9, value = 487,597.77; at K=10, value = 497,349.72.
        # The K+1 (not K) indexing comes from the year loop
        # recording state AFTER iteration K's growth step.
        self.assertAlmostEqual(
            r_off["property_value"][9], 400_000 * (1.02 ** 10), delta=2.0
        )
        self.assertAlmostEqual(
            r_off["property_value"][10], 400_000 * (1.02 ** 11), delta=2.0
        )
        # ON: frozen at 400,000 for every year.
        for y in (0, 5, 10, 15, 19):
            self.assertAlmostEqual(
                r_on["property_value"][y], 400_000.0, delta=0.5,
                msg=f"year {y}: {r_on['property_value'][y]} should be 400000",
            )

    def test_isa_uses_real_growth_rate_in_today_value(self):
        """ISA asset: nominal 5% at 2.5% inflation = 2.5% real."""
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Fixed"
        )
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Fixed"
        )
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        # Year K=4 OFF: 50000 * 1.05^5 = 63,814.08.
        self.assertAlmostEqual(
            r_off["isa_value"][4], 50_000 * (1.05 ** 5), delta=2.0
        )
        # Year K=4 ON: 50000 * 1.025^5 = 56,602.36.
        self.assertAlmostEqual(
            r_on["isa_value"][4], 50_000 * (1.025 ** 5), delta=2.0
        )
        # Crossing sanity check: ON ISA value should be strictly
        # less than OFF at every post-iteration K (since real rate
        # < nominal rate for this case).
        for y in range(1, 20):
            self.assertLess(
                r_on["isa_value"][y], r_off["isa_value"][y],
                msg=f"year {y}: ON ISA {r_on['isa_value'][y]} "
                    f"should be < OFF {r_off['isa_value'][y]}",
            )

    def test_dc_pot_uses_real_growth_rate_in_today_value(self):
        """DC pot compounds at real_rate = nominal - inflation in
        today's-value mode, monthly. Use ratio assertions
        rather than closed-form monthly math to dodge the
        off-by-one month indexing trap."""
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Fixed"
        )
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Fixed"
        )
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        # ON dc_pot should be strictly smaller than OFF at every
        # post-iteration K (real rate < nominal rate, with both
        # partners' dc_growth_rate > inflation_rate=2.5%).
        for y in range(0, 20):
            self.assertLess(
                r_on["dc_pot"][y], r_off["dc_pot"][y],
                msg=f"year {y}: ON dc_pot {r_on['dc_pot'][y]} "
                    f"should be < OFF {r_off['dc_pot'][y]}",
            )
        # Year 1 sanity: ON should be smaller because real rate
        # (4.5% / 2.5%) < nominal (7% / 5%) for both partners.
        self.assertGreater(r_off["dc_pot"][1], 0.0)
        self.assertGreater(r_on["dc_pot"][1], 0.0)

    def test_mortgage_outstanding_unchanged_by_today_value_toggle(self):
        """Mortgage amortisation is byte-identical in both modes —
        the interest rate is a real (not inflation-linked)
        liability rate and the user explicitly said "mortgage
        interest will STILL BE APPLIED"."""
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Fixed"
        )
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Fixed"
        )
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        for y in range(0, 15):
            self.assertAlmostEqual(
                r_off["mortgage_balance"][y],
                r_on["mortgage_balance"][y],
                delta=0.01,
                msg=f"year {y}: mortgage diverges between modes",
            )
            self.assertAlmostEqual(
                r_off["mortgage_payment"][y],
                r_on["mortgage_payment"][y],
                delta=0.01,
            )

    def test_today_value_off_matches_nominal_baseline(self):
        """Default (toggle OFF) engine output equals the prior
        base case: spending inflates at 2.5% with no today's-value
        transforms applied."""
        h = _build_baseline_household(
            show_in_todays_value=False, strategy="Inflation-adjusted"
        )
        r = run_simulation(h)
        # Year K spending = base * 1.025^K = 32,306.72 at K=3.
        self.assertAlmostEqual(r["spending"][3], 32_306.72, delta=1.0)
        self.assertGreater(r["db_payout"][7], 0)


# ----------------------- Backward-compat tests -----------------------

class TestBackCompat(unittest.TestCase):
    """Dataclass default values and helper signatures must remain
    BC-stable so the 290+ pre-existing tests keep passing."""

    def test_household_dataclass_defaults(self):
        """`show_in_todays_value` defaults to False and
        `inflation_rate` defaults to 0.025 — legacy saved-JSON
        plans (with neither field) construct cleanly."""
        h = _build_baseline_household()
        self.assertEqual(h.show_in_todays_value, False)
        self.assertEqual(h.inflation_rate, 0.025)

    def test_view_mode_in_results_for_chart_labels(self):
        """The simulation output dict carries the today's-value
        flag so downstream captions auto-label."""
        h_on = _build_baseline_household(
            show_in_todays_value=True, strategy="Fixed"
        )
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Fixed"
        )
        r_on = run_simulation(h_on)
        r_off = run_simulation(h_off)
        self.assertEqual(r_on.get("view_mode"), "today")
        self.assertEqual(r_off.get("view_mode"), "nominal")
        self.assertEqual(r_on.get("inflation_rate"), 0.025)

    def test_state_pension_income_legacy_signature_unchanged(self):
        """`simulation.state_pension.state_pension_income(person, year)`
        still works with the legacy single-argument shape so all
        existing unit tests can import the helper unchanged."""
        from simulation.state_pension import state_pension_income
        p = Person(
            name="x", age=68.0, retirement_age=60.0,
            state_pension_age=67.0, dc_pot=0.0,
            state_pension_growth_rate=0.025,
        )
        # Year 1: age 69, 2 years post state_pension_age. SP =
        # 11000 * 1.025^2 = 11000 * 1.050625 = 11,556.875.
        sp = state_pension_income(p, 1)
        self.assertAlmostEqual(sp, 11_556.875, delta=0.5)

    def test_indexed_earned_income_legacy_signature_unchanged(self):
        """`simulation.engine._indexed_earned_income(person, year)`
        still works with the legacy single-argument shape."""
        from simulation.engine import _indexed_earned_income
        p = Person(
            name="x", age=55.0, retirement_age=60.0,
            state_pension_age=67.0, dc_pot=0.0,
            income_until_retirement=50_000.0,
            income_growth_rate=0.025,
        )
        # Year 0: 50000 * 1.025^0 = 50,000.
        self.assertAlmostEqual(
            _indexed_earned_income(p, 0), 50_000.0, delta=0.5
        )
        # Year 4: 50000 * 1.025^4 = 55,190.64.
        self.assertAlmostEqual(
            _indexed_earned_income(p, 4), 55_190.64, delta=1.0
        )


# ----------------------- Deficit-signal helper -----------------------

class TestDeficitSignalTodayValue(unittest.TestCase):
    """`compute_pre_retirement_deficit_signal` reports via the
    Spending page banner. When today's-value is ON the helper
    must match the engine output: wages use real rate, DB and
    SP payouts stay flat."""

    def test_dict_person_earned_today_value_uses_real_rate(self):
        """`_dict_person_earned` should produce a smaller number
        when today's-value mode is on (real rate < nominal rate
        for any positive income_growth_rate > inflation_rate)."""
        from simulation.deficit_signal import _dict_person_earned
        p = {
            "age": 55.0,
            "retirement_age": 60.0,
            "income_until_retirement": 50_000.0,
            "income_growth_rate": 0.025,
        }
        # Default (legacy signature): nominal rate. Year 4 = 55,190.64.
        self.assertAlmostEqual(
            _dict_person_earned(p, 4),
            50_000.0 * (1.025 ** 4),
            delta=1.0,
        )
        # Today's-value mode: real rate = 0% (wage growth = inflation).
        # Year 4 = 50_000 (flat).
        self.assertAlmostEqual(
            _dict_person_earned(
                p, 4,
                inflation_rate=0.025,
                today_value_mode=True,
            ),
            50_000.0,
            delta=0.5,
        )


# ----------------------- Monte-Carlo currency modes -------------------

class TestMonteCarloCurrencyModes(unittest.TestCase):
    """MC simulates nominal stochastic paths internally, then optionally
    converts completed paths to today's money using each path's sampled
    cumulative inflation. This keeps stochastic inflation intact without
    double-deflating growth rates.

    The source households can carry different toggle values, but callers
    explicitly choose the output currency with `today_value_mode`. Random
    draws remain identical under a fixed numpy seed.
    """

    def test_mc_percentile_bands_are_distinct_when_today_mode_requested(self):
        """Today's-money output is lower than nominal future-pound output
        after a positive-inflation horizon, while the starting point stays
        identical."""
        import numpy as np
        from simulation.monte_carlo import monte_carlo_simulation

        h_on = _build_baseline_household(
            show_in_todays_value=True,
            strategy="Fixed",
            life_expectancy_end_age=75.0,
        )
        h_off = _build_baseline_household(
            show_in_todays_value=False,
            strategy="Fixed",
            life_expectancy_end_age=75.0,
        )

        runs, years = 50, 20
        np.random.seed(42)
        result_on = monte_carlo_simulation(
            h_on, runs=runs, years=years, today_value_mode=True
        )
        np.random.seed(42)
        result_off = monte_carlo_simulation(
            h_off, runs=runs, years=years, today_value_mode=False
        )

        for band in ("p10", "p50", "p90"):
            on_vals = result_on["percentiles"][band]
            off_vals = result_off["percentiles"][band]
            self.assertEqual(len(on_vals), len(off_vals))
            # Displayed real-terms wealth is lower over the horizon after
            # removing the sampled cumulative inflation from every asset.
            self.assertLess(on_vals[-1], off_vals[-1])

    def test_mc_success_rate_is_invariant_to_display_currency(self):
        """Changing only the displayed currency must not change the
        underlying simulated failures or success probability."""
        import copy
        import numpy as np
        from simulation.monte_carlo import monte_carlo_simulation

        h = _build_baseline_household(
            show_in_todays_value=False,
            strategy="Fixed",
            life_expectancy_end_age=75.0,
        )
        h_today = copy.deepcopy(h)
        h_today.show_in_todays_value = True

        np.random.seed(777)
        nominal = monte_carlo_simulation(
            h, runs=50, years=20, today_value_mode=False
        )
        np.random.seed(777)
        today = monte_carlo_simulation(
            h_today, runs=50, years=20, today_value_mode=True
        )

        self.assertEqual(nominal["success_rate"], today["success_rate"])
        self.assertEqual(nominal["failure_years"], today["failure_years"])

    def test_mc_wrapper_does_not_mutate_source_household(self):
        """MC must not mutate the caller's household while creating
        nominal internal copies."""
        from simulation.monte_carlo import monte_carlo_simulation
        import copy

        h_on = _build_baseline_household(
            show_in_todays_value=True,
            strategy="Fixed",
            life_expectancy_end_age=70.0,
        )
        snapshot = copy.deepcopy(h_on)
        monte_carlo_simulation(h_on, runs=1, years=5, today_value_mode=True)

        self.assertEqual(h_on.show_in_todays_value, snapshot.show_in_todays_value)
        self.assertEqual(h_on.person1.dc_growth_rate, snapshot.person1.dc_growth_rate)
        self.assertEqual(h_on.person1.db_growth_rate, snapshot.person1.db_growth_rate)
        self.assertEqual(
            h_on.person1.state_pension_growth_rate,
            snapshot.person1.state_pension_growth_rate,
        )
        self.assertEqual(h_on.person2.income_growth_rate, snapshot.person2.income_growth_rate)


# ----------------------- Quick-Estimate DC growth contract -----------------
#
# Lock down the Quick-Estimate default scenario the user described:
# nominal DC growth = 5%/yr, inflation = 2.5%/yr, today's-money mode
# ON. The effective DC growth must be exactly 2.5%/yr \u2014 the user
# explicitly stated this is "median growth on the still-invested DC
# pensions, after inflation removal" and the rationale for keeping DC
# growth alive (non-zero) in today's-money mode rather than zeroing it
# like DB pension / State Pension payouts do.
#
# NOTE: The general-purpose `TestEngineTodayValueInvariants` already
# covers "ON real rate < OFF nominal rate" via
# `test_dc_pot_uses_real_growth_rate_in_today_value`; this focused
# suite adds the SPECIFIC scenario the Quick-Estimate page ships with.

class TestQuickEstimateDcGrowthContract(unittest.TestCase):
    """User-confirmed rationale: in today's-money mode ON with the
    Quick-Estimate defaults (dc_growth_rate=0.05 nominal,
    inflation_rate=0.025), the effective DC growth is exactly
    0.025 (2.5%/yr). The DC pot continues to compound at
    its real rate \u2014 not zeroed like DB / State Pension payouts.
    """

    def test_helper_returns_2_5_pct_for_quick_estimate_defaults(self):
        """`effective_dc_growth(ON, nominal=0.05)` returns 0.025."""
        from simulation.today_value import TodayValueSettings
        s = TodayValueSettings(enabled=True, inflation_rate=0.025)
        self.assertAlmostEqual(
            effective_dc_growth(s, 0.05), 0.025,
            msg="Quick-Estimate default (5% nominal - 2.5% inflation) "
                "must yield 2.5% real DC growth in today's-money mode.",
        )

    def test_engine_dc_pot_grows_in_today_value_mode(self):
        """Build a Quick-Estimate-shape household (5% nominal DC
        growth, 2.5% inflation, today's-money ON). Assert that:

          (a) The DC pot GROWS year-over-year in today's-money mode
              (not silently zeroed) \u2014 confirming the engine
              continues to apply the real growth rate, matching
              the user's "median growth on still-invested DC
              pensions" intent.

          (b) Today's-money ratio (end year 1 / year 0) is
              strictly LESS than the OFF mode's ratio \u2014 i.e. real
              growth applied, not nominal.

          (c) The numeric ratio is approximately 1.025 (real rate
              compounded monthly) \u2014 close to the simple-additive
              2.5% real rate the helper returns, with the small
              extra from monthly compounding (~(1.025/12)^12 \u2212 1
              \u2248 2.53%).
        """
        import copy
        h_off = _build_baseline_household(
            show_in_todays_value=False, strategy="Fixed",
        )
        h_off.person1.dc_growth_rate = 0.05
        h_off.person2.dc_growth_rate = 0.05
        h_on = copy.deepcopy(h_off)
        h_on.show_in_todays_value = True
        h_on.inflation_rate = 0.025
        r_off = run_simulation(h_off)
        r_on = run_simulation(h_on)
        # (a) Both modes grow. Skip if start is 0 (degenerate
        # case; the baseline fixture starts with \u00a3100k+ so this
        # branch should never fire).
        for h_label, r in (("OFF", r_off), ("ON", r_on)):
            start = r["dc_pot"][0]
            end = r["dc_pot"][1]
            self.assertGreater(start, 0.0)
            ratio = end / start
            self.assertGreater(
                ratio, 1.005,
                msg=f"{h_label}: dc_pot ratio year-1/year-0 = "
                    f"{ratio:.5f} should be >1.005 (DC is still "
                    "invested at a positive rate)",
            )
        # (b) ON real-rate ratio < OFF nominal-rate ratio.
        on_ratio = r_on["dc_pot"][1] / r_on["dc_pot"][0]
        off_ratio = r_off["dc_pot"][1] / r_off["dc_pot"][0]
        self.assertLess(
            on_ratio, off_ratio,
            msg=f"ON ratio {on_ratio:.5f} should be < OFF ratio "
                f"{off_ratio:.5f} (real < nominal)",
        )
        # (c) ON ratio is approximately 1.025 (real rate compounded
        # monthly). Generous delta for floating-point noise and
        # monthly-compounding rounding.
        self.assertAlmostEqual(
            on_ratio, 1.025, delta=0.01,
            msg=f"ON ratio {on_ratio:.5f} should be approximately "
                "1.025 (= 2.5% real rate, monthly compounded)",
        )


if __name__ == "__main__":
    unittest.main()
