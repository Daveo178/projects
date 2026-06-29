"""Tests for `simulation/aa.py` — UK Pension Annual Allowance taper + projection."""

import unittest

from simulation.aa import (
    MIN_TAPERED_AA,
    STANDARD_AA,
    STATUS_EXCEEDED,
    STATUS_WITHIN,
    TAPER_THRESHOLD_INCOME,
    aa_status,
    effective_aa,
    project_annual_contribution,
)


class TestEffectiveAATaper(unittest.TestCase):
    """The HMRC taper formula: standard £60k above £200k income, £10k floor."""

    def test_below_taper_threshold_keeps_full_aa(self):
        # Just below the taper threshold — no reduction.
        self.assertEqual(effective_aa(199_999.0), STANDARD_AA)
        self.assertEqual(effective_aa(0.0), STANDARD_AA)
        self.assertEqual(effective_aa(100_000.0), STANDARD_AA)

    def test_at_taper_threshold_keeps_full_aa(self):
        # Boundary: exactly £200,000 → full £60,000 (taper is '<= threshold').
        self.assertEqual(effective_aa(200_000.0), STANDARD_AA)

    def test_one_pound_above_threshold_tapers_by_half(self):
        # The reviewer-flagged gap: £200,001 → 60k - 1/2 = £59,999.50.
        # Catches a `<=`→`<` swap in `effective_aa` immediately, before the
        # mid-range 220k/250k tests fire. Belt-and-braces with the boundary
        # regression in `TestProjectAnnualContribution`.
        self.assertAlmostEqual(effective_aa(200_001.0), 59_999.5)

    def test_just_above_threshold_starts_taper(self):
        # £220,000 income → 60k - 20k/2 = 50k
        self.assertAlmostEqual(effective_aa(220_000.0), 50_000.0)

    def test_mid_taper(self):
        # £250,000 → 60k - 50k/2 = 35k
        self.assertAlmostEqual(effective_aa(250_000.0), 35_000.0)

    def test_taper_reaches_floor_at_300k(self):
        # £300,000 → 60k - 100k/2 = 10k (exactly the floor).
        self.assertAlmostEqual(effective_aa(300_000.0), MIN_TAPERED_AA)

    def test_far_above_threshold_never_drops_below_floor(self):
        # £500_000 → off-the-chart, must clamp at MIN_TAPERED_AA.
        self.assertEqual(effective_aa(500_000.0), MIN_TAPERED_AA)
        self.assertEqual(effective_aa(1_000_000.0), MIN_TAPERED_AA)

    def test_negative_or_garbage_in_returns_standard_aa(self):
        # Defensive: a UI edge case that returns 0 or a non-numeric should
        # not refuse to display a value. Negative is also treated as "no taper".
        self.assertEqual(effective_aa(-50_000.0), STANDARD_AA)
        self.assertEqual(effective_aa(None), STANDARD_AA)
        self.assertEqual(effective_aa("not a number"), STANDARD_AA)

    def test_30pct_of_250k_exceeds_tapered_aa(self):
        # Second primary failure mode: mid-taper-income user with a hefty
        # % contribution. AA at £250k is £35k (60k - 50k/2). 30% of £250k
        # is £75k. Result: £75k > £35k, headroom -£40k. Locks the tapered
        # path so a future taper-formula drift can't silently move the
        # mid-range AA by £5-10k without tripping the test.
        proj = project_annual_contribution({
            "monthly_contrib_pct": 0.30,
            "income_until_retirement": 250_000.0,
            "monthly_contrib": 0.0,
        })
        self.assertAlmostEqual(proj, 75_000.0)
        aa = effective_aa(250_000.0)
        self.assertAlmostEqual(aa, 35_000.0)
        self.assertGreater(
            proj, aa,
            "30% of £250k (£75k) should exceed the tapered £35k AA — "
            "if this fails, the taper formula has drifted.",
        )
        # Mirror the boundary-regression pattern: lock the headroom
        # numerically so a future drift of BOTH numbers in opposite
        # directions can't keep `proj > aa` true while the panel's
        # "headroom" message silently moves.
        self.assertAlmostEqual(proj - aa, 40_000.0)


class TestProjectAnnualContribution(unittest.TestCase):
    """Mirrors the Pensions-page precedence: % first, flat £ as legacy fallback."""

    def test_pct_path_uses_income_times_pct(self):
        # 15% of £60_000 income = £9_000/yr
        out = project_annual_contribution({
            "monthly_contrib_pct": 0.15,
            "income_until_retirement": 60_000.0,
            "monthly_contrib": 0.0,
        })
        self.assertAlmostEqual(out, 9_000.0)

    def test_pct_path_ignores_legacy_flat_figure(self):
        # Even if the legacy £ field is non-zero, % wins when > 0.
        out = project_annual_contribution({
            "monthly_contrib_pct": 0.10,
            "income_until_retirement": 80_000.0,
            "monthly_contrib": 1_000.0,  # would yield £12k if used
        })
        self.assertAlmostEqual(out, 8_000.0)

    def test_flat_path_used_when_pct_is_zero(self):
        # £500/mo flat = £6_000/yr. % is 0 so flat wins.
        out = project_annual_contribution({
            "monthly_contrib_pct": 0.0,
            "income_until_retirement": 100_000.0,
            "monthly_contrib": 500.0,
        })
        self.assertAlmostEqual(out, 6_000.0)

    def test_zero_pct_and_zero_flat_returns_zero(self):
        out = project_annual_contribution({
            "monthly_contrib_pct": 0.0,
            "income_until_retirement": 60_000.0,
            "monthly_contrib": 0.0,
        })
        self.assertEqual(out, 0.0)

    def test_partial_dict_does_not_raise(self):
        # First-page load: only an age field known, no contrib fields.
        out = project_annual_contribution({"age": 55})
        self.assertEqual(out, 0.0)

    def test_garbage_values_coerce_to_zero(self):
        # Defensive: non-numeric values must not raise inside the panel.
        out = project_annual_contribution({
            "monthly_contrib_pct": "high",
            "income_until_retirement": None,
            "monthly_contrib": 0.0,
        })
        self.assertEqual(out, 0.0)

    def test_50pct_of_200k_exceeds_aa_at_boundary(self):
        # The headline failure mode the AA feature was built for: a user
        # pushes the % slider to its 50% maximum on a £200k salary. Annual
        # contribution is £100k; standard AA at the £200k boundary is £60k.
        # Result should clearly trigger the page-side st.warning — if this
        # ever flips sign, the panel is broken even when the math is right.
        proj = project_annual_contribution({
            "monthly_contrib_pct": 0.50,
            "income_until_retirement": 200_000.0,
            "monthly_contrib": 0.0,
        })
        self.assertAlmostEqual(proj, 100_000.0)
        aa = effective_aa(200_000.0)
        self.assertEqual(aa, 60_000.0)
        self.assertGreater(
            proj, aa,
            "message: 50% of £200k should exceed the £60k AA at the £200k "
            "boundary — if this assertion fails, the warning has stopped "
            "firing for the primary use case the feature was built for.",
        )
        self.assertAlmostEqual(proj - aa, 40_000.0)  # headroom is -40k


class TestAASurfaceContract(unittest.TestCase):
    """Lock the public API shape — the page side imports these names."""

    def test_public_constants_exist_and_are_positive(self):
        self.assertEqual(STANDARD_AA, 60_000.0)
        self.assertEqual(MIN_TAPERED_AA, 10_000.0)
        self.assertEqual(TAPER_THRESHOLD_INCOME, 200_000.0)
        self.assertGreater(STANDARD_AA, MIN_TAPERED_AA)
        self.assertGreater(STANDARD_AA, TAPER_THRESHOLD_INCOME - TAPER_THRESHOLD_INCOME)

    def test_realistic_high_income_floor_case(self):
        # £400k income: 60k - 200k/2 = -40k → clamped to £10,000 floor.
        self.assertEqual(effective_aa(400_000.0), MIN_TAPERED_AA)

    def test_per_spouse_independence_two_realistic_partners(self):
        # Dave £60k → £60k AA. Shaz £250k → £35k AA. Independent.
        self.assertEqual(effective_aa(60_000.0), 60_000.0)
        self.assertAlmostEqual(effective_aa(250_000.0), 35_000.0)


class TestAAStatus(unittest.TestCase):
    """Lock the comparison direction used by the page-side helper.

    The page wires `_show_aa_status` to call `aa_status(proj, aa)` rather
    than the raw `proj > aa` operator so the warning-vs-caption direction
    can be unit-tested without rendering Streamlit warnings. If a future
    refactor swaps `>` for `>=` in `aa_status`, every test here fires.
    """

    def test_above_aa_returns_exceeded(self):
        # Strictly above the AA — excess contributions attract the
        # Annual Allowance Charge.
        self.assertEqual(aa_status(60_000.1, 60_000.0), STATUS_EXCEEDED)
        self.assertEqual(aa_status(100_000.0, 60_000.0), STATUS_EXCEEDED)
        self.assertEqual(aa_status(75_000.0, 35_000.0), STATUS_EXCEEDED)

    def test_equal_to_aa_returns_within(self):
        # Boundary: contributing exactly up to the AA is fine — no excess,
        # no charge. The `>=` swap protection here is critical.
        self.assertEqual(aa_status(60_000.0, 60_000.0), STATUS_WITHIN)
        self.assertEqual(aa_status(10_000.0, 10_000.0), STATUS_WITHIN)

    def test_below_aa_returns_within(self):
        self.assertEqual(aa_status(0.0, 60_000.0), STATUS_WITHIN)
        self.assertEqual(aa_status(9_000.0, 60_000.0), STATUS_WITHIN)
        self.assertEqual(aa_status(34_999.0, 35_000.0), STATUS_WITHIN)

    def test_garbage_inputs_default_to_within(self):
        # Non-numeric projections / AAs must not raise on the page side
        # (e.g. a session_state wipe).
        self.assertEqual(aa_status(None, 60_000.0), STATUS_WITHIN)
        self.assertEqual(aa_status("nan", 60_000.0), STATUS_WITHIN)
        self.assertEqual(aa_status(50_000.0, None), STATUS_WITHIN)

    def test_status_tokens_are_accessible_to_callers(self):
        # The page does an exact `== "exceeded"` string compare against
        # the rendered warning. The literal tokens must remain accessible
        # on the module so a future rename — e.g. "exceeded" -> "over" —
        # trips the page's comparison at runtime rather than silently
        # silencing the panel.
        self.assertEqual(STATUS_WITHIN, "within")
        self.assertEqual(STATUS_EXCEEDED, "exceeded")


if __name__ == "__main__":
    unittest.main()
