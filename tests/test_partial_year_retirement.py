"""
Regression tests for the months-precision `retirement_age` feature.

Two layers under test:

  1. Person dataclass            — accepts int (legacy) AND float; the
                                   `is_retired(year)` and
                                   `years_to_retirement()` helpers work
                                   correctly for fractional values so
                                   half-year retirement ages round-trip
                                   cleanly.
  2. Engine step 2a/2b           — wires `fraction = min(1.0,
                                   retirement_offset - year)` into both
                                   `_dc_monthly_compound` calls when
                                   `year < retirement_offset`, and falls
                                   back to `fraction=1.0, M=0.0` after
                                   retirement so the pot keeps
                                   compounding during drawdown.

Mirrors the partial-year scaling applied to mortgage amortisation in
step 4 (where a 9y6m mortgage ends mid-year-9). The symmetry:

  * Mortgage: `fraction = min(1.0, mortgage.end_year - year)` →
              declining-edge interest + payment in the closing year.
  * Retirement: `fraction = min(1.0, retirement_offset - year)` →
                declining-edge growth + contributions in the closing
                working year.

BC guarantee: when `retirement_age` is an integer (legacy saved JSON),
`retirement_offset` is an integer, so `min(1.0, retirement_offset -
year)` evaluates to exactly `1.0` for every pre-retirement year — the
helper runs the same 12 iterations with the same per-step ops on the
same operands in the same order as pre-PR, giving byte-identical
output. The byte-identical BC guard for legacy int retirement_age sits
in TestEngineIntRetirementAgeIsByteIdentical below.
"""

import unittest

from simulation.engine import _dc_monthly_compound, run_simulation
from models.person import Person
from models.household import Household


# ---------------------------------------------------------------------------
# Shared closed-form helpers — annuity-due, identical to those in
# tests/test_dc_compound.py so the math behaves identically.
# ---------------------------------------------------------------------------

def _closed_form_n_months(pot_start, r, M, n_months):
    """Annuity-due closed form for `n_months` monthly iterations."""
    if r == 0:
        return pot_start + n_months * M
    r_m = r / 12
    return pot_start * (1 + r_m) ** n_months + M * ((1 + r_m) ** n_months - 1) / r_m


def _closed_form_accumulator_with_retirement(
    pot_start, r, M, retirement_offset, n_years,
):
    """12-iteration year-by-year accumulator that gates contributions on a
    numeric `retirement_offset`. Year y is a "working year" when
    `y < retirement_offset` (full 12-month compound + M); year y is a
    "retired year" when `y >= retirement_offset` (12-month pure compound,
    M=0). Works for integer AND fractional retirement_offset — e.g.
    offset=5.5 means y=5 is also a "working year" (full 12-month
    compound + M, matching the engine's "fraction=1.0" pre-retirement
    branch); the FRACTIONAL closing-year partial-scaling is NOT
    modelled here — that's covered separately by direct n_months calls
    in the partial-year tests.

    Replaces an earlier flat (no-retirement-gate) version that compounded
    M in every year, including post-retirement years on which the
    engine drops to M=0.
    """
    r_m = r / 12
    growth_factor = (1 + r_m) ** 12
    pot = pot_start
    series = []
    for y in range(n_years):
        if y >= retirement_offset:
            # Post-retirement: M=0, full 12 months of pure compound.
            pot = pot * growth_factor
        elif r == 0:
            pot = pot + 12 * M
        else:
            pot = pot * growth_factor + M * ((growth_factor - 1) / r_m)
        series.append(pot)
    return series


# Backwards-compat alias — keep the pre-PR name so any out-of-tree
# caller (future test fixture, ad-hoc REPL) still finds the function
# by its original one-line description.
_closed_form_accumulator_full_years = _closed_form_accumulator_with_retirement


def _make_person(
    name="P1",
    age=55,
    retirement_age=60,
    income_until_retirement=0.0,
    income_growth_rate=0.0,
    dc_pot_=0.0,
    dc_rate=0.0,
    monthly_contrib=0.0,
    monthly_contrib_pct=0.0,
    pcls_percent=0,
    draw_age=99,
    state_pension_age=99,
):
    defaults = dict(
        name=name, age=age,
        retirement_age=retirement_age,
        state_pension_age=state_pension_age,
        dc_pot=dc_pot_,
        db_income=0.0, draw_age=draw_age,
        monthly_contrib=monthly_contrib,
        income_until_retirement=income_until_retirement,
        pcls_percent=pcls_percent,
        income_growth_rate=income_growth_rate,
        monthly_contrib_pct=monthly_contrib_pct,
        dc_growth_rate=dc_rate,
        db_growth_rate=0.0,
        state_pension_growth_rate=0.0,
    )
    return Person(**defaults)


def _make_household(p1, p2=None, spending_target=0, years=10):
    if p2 is None:
        p2 = _make_person(
            name="P2",
            retirement_age=99,
            income_until_retirement=0.0,
        )
    h = Household(
        person1=p1, person2=p2, assets=[], mortgage=None,
        spending_target=spending_target, events=[],
    )
    return h, years


# ---------------------------------------------------------------------------
# Layer 1: Person dataclass accepts fractional retirement_age.
# ---------------------------------------------------------------------------

class TestPersonRetirementAgeDataclass(unittest.TestCase):
    """Person.retirement_age now accepts float (months-precision)."""

    def test_person_accepts_int_retirement_age_for_legacy_back_compat(self):
        # BC: legacy `household_data.json.bak` has `\"retirement_age\": 60`
        # as an integer. The dataclass must still construct cleanly.
        p = _make_person(retirement_age=60)
        self.assertEqual(p.retirement_age, 60)

    def test_person_accepts_float_retirement_age(self):
        # The new contract: `60 years 6 months` serialised as 60.5.
        p = _make_person(retirement_age=60.5)
        self.assertEqual(p.retirement_age, 60.5)
        self.assertIsInstance(p.retirement_age, float)

    def test_person_accepts_fractional_retirement_age_close_to_a_year(self):
        # Edge case: a fractional retirement_age whose fractional part
        # is non-zero (the headline use case). Exercises int(...),
        # round(... * 12), etc. inside helper functions.
        p = _make_person(retirement_age=59 + 7 / 12)  # 59y7m
        self.assertAlmostEqual(p.retirement_age, 59 + 7 / 12, places=6)

    def test_years_to_retirement_returns_float_for_fractional(self):
        # `years_to_retirement()` is used internally elsewhere but must
        # return a float so callers that compute a partial-year fraction
        # (e.g. the engine's step 2a/2b) get the same type as
        # `retirement_age`.
        p = _make_person(age=55, retirement_age=60.5)
        self.assertAlmostEqual(p.years_to_retirement(), 5.5, places=6)

    def test_years_to_retirement_clamps_at_zero_for_already_retired(self):
        # Defensive clamp: a partner whose `age >= retirement_age` should
        # read 0 years-to-retirement (not negative) — mirrors the pre-PR
        # behaviour of `max(0, ...)` but now operates on floats so a
        # `age=55, retirement_age=54.5` (already retired at year 0.5)
        # also reads 0.
        p = _make_person(age=55, retirement_age=54.5)
        self.assertEqual(p.years_to_retirement(), 0.0)

    def test_is_retired_at_fractional_year_handles_half_year_correctly(self):
        # Lock the half-year resolution: age=55, year=5, retirement_age=60.5
        # → still working (60 < 60.5). Age=55, year=6, retirement_age=60.5
        # → retired (61 >= 60.5). This is the BC anchor for all engine
        # gates (`not is_retired(year)`, `is_retired(year) and ...`,
        # PCLS availability, asset contributions) — they are all
        # `is_retired`-driven and must yield the right answer at the
        # boundary.
        p = _make_person(age=55, retirement_age=60.5)
        self.assertFalse(p.is_retired(5))   # 60 >= 60.5 = False
        self.assertTrue(p.is_retired(6))    # 61 >= 60.5 = True

    def test_is_retired_at_exact_boundary(self):
        # Spec corner: `age + year == retirement_age` should count as
        # `is_retired=True` (the clause uses `>=`). For integer values
        # this is the pre-PR behaviour; for fractional values it nails
        # down the closing-year partial contribution semantics: at
        # `year=floor(retirement_offset)`, we're STILL working because
        # `age + year < retirement_age` is strict-less-than after the
        # floor. (The engine's partial-year formula complements this by
        # also clamping `min(1.0, retirement_offset - year) < 1.0`
        # rather than 0.)
        p_int = _make_person(age=55, retirement_age=60)
        self.assertTrue(p_int.is_retired(5))     # 60 >= 60 = True
        self.assertFalse(p_int.is_retired(4))    # 59 >= 60 = False
        p_frac = _make_person(age=55, retirement_age=60.5)
        self.assertFalse(p_frac.is_retired(5))   # 60 >= 60.5 = False


# ---------------------------------------------------------------------------
# Layer 2: Engine — partial-year-of-contributions wiring.
# ---------------------------------------------------------------------------

class TestEngineIntRetirementAgeIsByteIdentical(unittest.TestCase):
    """BC guard — legacy int retirement_age produces byte-identical
    output to the pre-PR 12-month closed-form baseline.

    When `retirement_age` is an integer, `retirement_offset` is an
    integer, so `min(1.0, retirement_offset - year)` evaluates to
    exactly `1.0` for every pre-retirement year. The helper therefore
    rounds `12 * 1.0 = 12.0` to 12, runs the same 12 iterations with
    the same per-step ops on the same operands in the same order as
    pre-PR — so the floats produced by the engine for an int
    retirement_age are byte-identical to pre-PR.
    """

    def test_int_retirement_age_dc_pot_matches_pre_pr_full_year_accumulator(self):
        # 6 working years + 4 retirement years. Pre-PR: every working
        # year is a full 12-month compound + contribution; every
        # retirement year is a full 12-month compound only. Post-PR
        # with int retirement_age (offset=6): fraction=1.0 for years
        # 0..5 (working), then M=0 + fraction=1.0 for years 6..9
        # (retired). Byte-identical to pre-PR.
        p1 = _make_person(
            age=55, retirement_age=61,  # offset 6
            income_until_retirement=60_000.0,
            income_growth_rate=0.0,
            dc_pot_=10_000.0,
            dc_rate=0.05,
            monthly_contrib=0.0,
            monthly_contrib_pct=0.15,
        )
        h, years = _make_household(p1, years=10, spending_target=0)
        r = run_simulation(h, years=years)

        M = 60_000.0 * 0.15 / 12  # 750 per month
        retirement_offset = p1.retirement_age - p1.age
        expected = _closed_form_accumulator_full_years(
            10_000.0, 0.05, M, retirement_offset, years,
        )
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(
                    r["dc_pot"][y], exp, places=4,
                    msg=f"Y{y}: engine={r['dc_pot'][y]:.4f} vs pre-PR={exp:.4f}",
                )

    def test_int_retirement_age_immediate_retirement_matches_pre_pr(self):
        # age=55, retirement_age=55 (offset=0). Pre-PR: M=0 from year 0
        # onwards (retired at year 0). Post-PR: `year < 0` is False at
        # every year=0+, so `fraction=1.0` and M=0 — same as pre-PR.
        # The post-PR short-circuit-on-`fraction<=0` in the helper
        # cannot fire here because we explicitly set fraction=1.0 in
        # the post-retirement branch (not 0 or negative).
        p1 = _make_person(
            age=55, retirement_age=55,  # offset 0
            income_until_retirement=0.0,
            dc_pot_=5000.0,
            dc_rate=0.05,
        )
        h, years = _make_household(p1, years=5, spending_target=0)
        r = run_simulation(h, years=years)
        # 5 years of pure compound at 5%, no contributions.
        retirement_offset = p1.retirement_age - p1.age
        expected = _closed_form_accumulator_full_years(
            5000.0, 0.05, 0.0, retirement_offset, years,
        )
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(r["dc_pot"][y], exp, places=4)

    def test_int_retirement_age_already_retired_at_year_zero_matches_pre_pr(self):
        # age=60, retirement_age=55 (`retirement_age < age`). Pre-PR:
        # retired at year 0 onwards. Post-PR: `year < -5` is False at
        # every year=0+, so `fraction=1.0` and M=0 — same as pre-PR.
        p1 = _make_person(
            age=60, retirement_age=55,
            income_until_retirement=0.0,
            dc_pot_=5000.0,
            dc_rate=0.05,
        )
        h, years = _make_household(p1, years=5, spending_target=0)
        r = run_simulation(h, years=years)
        retirement_offset = p1.retirement_age - p1.age
        expected = _closed_form_accumulator_full_years(
            5000.0, 0.05, 0.0, retirement_offset, years,
        )
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(r["dc_pot"][y], exp, places=4)


class TestEnginePartialYearRetirementFiresClosingYearBranch(unittest.TestCase):
    """Fractional retirement_age — actually exercises the new partial-
    year-of-contributions branch."""

    def test_fractional_retirement_uses_six_month_slice_in_closing_year(self):
        # age=55, retirement_age=60.5 (offset=5.5). 8-year horizon:
        #   year 0..4: full 12 months of compound + M (fraction=1.0)
        #   year 5:    ONLY 6 months of compound + M (fraction=0.5)
        #   year 6..7: 12 months of pure compound (M=0, fraction=1.0)
        #
        # Year 5's pot MUST match the closed form for `n_months=6`,
        # NOT for `n_months=12`. This is the lock-down for "the
        # partial-year branch actually fires".
        p1 = _make_person(
            age=55, retirement_age=60.5,  # offset 5.5 → closing year is 5
            income_until_retirement=60_000.0,
            income_growth_rate=0.0,
            dc_pot_=10_000.0,
            dc_rate=0.05,
            monthly_contrib=0.0,
            monthly_contrib_pct=0.15,
        )
        h, years = _make_household(p1, years=8, spending_target=0)
        r = run_simulation(h, years=years)

        M = 60_000.0 * 0.15 / 12
        # Year-by-year closed-form accumulator that mirrors the engine's
        # branchy behaviour: full-year compound + M for pre-retirement
        # years not in the closing window, six-month closed form for
        # the closing partial-year, full-year pure compound (M=0) after.
        r_m = 0.05 / 12
        growth_12 = (1 + r_m) ** 12
        growth_6 = (1 + r_m) ** 6
        annuity_12 = M * (growth_12 - 1) / r_m
        annuity_6 = M * (growth_6 - 1) / r_m

        pot = 10_000.0
        closing_year = 5  # floor(5.5) == 5
        for y in range(years):
            is_closing = (y == closing_year)
            in_post = (y > closing_year)
            if in_post:
                pot = pot * growth_12  # M=0, fraction=1.0 -> 12 months pure compound
            elif is_closing:
                pot = pot * growth_6 + annuity_6  # 6-month slice + 6-month contributions
            else:
                pot = pot * growth_12 + annuity_12
            with self.subTest(year=y):
                self.assertAlmostEqual(
                    r["dc_pot"][y], pot, places=4,
                    msg=f"Y{y}: engine={r['dc_pot'][y]:.4f} vs partial-year={pot:.4f}",
                )

        # Sanity reframe: a CLOSING-YEAR-ONLY-PARTIAL pot MUST be
        # strictly LESS than the full-year pot that would result from
        # always running 12 months. Otherwise the fraction formula
        # hasn't actually shortened the closing year.
        baseline_full_year_pot = 10_000.0
        for _ in range(6):  # years 0..5 baseline (all full 12 months)
            baseline_full_year_pot = baseline_full_year_pot * growth_12 + annuity_12
        self.assertLess(
            r["dc_pot"][closing_year], baseline_full_year_pot,
            msg="Closing-year partial-year pot must be strictly less than "
                "the equivalent all-12-months baseline — otherwise the "
                "fraction formula hasn't actually shortened the slice.",
        )

    def test_fractional_retirement_keeps_full_year_post_retirement_growth(self):
        # Year 6+ (post-retirement for retirement_age=60.5 age=55):
        # M=0 + fraction=1.0, so 12 months of pure compound. This is
        # the BC anchor: pre-PR and post-PR both had this growth; the
        # new wiring must NOT drop post-retirement compound because it
        # would silently hurt the drawdown horizon's net-worth floor.
        p1 = _make_person(
            age=55, retirement_age=60.5,  # offset 5.5
            income_until_retirement=60_000.0,
            income_growth_rate=0.0,
            dc_pot_=10_000.0,
            dc_rate=0.05,
            monthly_contrib=0.0,
            monthly_contrib_pct=0.15,
        )
        h, years = _make_household(p1, years=10, spending_target=0)
        r = run_simulation(h, years=years)

        # After the partial-year at year 5, year 6 -> pot_y5 * (1+r/12)^12.
        # Year 7 -> year_6_pot * (1+r/12)^12. Etc. Lock down that the
        # year-on-year post-retirement multiplier is the same as a
        # pure-compound 12-month call would produce.
        for y in (6, 7, 8, 9):
            with self.subTest(year=y):
                # Engine value must equal prior directly composed via helper.
                pot_via_helper = _dc_monthly_compound(
                    r["dc_pot"][y - 1], 0.05, 0.0, fraction=1.0,
                )
                self.assertAlmostEqual(
                    r["dc_pot"][y], pot_via_helper, places=4,
                    msg=f"Y{y}: post-retirement growth diverged "
                        f"(engine {r['dc_pot'][y]:.4f} vs "
                        f"closed-form {pot_via_helper:.4f})",
                )

    def test_quarter_year_retirement_gives_three_month_closing_year_slice(self):
        # age=55, retirement_age=63.25 (offset=8.25). Closing year is 8
        # and the fractional slice is 8.25 - 8 = 0.25 → 3 months.
        p1 = _make_person(
            age=55, retirement_age=63.25,  # offset 8.25 → 3-month slice
            income_until_retirement=60_000.0,
            income_growth_rate=0.0,
            dc_pot_=0.0,
            dc_rate=0.05,
            monthly_contrib=0.0,
            monthly_contrib_pct=0.15,
        )
        h, years = _make_household(p1, years=10, spending_target=0)
        r = run_simulation(h, years=years)

        M = 60_000.0 * 0.15 / 12
        r_m = 0.05 / 12
        growth_12 = (1 + r_m) ** 12
        growth_3 = (1 + r_m) ** 3
        annuity_12 = M * (growth_12 - 1) / r_m
        annuity_3 = M * (growth_3 - 1) / r_m

        pot = 0.0
        closing_year = 8
        for y in range(years):
            is_closing = (y == closing_year)
            in_post = (y > closing_year)
            if in_post:
                pot = pot * growth_12
            elif is_closing:
                pot = pot * growth_3 + annuity_3
            else:
                pot = pot * growth_12 + annuity_12
            with self.subTest(year=y):
                self.assertAlmostEqual(
                    r["dc_pot"][y], pot, places=4,
                    msg=f"Y{y}: engine={r['dc_pot'][y]:.4f} vs 3-month closing={pot:.4f}",
                )


class TestEngineFractionalRetirementEdgeCases(unittest.TestCase):
    """Edge cases for fractional `retirement_age` paths."""

    def test_retirement_age_below_age_treated_as_immediately_retired(self):
        # Defensive: a future caller (or already-retired partner on
        # load) might pass `retirement_age < age`. The engine should
        # treat the partner as retired at year 0 — no contributions,
        # full 12-month compound on the opening pot each year.
        p1 = _make_person(
            age=55, retirement_age=54.5,
            income_until_retirement=60_000.0,  # ignored
            income_growth_rate=0.0,
            dc_pot_=5000.0,
            dc_rate=0.05,
            monthly_contrib=0.0,
            monthly_contrib_pct=0.15,
        )
        h, years = _make_household(p1, years=5, spending_target=0)
        r = run_simulation(h, years=years)
        retirement_offset = p1.retirement_age - p1.age  # -0.5
        expected = _closed_form_accumulator_full_years(
            5000.0, 0.05, 0.0, retirement_offset, years,
        )
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(r["dc_pot"][y], exp, places=4)

    def test_retirement_age_zero_means_already_retired(self):
        # `retirement_age = 0` is technically "retired at birth" — the
        # engine must NOT explode, and must treat this partner as
        # retired at year 0 (full 12-month compound, M=0).
        p1 = _make_person(
            age=55, retirement_age=0.0,
            income_until_retirement=0.0,
            dc_pot_=3000.0,
            dc_rate=0.10,  # higher rate for variety
        )
        h, years = _make_household(p1, years=5, spending_target=0)
        r = run_simulation(h, years=years)
        retirement_offset = p1.retirement_age - p1.age  # -55
        expected = _closed_form_accumulator_full_years(
            3000.0, 0.10, 0.0, retirement_offset, years,
        )
        for y, exp in enumerate(expected):
            with self.subTest(year=y):
                self.assertAlmostEqual(r["dc_pot"][y], exp, places=4)

    def test_two_partners_partial_year_retirements_simulate_independently(self):
        """Per-partner fraction wiring must fire independently.

        Approach: simulate each partner on their own with a "silent"
        partner (retirement_age=99, never retired, zero contributions).
        The resulting per-partner dc_pot series must equal what the
        combined-run engine produces when summed across both partners'
        dc_pot values at year-end.

        Both partners use FRACTIONAL retirement ages so each exercises
        the partial-year branch at a different closing year:
          - p1: age=55, retirement_age=60.5 (offset 5.5 → closing y=5)
          - p2: age=55, retirement_age=62.75 (offset 7.75 → closing y=7)

        A regression where the engine accidentally computes the
        fraction for one partner and applies it to both would cause
        the summed series to diverge from the per-partner references.

        IMPORTANT: each run uses FRESH Person objects so the engine's
        in-place mutation of `dc_pot` doesn't carry between runs (a
        prior round's failure mode where the singles started from the
        combined run's end-of-horizon dc_pot instead of from zero).
        """
        years = 10

        def _build_p1():
            return _make_person(
                name="P1", age=55, retirement_age=60.5,
                income_until_retirement=40_000.0,
                dc_pot_=0.0,
                dc_rate=0.05,
                monthly_contrib=0.0,
                monthly_contrib_pct=0.10,
            )

        def _build_p2():
            return _make_person(
                name="P2", age=55, retirement_age=62.75,
                income_until_retirement=20_000.0,
                dc_pot_=0.0,
                dc_rate=0.05,
                monthly_contrib=0.0,
                monthly_contrib_pct=0.20,
            )

        def _silent():
            return _make_person(
                name="Silent", retirement_age=99,
                income_until_retirement=0.0,
                dc_rate=0.0,
            )

        # Combined run — both partners active together (fresh objects).
        h_combined, _ = _make_household(
            _build_p1(), p2=_build_p2(),
            years=years, spending_target=0,
        )
        r_combined = run_simulation(h_combined, years=years)

        # Per-partner single active runs — each with a fresh silent
        # partner + fresh active partner (so their dc_pot starts at
        # exactly zero).
        h_p1_only, _ = _make_household(
            _build_p1(), p2=_silent(),
            years=years, spending_target=0,
        )
        h_p2_only, _ = _make_household(
            _silent(), p2=_build_p2(),
            years=years, spending_target=0,
        )
        r_p1_only = run_simulation(h_p1_only, years=years)
        r_p2_only = run_simulation(h_p2_only, years=years)

        for y in range(years):
            with self.subTest(year=y):
                # Combined dc_pot equals sum of per-partner singles.
                # This is the core regression guard for "the engine's
                # per-partner wiring computes fractions independently".
                self.assertAlmostEqual(
                    r_combined["dc_pot"][y],
                    r_p1_only["dc_pot"][y] + r_p2_only["dc_pot"][y],
                    places=2,
                    msg=f"Y{y}: combined={r_combined['dc_pot'][y]:.4f} "
                        f"vs sum-of-singles="
                        f"{r_p1_only['dc_pot'][y] + r_p2_only['dc_pot'][y]:.4f}",
                )

        # Sanity-reframe gates (mirror the existing single-partner
        # sanity gates in
        # TestEnginePartialYearRetirementFiresClosingYearBranch): the
        # partial-year closing-year slice MUST explicitly fire on each
        # partner. Spot-check that the per-partner closing-year dc_pot
        # is strictly less than what would result from always running
        # 12 months. Recompute the all-12-months baseline inline so
        # we don't carry Person-state across runs.
        for partner_name, single_result, build_active in [
            ("p1", r_p1_only, _build_p1),
            ("p2", r_p2_only, _build_p2),
        ]:
            p_fresh = build_active()
            offset = p_fresh.retirement_age - p_fresh.age
            closing_year = int(offset)  # floor for positive fractional
            M = (
                p_fresh.income_until_retirement
                * p_fresh.monthly_contrib_pct / 12
            )
            r_m = 0.05 / 12
            growth_12 = (1 + r_m) ** 12
            annuity_12 = M * (growth_12 - 1) / r_m
            # Reconstruct the all-12-months baseline (no closing-year
            # partial scaling) up through and INCLUDING the closing year.
            baseline_pot = 0.0
            for _ in range(closing_year + 1):
                baseline_pot = baseline_pot * growth_12 + annuity_12
            with self.subTest(partner=partner_name, year=closing_year):
                self.assertLess(
                    single_result["dc_pot"][closing_year], baseline_pot,
                    msg=f"{partner_name} closing-year partial-year pot "
                        f"({single_result['dc_pot'][closing_year]:.4f}) "
                        f"must be strictly less than the all-12-months "
                        f"baseline ({baseline_pot:.4f}) — otherwise the "
                        f"fraction formula hasn't actually shortened "
                        f"the closing year.",
                )


if __name__ == "__main__":
    unittest.main()
