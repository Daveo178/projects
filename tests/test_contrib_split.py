"""
Tests for the Quick-Estimate personal + employer contribution split.

What this module locks down
===========================

1. Engine `_monthly_dc_contrib`:
     - New fields (personal_contrib_pct / personal_contrib_flat_monthly
       / employer_contrib_pct) sum correctly per year.
     - Personal % precedence over personal flat: when BOTH are set,
       the engine uses % (matches `% > £` rule already used by the
       legacy `monthly_contrib_pct` vs `monthly_contrib` helpers).
     - Legacy fields preserved byte-for-byte for plans that pre-date
       the new model — when ALL THREE new fields are 0, behaviour is
       identical to the pre-refactor engine.

2. AA projection (`simulation/aa.py::project_annual_contribution`):
     - New split-mode projection = income*(pct + employer_pct) when
       either party pays by %.
     - New flat-mode projection = personal_flat*12 + income*employer_pct.
     - Legacy path preserved verbatim for backward-compatibility.

3. Model defaults (`model_defaults.py`):
     - A freshly-seeded partner has personal=5%, employer=3%, flat £/yr=0.
     - Legacy `monthly_contrib_pct` stays at 0.15 for the detailed
       Pensions page's existing slider.

These tests are intentionally small and pixel-perfect (hand-derived
expected values) so a future refactor that subtly changes the
aggregation precedence or the BC fallback order trips them
immediately.
"""
import unittest
from types import SimpleNamespace

from simulation.aa import (
    project_annual_contribution,
    effective_aa,
    aa_status,
    STATUS_EXCEEDED,
)
from simulation.engine import _monthly_dc_contrib
from model_defaults import default_partner_dict


# A small helper that builds a Person-shaped namespace with the new
# fields, so the engine helper's `getattr` defensive reads return
# precisely what we set. Mirrors the SimpleNamespace approach used in
# `tests/test_dc_compound.py::TestMonthlyDcContrib._person` so the
# test pattern is repeatable.
def _person(
    personal_pct=0.0,
    personal_flat=0.0,
    employer_pct=0.0,
    legacy_pct=0.0,
    legacy_flat=0.0,
):
    return SimpleNamespace(
        personal_contrib_pct=personal_pct,
        personal_contrib_flat_monthly=personal_flat,
        employer_contrib_pct=employer_pct,
        monthly_contrib_pct=legacy_pct,
        monthly_contrib=legacy_flat,
    )


class TestEngineMonthlyDcContribSplit(unittest.TestCase):
    """`_monthly_dc_contrib` aggregates personal + employer for the new
    split model without doubling the legacy fields when both are
    present."""

    def test_only_personal_pct_zero_employer_returns_personal(self):
        p = _person(personal_pct=0.05, employer_pct=0.0)
        income = 60_000.0
        expected = income * 0.05 / 12
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, income), expected, places=6,
        )

    def test_only_employer_pct_zero_personal_returns_employer(self):
        p = _person(personal_pct=0.0, employer_pct=0.03)
        income = 60_000.0
        expected = income * 0.03 / 12
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, income), expected, places=6,
        )

    def test_personal_pct_plus_employer_sums(self):
        p = _person(personal_pct=0.05, employer_pct=0.03)
        income = 60_000.0
        # 5% + 3% = 8% of £60k/yr => £4,800/yr => £400/mo.
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, income), 400.0, places=4,
        )

    def test_personal_flat_uses_flat_over_pct_when_pct_zero(self):
        p = _person(personal_pct=0.0, personal_flat=150.0, employer_pct=0.0)
        # % is zero -> engine honours flat £/month directly.
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, indexed_income_ignored()),
            150.0, places=6,
        )

    def test_personal_pct_wins_over_personal_flat_when_both_set(self):
        # % > £ precedence — same contract as the legacy
        # engine `_monthly_dc_contrib` so a plan that has both
        # always resolves to the % reading.
        p = _person(
            personal_pct=0.05, personal_flat=9999.0, employer_pct=0.0,
        )
        income = 60_000.0
        expected = income * 0.05 / 12
        # Should NOT see 9999.0 — that's the precedence assertion.
        self.assertNotEqual(_monthly_dc_contrib(p, income), 9999.0)
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, income), expected, places=6,
        )

    def test_personal_flat_plus_employer(self):
        # The "self-employed / irregular income" use case — flat £
        # for personal + employer pays a % on top. A £200/mo
        # self-employed personal + 3% employer on £60k salary:
        #   personal = £200/mo
        #   employer = 60k * 3%/12 = £150/mo
        #   total    = £350/mo
        p = _person(
            personal_pct=0.0,
            personal_flat=200.0,
            employer_pct=0.03,
        )
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, 60_000.0), 350.0, places=4,
        )

    def test_legacy_path_preserved_when_all_new_fields_zero(self):
        # BC: a plan with ONLY legacy fields behaves exactly like the
        # pre-refactor engine.
        p = _person(legacy_pct=0.15)
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, 60_000.0),
            60_000.0 * 0.15 / 12, places=6,
        )
        p = _person(legacy_flat=600.0)
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, 60_000.0), 50.0, places=6,
        )
        p = _person()  # all zero
        self.assertEqual(_monthly_dc_contrib(p, 60_000.0), 0.0)

    def test_new_fields_zero_but_legacy_set_engine_uses_legacy(self):
        # When the new fields are exactly 0 BUT legacy fields are
        # non-zero, the engine should fall back to legacy behaviour
        # (i.e. NOT sum new-and-legacy; otherwise a user would see
        # contributions DOUBLE once the new fields are introduced and
        # the next migration touches the legacy fields).
        p = _person(
            personal_pct=0.0,
            employer_pct=0.0,
            legacy_pct=0.15,
            legacy_flat=0.0,
        )
        self.assertAlmostEqual(
            _monthly_dc_contrib(p, 60_000.0),
            60_000.0 * 0.15 / 12, places=6,
        )

    def test_zero_income_does_not_crash_with_new_fields(self):
        # Defensive: the Quick Estimate page writes
        # income_until_retirement=0 for all partners, so M must be
        # 0 when income is 0 and the new fields are set. Also locks
        # the "retired partner short-circuit" contract \u2014 the
        # engine caller passes `indexed_income=0` because
        # `_indexed_earned_income` returns 0 once the partner is
        # past `retirement_age`. Covers both zero-income and
        # retired-partner scenarios in one assertion.
        p = _person(personal_pct=0.05, employer_pct=0.03)
        self.assertEqual(_monthly_dc_contrib(p, 0.0), 0.0)


def indexed_income_ignored():
    """Sentinel helper for tests where the personal-flat branch is
    expected to ignore the income argument (the engine branches on
    `personal_contrib_pct == 0` and returns the flat £/month verbatim,
    so the income value is irrelevant to that path)."""
    return 0.0


class TestAAPersonalEmployerSplit(unittest.TestCase):
    """`project_annual_contribution` must include employer when set
    so the AA widget on the Pensions page stops UNDER-REPORTING the
    household's projected annual contributions."""

    def test_legacy_path_unchanged(self):
        # 15% of £60k = £9k — pre-refactor contract.
        out = project_annual_contribution({
            "monthly_contrib_pct": 0.15,
            "income_until_retirement": 60_000.0,
            "monthly_contrib": 0.0,
        })
        self.assertAlmostEqual(out, 9_000.0)

    def test_legacy_flat_path_unchanged(self):
        out = project_annual_contribution({
            "monthly_contrib_pct": 0.0,
            "monthly_contrib": 500.0,
            "income_until_retirement": 100_000.0,
        })
        self.assertAlmostEqual(out, 6_000.0)

    def test_personal_pct_plus_employer(self):
        # 5% personal + 3% employer on £60k = £4,800/yr.
        out = project_annual_contribution({
            "personal_contrib_pct": 0.05,
            "employer_contrib_pct": 0.03,
            "income_until_retirement": 60_000.0,
            "personal_contrib_flat_monthly": 0.0,
        })
        self.assertAlmostEqual(out, 4_800.0)

    def test_personal_flat_monthly_times_12_plus_employer(self):
        # £200/mo personal + 3% employer on £60k:
        #   personal = £200 * 12 = £2,400/yr
        #   employer = 60k * 3% = £1,800/yr
        #   total    = £4,200/yr
        out = project_annual_contribution({
            "personal_contrib_pct": 0.0,
            "personal_contrib_flat_monthly": 200.0,
            "employer_contrib_pct": 0.03,
            "income_until_retirement": 60_000.0,
        })
        self.assertAlmostEqual(out, 4_200.0)

    def test_personal_pct_ignores_personal_flat_when_both_set(self):
        # % > £ precedence — same contract as the engine helper.
        out = project_annual_contribution({
            "personal_contrib_pct": 0.05,
            "personal_contrib_flat_monthly": 12_000.0,  # would dominate
            "employer_contrib_pct": 0.03,
            "income_until_retirement": 60_000.0,
        })
        # 5% + 3% = 8% on £60k = £4,800/yr (NOT £144k from the
        # rogue flat field).
        self.assertAlmostEqual(out, 4_800.0)

    def test_zero_income_with_new_fields_does_not_crash(self):
        # Quick Estimate currently writes income=0 for all partners.
        # AA projection must NOT blow up on income=0 (would yield
        # £4800/yr projection, which is the same as the test above
        # with 8% — verifies no hidden division / interpolation).
        out = project_annual_contribution({
            "personal_contrib_pct": 0.05,
            "employer_contrib_pct": 0.03,
            "income_until_retirement": 0.0,
            "personal_contrib_flat_monthly": 0.0,
        })
        self.assertAlmostEqual(out, 0.0)

    def test_partial_dict_only_employer_returns_employer(self):
        # Defensive read: dict missing `personal_*` fields entirely
        # still projects the employer contribution correctly.
        out = project_annual_contribution({
            "employer_contrib_pct": 0.03,
            "income_until_retirement": 60_000.0,
        })
        self.assertAlmostEqual(out, 1_800.0)

    def test_aa_exceeded_with_employer_included(self):
        # 50% personal + 25% employer on £200k = £150k/yr \u2014
        # clearly above the \u00a360k tapered AA at the \u00a3200k
        # boundary, so the AA warning fires. Locks BOTH the
        # projection math AND the `aa_status` warning comparator
        # so a future drift in either side trips the same test.
        proj = project_annual_contribution({
            "personal_contrib_pct": 0.50,
            "employer_contrib_pct": 0.25,
            "income_until_retirement": 200_000.0,
        })
        self.assertAlmostEqual(proj, 150_000.0)
        aa = effective_aa(200_000.0)
        self.assertAlmostEqual(aa, 60_000.0)
        self.assertEqual(
            aa_status(proj, aa), STATUS_EXCEEDED,
            "50% personal + 25% employer on \u00a3200k should trip "
            "the AA warning \u2014 if this fails, the projection "
            "helper or the aa_status comparison direction has "
            "drifted.",
        )
        self.assertAlmostEqual(proj - aa, 90_000.0)


class TestModelDefaultsPersonalEmployer(unittest.TestCase):
    """`default_partner_dict` returns a partner with the new fields
    wired to sensible defaults so a brand-new Quick Estimate user
    lands with a realistic 5% personal + 3% employer split."""

    def test_dave_default_has_personal_and_employer(self):
        d = default_partner_dict("Dave", p1=True)
        self.assertEqual(d["personal_contrib_pct"], 0.05)
        self.assertEqual(d["personal_contrib_flat_monthly"], 0.0)
        self.assertEqual(d["employer_contrib_pct"], 0.03)

    def test_shaz_default_has_personal_and_employer(self):
        d = default_partner_dict("Shaz", p1=False)
        self.assertEqual(d["personal_contrib_pct"], 0.05)
        self.assertEqual(d["personal_contrib_flat_monthly"], 0.0)
        self.assertEqual(d["employer_contrib_pct"], 0.03)

    def test_legacy_pct_kept_for_pensions_page_bc(self):
        # The detailed Pensions page's existing slider still works
        # for users who haven't visited Quick Estimate — the legacy
        # `monthly_contrib_pct` default is preserved at 0.15.
        d = default_partner_dict("Dave", p1=True)
        self.assertEqual(d["monthly_contrib_pct"], 0.15)

    def test_default_partner_dict_returns_fresh_copy_each_call(self):
        # Sanity: each call returns an INDEPENDENT dict so a
        # page-side mutation doesn't bleed across partners.
        d1 = default_partner_dict("Dave", p1=True)
        d2 = default_partner_dict("Dave", p1=True)
        d1["personal_contrib_pct"] = 0.99
        self.assertEqual(d2["personal_contrib_pct"], 0.05)


if __name__ == "__main__":
    unittest.main()
