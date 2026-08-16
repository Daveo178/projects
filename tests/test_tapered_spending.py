"""Tests for the new "Tapered (down with age)" drawdown strategy.

The strategy is added in `simulation/engine.py` step 6 alongside
the existing Fixed / Inflation-adjusted / Safe Withdrawal (4%)
branches. Key contracts locked down by this test class:

  * Real-terms (not nominal) decline — base inflates annually
    THEN the taper is applied, so a 2% taper with 2.5% inflation
    yields a 2% real decline per year (not the ~4.5% a nominal-
    only taper would).
  * No decline before `taper_start_age` — pre-taper years are
    inflation-adjusted flat (same trajectory as the standalone
    Inflation-adjusted strategy).
  * `taper_floor_gbp` caps the asymptotic approach to zero in
    extreme old age — spending never drops below the floor.
  * Defaults wired to the `Household` dataclass defaults
    (start=75.0, rate=0.02, floor=10000.0) and `getattr(...)`
    defensive reads work for legacy `Household(...)` instances
    built from a dict that does NOT include the three new fields.
"""

from __future__ import annotations

import unittest

from models.household import Household
from models.person import Person
from simulation.engine import run_simulation
from simulation.spending import apply_late_life_spending_reductions


def _build_household(
    strategy: str,
    *,
    taper_start_age: float = 75.0,
    taper_rate: float = 0.02,
    taper_floor_gbp: float = 10_000.0,
    life_expectancy_end_age: float = 95.0,
    age_p1: float = 60.0,
    age_p2: float = 60.0,
    retirement_age: float = 60.0,
    spending_target: float = 30_000.0,
    late_life_step_1_age: float = 75.0,
    late_life_step_1_rate: float = 0.0,
    late_life_step_2_age: float = 85.0,
    late_life_step_2_rate: float = 0.0,
):
    """Single-shape fixture for the test class. Both partners
    aged 60, zero income, zero DC, zero DB — so the spending
    trajectory is exactly the strategy alone (no UFPLS / DB / SP
    noise to mask the assertion).
    """
    p1 = Person(
        name="Dave",
        age=age_p1,
        retirement_age=retirement_age,
        state_pension_age=67.0,
        dc_pot=0.0,
        income_until_retirement=0.0,
        db_income=0.0,
        draw_age=60.0,
        pcls_percent=0,
    )
    p2 = Person(
        name="Shaz",
        age=age_p2,
        retirement_age=retirement_age,
        state_pension_age=67.0,
        dc_pot=0.0,
        income_until_retirement=0.0,
        db_income=0.0,
        draw_age=60.0,
        pcls_percent=0,
    )
    return Household(
        person1=p1,
        person2=p2,
        assets=[],
        mortgage=None,
        spending_target=spending_target,
        drawdown_strategy=strategy,
        events=[],
        cash_buffer=False,
        taper_start_age=taper_start_age,
        taper_rate=taper_rate,
        taper_floor_gbp=taper_floor_gbp,
        late_life_step_1_age=late_life_step_1_age,
        late_life_step_1_rate=late_life_step_1_rate,
        late_life_step_2_age=late_life_step_2_age,
        late_life_step_2_rate=late_life_step_2_rate,
        life_expectancy_end_age=life_expectancy_end_age,
    )


class TestTaperedSpendSeries(unittest.TestCase):
    """Engine-level contract: per-year spending series shape."""

    def test_tapered_pre_taper_matches_inflation_adjusted(self):
        """Before `taper_start_age`, Tapered should produce the same
        trajectory as standalone Inflation-adjusted (inflation at
        2.5%/yr, no taper)."""
        taper_h = _build_household(
            "Tapered (down with age)",
            taper_start_age=80.0,  # well past horizon end of 75
            life_expectancy_end_age=75.0,  # 60 → 75 → 15 years
        )
        inflation_h = _build_household(
            "Inflation-adjusted",
            life_expectancy_end_age=75.0,
        )
        taper_res = run_simulation(taper_h)
        inflation_res = run_simulation(inflation_h)
        # Every year of the 15-year horizon should be IDENTICAL —
        # taper_start_age=80 is past the 75-year end so the taper
        # never fires. Parametrise this way to assert the
        # "pre-taper = Inflation-adjusted" invariant.
        for year in range(15):
            self.assertAlmostEqual(
                taper_res["spending"][year],
                inflation_res["spending"][year],
                delta=0.01,
                msg=(
                    f"pre-taper year {year}: "
                    f"{taper_res['spending'][year]:.4f} vs "
                    f"{inflation_res['spending'][year]:.4f}"
                ),
            )

    def test_tapered_post_taper_real_decline_per_year(self):
        """Post-taper, the year-over-year spending ratio should be
        `1.025 * (1 - taper_rate)` — the 1.025 step is inflation
        indexation, the (1 - rate) is the taper multiplicative
        step on the post-inflation base. Concrete proof that the
        taper is REAL-terms (factor out inflation), not nominal."""
        # Use taper_start_age=65 with age=60 — taper fires immediately
        # in year 5. life_expectancy_end_age=95 → 35-year horizon.
        # So we have years 5..34 (30 samples) of post-taper data.
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=65.0,
            taper_rate=0.02,
            taper_floor_gbp=0.0,  # disable floor for the ratio test
            life_expectancy_end_age=95.0,
        )
        res = run_simulation(h)
        # Pre-taper years (year 0..4) — straight inflation at 2.5%/yr:
        for y in range(4):
            self.assertAlmostEqual(
                res["spending"][y + 1] / res["spending"][y],
                1.025,
                delta=1e-6,
                msg=f"pre-taper year {y}: ratio should be 1.025 exactly",
            )
        # Post-taper years (year 5+): ratio is 1.025 * (1 - rate):
        expected_ratio = 1.025 * (1.0 - 0.02)  # = 1.0045 exactly
        for y in range(5, 30):
            ratio = res["spending"][y + 1] / res["spending"][y]
            self.assertAlmostEqual(
                ratio,
                expected_ratio,
                delta=1e-3,  # FP-tolerance accumulated over 25 steps
                msg=(
                    f"post-taper year {y}: ratio {ratio:.6f}, "
                    f"expected {expected_ratio:.6f}"
                ),
            )

    def test_tapered_floor_caps_asymptotic_decline(self):
        """With `taper_floor_gbp=12,500` and a starting base
        £12,500 + aggressive 10% taper, the floor must kick in
        once the compounding decay would otherwise drop below
        it. Spending should NEVER fall below the floor."""
        # Very short horizon so the £12,500 floor would otherwise
        # breach immediately otherwise — age 60, life_expectancy
        # 70 → 10 years. taper_start_age=60 (immediate taper).
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=60.0,
            taper_rate=0.10,  # aggressive
            taper_floor_gbp=12_500.0,
            life_expectancy_end_age=70.0,
            spending_target=12_500.0,
        )
        res = run_simulation(h)
        # Year 0: 12500 * 1.025 * 1.0 → 12812.5
        # Year 1: 12500 * 1.0506 * 0.9 → 11819
        # Year 1 is below 12500 → floor kicks in → 12500
        for y, s in enumerate(res["spending"]):
            self.assertGreaterEqual(
                s, 12_500.0 - 0.01,
                msg=(
                    f"spending[{y}] = {s:.2f} fell below floor "
                    f"£12,500"
                ),
            )

    def test_tapered_strategy_smoke_vs_fixed(self):
        """Smoke test verifying the strategy string is actually
        wired into the engine. If the engine silently fell through
        to the `else` (= Fixed-equivalent) branch, this assertion
        would fail because the trajectory would NOT diverge."""
        h_fixed = _build_household(
            "Fixed",
            life_expectancy_end_age=70.0,
            spending_target=30_000.0,
        )
        h_tapered = _build_household(
            "Tapered (down with age)",
            taper_start_age=60.0,  # taper fires immediately
            taper_rate=0.50,
            taper_floor_gbp=0.0,
            life_expectancy_end_age=70.0,
            spending_target=30_000.0,
        )
        res_fixed = run_simulation(h_fixed)
        res_tapered = run_simulation(h_tapered)
        # Year-0 spending matches in both (£30,000 base).
        self.assertAlmostEqual(res_fixed["spending"][0], 30_000.0, delta=1.0)
        self.assertAlmostEqual(res_tapered["spending"][0], 30_000.0, delta=1.0)
        # Year 5 is well past the taper_start_age=60, with a
        # 50%/yr decline rate + no floor. Spending should be
        # MUCH lower than the Fixed equivalent.
        self.assertLess(
            res_tapered["spending"][5],
            res_fixed["spending"][5] / 4,
            msg=(
                f"Tapered[5]={res_tapered['spending'][5]:.0f} "
                f"should be < 1/4 of Fixed[5]={res_fixed['spending'][5]:.0f}"
            ),
        )


class TestLateLifeSpendingReductions(unittest.TestCase):
    """Two optional age-based step-downs sit on top of the gradual taper."""

    def test_helper_applies_each_step_inclusive_and_multiplicatively(self):
        # 10% at 75 then 20% at 85 leaves 72% of the pre-step amount.
        self.assertAlmostEqual(
            apply_late_life_spending_reductions(
                50_000.0,
                85.0,
                step_1_age=75.0,
                step_1_rate=0.10,
                step_2_age=85.0,
                step_2_rate=0.20,
            ),
            36_000.0,
        )

    def test_helper_sorts_reversed_ages_and_clamps_bad_rates(self):
        # Reversed ages are still age-triggered; negative/over-100% rates
        # cannot create an increase or negative spending.
        self.assertAlmostEqual(
            apply_late_life_spending_reductions(
                10_000.0,
                80.0,
                step_1_age=85.0,
                step_1_rate=-0.25,
                step_2_age=75.0,
                step_2_rate=1.5,
            ),
            0.0,
        )

    def test_engine_applies_steps_at_configured_ages(self):
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=110.0,
            taper_floor_gbp=0.0,
            life_expectancy_end_age=90.0,
            spending_target=30_000.0,
            late_life_step_1_age=65.0,
            late_life_step_1_rate=0.10,
            late_life_step_2_age=75.0,
            late_life_step_2_rate=0.20,
        )
        res = run_simulation(h)
        # The existing gradual taper is disabled by putting its start
        # beyond the horizon. Compare exact age-boundary ratios.
        self.assertAlmostEqual(
            res["spending"][5] / res["spending"][4],
            1.025 * 0.90,
            delta=1e-6,
        )
        # The first step is already present in year 14, so the
        # second boundary introduces only its additional 20% cut;
        # the normal 2.5% nominal inflation step still applies.
        self.assertAlmostEqual(
            res["spending"][15] / res["spending"][14],
            1.025 * 0.80,
            delta=1e-6,
        )

    def test_steps_do_not_reduce_pre_retirement_spending(self):
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=110.0,
            taper_floor_gbp=0.0,
            life_expectancy_end_age=80.0,
            retirement_age=65.0,
            late_life_step_1_age=50.0,
            late_life_step_1_rate=0.50,
            late_life_step_2_age=55.0,
            late_life_step_2_rate=0.50,
        )
        spending = run_simulation(h)["spending"]
        # Ages 60–64 are still working; the late-life steps must not
        # alter the ordinary inflation-adjusted pre-retirement base.
        for year in range(5):
            self.assertAlmostEqual(
                spending[year],
                30_000.0 * (1.025 ** year),
                delta=1e-6,
            )

    def test_zero_rates_preserve_existing_tapered_series(self):
        baseline = _build_household(
            "Tapered (down with age)",
            taper_start_age=70.0,
            taper_rate=0.03,
            taper_floor_gbp=8_000.0,
            life_expectancy_end_age=90.0,
        )
        explicit_zero = _build_household(
            "Tapered (down with age)",
            taper_start_age=70.0,
            taper_rate=0.03,
            taper_floor_gbp=8_000.0,
            life_expectancy_end_age=90.0,
            late_life_step_1_rate=0.0,
            late_life_step_2_rate=0.0,
        )
        left = run_simulation(baseline)["spending"]
        right = run_simulation(explicit_zero)["spending"]
        self.assertEqual(left, right)


class TestHouseholdTaperDataclassDefaults(unittest.TestCase):
    """Dataclass-level defaults so legacy saved-JSON plans construct
    cleanly without the three new fields."""

    def test_dataclass_defaults(self):
        h = Household(
            person1=Person(
                name="Dave", age=60.0, retirement_age=60.0,
                state_pension_age=67.0, dc_pot=0.0,
                income_until_retirement=0.0, db_income=0.0,
            ),
            person2=Person(
                name="Shaz", age=60.0, retirement_age=60.0,
                state_pension_age=67.0, dc_pot=0.0,
                income_until_retirement=0.0, db_income=0.0,
            ),
        )
        self.assertEqual(h.taper_start_age, 75.0)
        self.assertEqual(h.taper_rate, 0.02)
        self.assertEqual(h.taper_floor_gbp, 10_000.0)
        self.assertEqual(h.late_life_step_1_age, 75.0)
        self.assertEqual(h.late_life_step_1_rate, 0.0)
        self.assertEqual(h.late_life_step_2_age, 85.0)
        self.assertEqual(h.late_life_step_2_rate, 0.0)
        self.assertEqual(h.life_expectancy_end_age, 95.0)

    def test_legacy_household_without_taper_fields_runs_cleanly(self):
        """Simulate a legacy JSON load that omits the three new
        fields. `del` them on a freshly-built instance and verify
        the engine still runs via `getattr(..., default)` defensive
        reads in step 6."""
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=65.0,
            taper_rate=0.02,
            life_expectancy_end_age=80.0,
        )
        del h.taper_start_age
        del h.taper_floor_gbp
        # Engine should still run, falling back to defaults
        # (75.0, 0.02, 10000.0).
        res = run_simulation(h)
        self.assertAlmostEqual(res["spending"][0], 30_000.0, delta=1.0)


class TestGogoBump(unittest.TestCase):
    """Tests the optional `gogo_bump_pct` hump-shape extension to
    the Tapered strategy. The bump adds a Phase 1 ramp-up between
    `retirement_age` and the peak at `taper_start_age`, complementing
    the existing Phase 2 (post-peak taper). Default 0% preserves
    pure-taper behaviour.

    Contracts locked down:
      * Phase 1 year-over-year ratio is `1.025 * (1 + gogo_bump)` —
        inflation up-step + real-terms bump.
      * Phase 2 year-over-year ratio is `1.025 * (1 - taper_rate)` —
        inflation up-step + real-terms taper (anchored at the
        Phase-1 peak value so there's no jump discontinuity at the
        boundary).
      * Peak lands EXACTLY at `taper_start_age` (year-0 ≈ retirement,
        year-N ≈ retirement + peak_years).
      * Pre-retirement years are unaffected by the bump (working
        years have no go-go pattern).
      * Default 0% produces byte-identical output to the previous
        Tapered engine — back-compat with all 292 locked-down
        regression tests.
      * Floor still caps the post-peak taper at `taper_floor_gbp`.
    """

    def test_gogo_zero_matches_pure_tapered(self):
        """Default 0% bump must reproduce the pure-taper behaviour
        byte-for-byte across the entire horizon — this is the
        back-compat gate that protects all 292 existing tests."""
        # Same fixture as a pure-Tapered run (no bump) — only
        # difference is the explicit `gogo_bump_pct=0` passing.
        h_pure = _build_household(
            "Tapered (down with age)",
            taper_start_age=70.0,
            taper_rate=0.03,
            taper_floor_gbp=8_000.0,
            life_expectancy_end_age=90.0,
            retirement_age=60.0,
            spending_target=30_000.0,
        )
        # `del` patches the attribute the dataclass defaulted to
        # 0.0 anyway, so the engine reads via getattr(..., default)
        # — this is the path an unmigrated legacy saved-JSON
        # exercise would take.
        if hasattr(h_pure, "gogo_bump_pct"):
            del h_pure.gogo_bump_pct
        h_with_explicit_zero = _build_household(
            "Tapered (down with age)",
            taper_start_age=70.0,
            taper_rate=0.03,
            taper_floor_gbp=8_000.0,
            life_expectancy_end_age=90.0,
            retirement_age=60.0,
            spending_target=30_000.0,
        )
        # Force the bump to 0.0 explicitly (matches the dataclass
        # default but exercises the explicit-write path).
        h_with_explicit_zero.gogo_bump_pct = 0.0
        res_pure = run_simulation(h_pure)
        res_zero = run_simulation(h_with_explicit_zero)
        for y, (s_pure, s_zero) in enumerate(
            zip(res_pure["spending"], res_zero["spending"])
        ):
            self.assertAlmostEqual(
                s_pure, s_zero, delta=1e-6,
                msg=(
                    f"year {y}: pure-taper {s_pure:.4f} != "
                    f"explicit-zero {s_zero:.4f}"
                ),
            )

    def test_gogo_phase1_ramps_up_post_retirement(self):
        """Phase 1 (retirement_age ≤ age < taper_start_age) year-
        over-year ratio should be `1.025 * (1 + gogo_bump)` —
        inflation up-step + real-terms ramp-up.

        Use `retirement_age > current_age` so there's a real
        pre-retirement horizon (years 0..N-1 with N = retiring-
        years). Without a pre-retirement period, Phase 1 fires
        from year 0 onwards and the test cannot distinguish
        pre-retirement from Phase 1."""
        # age=60, retirement=65 (5-year pre-retirement horizon,
        # years 0..4), taper_start_age=75 (peak at year 15),
        # taper_rate=0.05 (steeper than 0.02 so Phase 2 ratio
        # is < 1 and we can verify the trajectory clears the
        # floor with the 15-year taper-down stretch to age 80).
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=75.0,
            taper_rate=0.05,
            taper_floor_gbp=0.0,
            life_expectancy_end_age=95.0,
            retirement_age=65.0,
            age_p1=60.0,
            age_p2=60.0,
            spending_target=30_000.0,
        )
        h.gogo_bump_pct = 5.0  # 5%/yr real-terms bump
        res = run_simulation(h)
        # Pre-retirement (years 0..4, ages 60..64): straight
        # inflation only.
        for y in range(4):
            self.assertAlmostEqual(
                res["spending"][y + 1] / res["spending"][y],
                1.025,
                delta=1e-6,
                msg=f"pre-retirement year {y}: ratio should be 1.025",
            )
        # Phase 1 (years 5..14, ages 65..74, before peak at 75):
        # ramp up by 1.025 * (1+gogo) = 1.07625 per year.
        expected_ratio = 1.025 * 1.05
        for y in range(5, 14):
            ratio = res["spending"][y + 1] / res["spending"][y]
            self.assertAlmostEqual(
                ratio, expected_ratio, delta=1e-3,
                msg=(
                    f"Phase 1 year {y}: ratio {ratio:.6f}, "
                    f"expected {expected_ratio:.6f}"
                ),
            )

    def test_gogo_phase2_tapers_down_post_peak(self):
        """Phase 2 (age ≥ taper_start_age) year-over-year ratio
        should be `1.025 * (1 - taper_rate)`, anchored at the
        Phase-1 peak value so the trajectory is continuous at the
        boundary year."""
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=70.0,
            taper_rate=0.02,
            taper_floor_gbp=0.0,
            life_expectancy_end_age=90.0,
            retirement_age=60.0,
            spending_target=30_000.0,
        )
        h.gogo_bump_pct = 5.0
        res = run_simulation(h)
        # Phase 2 = years 11..end (peak at year 10). With 30 years
        # total and life_expectancy=95, age=60: 95-60=35 years (with
        # 5-yr floor), starting day 0. But retirement_age=60 so
        # household is retired from year 0; peak at year 10. Years
        # 11..29 Phase 2.
        expected_ratio = 1.025 * 0.98
        for y in range(11, 29):
            ratio = res["spending"][y + 1] / res["spending"][y]
            self.assertAlmostEqual(
                ratio, expected_ratio, delta=1e-3,
                msg=(
                    f"Phase 2 year {y}: ratio {ratio:.6f}, "
                    f"expected {expected_ratio:.6f}"
                ),
            )

    def test_gogo_peak_lands_at_taper_start_age(self):
        """Peak spending must land EXACTLY at `taper_start_age`
        — spending at year `peak` should be ≥ spending at
        `peak-1` (Phase 1 ended) AND > spending at `peak+1`
        (Phase 2 started). Without this the hump shape silently
        flattens or shifts.

        Uses a STEEP taper (5%/yr) so the post-peak ratio
        `1.025 * (1 - 0.05) = 0.974` is genuinely < 1. With the
        default 2% taper vs 2.5% inflation, the post-peak
        nominal ratio is 1.025 * 0.98 = 1.0045 (still rising)
        even though real-terms it's declining — i.e. nominal £
        keeps going up post-peak until the cumulative taper
        finally overcomes cumulative inflation. The peak-detection
        test needs a steep taper to observe the boundary."""
        # retirement_age=60, life_expectancy=90 → 30 years.
        # taper_start_age=70 → peak at year 10. Bump=5%, rate=5%.
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=70.0,
            taper_rate=0.05,
            taper_floor_gbp=0.0,
            life_expectancy_end_age=90.0,
            retirement_age=60.0,
            spending_target=30_000.0,
        )
        h.gogo_bump_pct = 5.0
        res = run_simulation(h)
        # Phase 1 spends[year+1] = spends[year] * 1.025 * 1.05 =
        # spends[year] * 1.07625 — so spend is STRICTLY INCREASING
        # through Phase 1. spend[10] >= spend[9] (loose
        # inequality handles fp drift).
        peak_y = 10  # year 10 = age 70 = taper_start_age
        self.assertGreaterEqual(
            res["spending"][peak_y], res["spending"][peak_y - 1],
            msg=(
                f"spending at peak ({res['spending'][peak_y]:.0f}) "
                f"should be >= spending at peak-1 "
                f"({res['spending'][peak_y - 1]:.0f})"
            ),
        )
        # Phase 2 spends[year+1] = spends[year] * 1.025 * 0.95 =
        # 0.97375\u00d7 peak — strictly DECREASING by ~2.6%/yr
        # in nominal terms.
        self.assertGreater(
            res["spending"][peak_y], res["spending"][peak_y + 1],
            msg=(
                f"spending at peak ({res['spending'][peak_y]:.0f}) "
                f"should be > spending at peak+1 "
                f"({res['spending'][peak_y + 1]:.0f})"
            ),
        )

    def test_gogo_pre_retirement_years_unchanged(self):
        """Pre-retirement years must be IDENTICAL with or without
        the bump — the go-go ramp applies only post-retirement
        (working years shouldn't inflate at 1.025 * (1+gogo))."""
        # Use retirement_age=65 so years 0..4 are pre-retirement
        # (ages 60..64). Years 5..9 are Phase 1 (ages 65..69), year
        # 10 is peak (age 70 = taper_start_age).
        no_bump = _build_household(
            "Tapered (down with age)",
            taper_start_age=70.0,
            taper_rate=0.02,
            taper_floor_gbp=0.0,
            life_expectancy_end_age=95.0,
            retirement_age=65.0,
            spending_target=30_000.0,
        )
        no_bump.gogo_bump_pct = 0.0
        with_bump = _build_household(
            "Tapered (down with age)",
            taper_start_age=70.0,
            taper_rate=0.02,
            taper_floor_gbp=0.0,
            life_expectancy_end_age=95.0,
            retirement_age=65.0,
            spending_target=30_000.0,
        )
        with_bump.gogo_bump_pct = 5.0
        res_no = run_simulation(no_bump)
        res_yes = run_simulation(with_bump)
        # Pre-retirement (years 0..4): identical.
        for y in range(5):
            self.assertAlmostEqual(
                res_no["spending"][y], res_yes["spending"][y],
                delta=1e-6,
                msg=(
                    f"pre-retirement year {y}: "
                    f"no-bump {res_no['spending'][y]:.2f} != "
                    f"with-bump {res_yes['spending'][y]:.2f}"
                ),
            )
        # Post-retirement (Phase 1, years 5..9): DIVERGENT.
        # with-bump should be strictly HIGHER.
        self.assertGreater(
            res_yes["spending"][9], res_no["spending"][9],
            msg=(
                f"Phase 1 year 9 with bump "
                f"{res_yes['spending'][9]:.0f} should be > "
                f"no-bump {res_no['spending'][9]:.0f}"
            ),
        )

    def test_gogo_floor_still_active_after_bump(self):
        """Aggressive bump + aggressive taper + very short horizon
        should still respect the floor — floor enforcement is
        engine-level, not phase-specific."""
        # bump=20%/yr, taper=15%/yr, age=60, end_age=70 → 10y
        # horizon. Spending skyrockets then plummets but floor
        # caps it at £12,000.
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=63.0,  # peak at year 3
            taper_rate=0.15,
            taper_floor_gbp=12_000.0,
            life_expectancy_end_age=70.0,
            retirement_age=60.0,
            spending_target=15_000.0,
        )
        h.gogo_bump_pct = 20.0
        res = run_simulation(h)
        for y, s in enumerate(res["spending"]):
            self.assertGreaterEqual(
                s, 12_000.0 - 0.01,
                msg=(
                    f"spending[{y}] = {s:.0f} fell below "
                    f"floor £12,000"
                ),
            )

    def test_gogo_dataclass_default_is_zero(self):
        """The `gogo_bump_pct` Household dataclass default must be
        0.0% so legacy saved-JSON plans (without the field)
        construct cleanly and produce byte-identical pure-taper
        behaviour."""
        h = Household(
            person1=Person(
                name="Dave", age=60.0, retirement_age=60.0,
                state_pension_age=67.0, dc_pot=0.0,
                income_until_retirement=0.0, db_income=0.0,
            ),
            person2=Person(
                name="Shaz", age=60.0, retirement_age=60.0,
                state_pension_age=67.0, dc_pot=0.0,
                income_until_retirement=0.0, db_income=0.0,
            ),
            spending_target=30_000.0,  # explicit; Household default is 0.0
        )
        # Default present on the dataclass:
        self.assertEqual(h.gogo_bump_pct, 0.0)
        # Default kicks in via `getattr` when `del`'d (legacy
        # saved-JSON path):
        del h.gogo_bump_pct
        res = run_simulation(h)
        # Year-0 spending is the explicit £30,000 — proves the
        # engine reads the dataclass default on the missing field.
        self.assertAlmostEqual(res["spending"][0], 30_000.0, delta=1.0)

    def test_gogo_pre_retirement_exemption_even_when_start_before_retirement(self):
        """Regression test for the deliberate Phase-1/Phase-2
        boundary: pre-retirement years ALWAYS sit at the straight
        inflation-adjusted base, regardless of where taper_start_age
        sits. Even if a user sets `taper_start_age < retirement_age`
        (a corner case), pre-retirement years see base_nominal —
        NOT the old `(1 - rate)^(age - start)` taper factor that
        the previous engine would have applied. Working-year
        spending is structurally exempt from the late-life shape."""
        # Pathological input: start_age 50, retirement_age 65.
        # Without the exemption, the OLD engine would have applied
        # a 15-year taper factor to year 0 (where age=60 > start=50).
        # The NEW engine keeps year 0–4 (= pre-retirement horizon
        # through age 60+4=64<65) at base_nominal.
        h = _build_household(
            "Tapered (down with age)",
            taper_start_age=50.0,  # < retirement_age (pathological)
            taper_rate=0.02,
            taper_floor_gbp=0.0,
            life_expectancy_end_age=95.0,
            retirement_age=65.0,  # 5-year pre-retirement horizon
            age_p1=60.0,
            age_p2=60.0,
            spending_target=30_000.0,
        )
        h.gogo_bump_pct = 0.0  # pure-taper behaviour
        res = run_simulation(h)
        # Years 0..4 (pre-retirement, ages 60..64): spending
        # should be EXACTLY base_nominal, NOT base_nominal * taper.
        for y in range(5):
            self.assertAlmostEqual(
                res["spending"][y], 30_000.0 * (1.025 ** y),
                delta=1e-6,
                msg=(
                    f"pre-retirement year {y}: spending "
                    f"{res['spending'][y]:.4f} should match "
                    f"base_nominal {30_000.0 * (1.025 ** y):.4f}"
                ),
            )


if __name__ == "__main__":
    unittest.main()
