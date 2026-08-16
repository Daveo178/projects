"""Month-precision regression tests for the months-precision UI feature.

Three layers under test:

  1. `_split_years_into_years_and_months` + `_format_years_months_caption`
     round-trip math — the building blocks of the `years_and_months_input`
     widget defined in `simulation/years_and_months.py`. These are
     pure-Python helpers (no Streamlit dependency), so we can exercise
     them directly. Verifies (years, months) ↔ `years + months/12` round-
     trip is stable for typical ages and that the `months == 12`
     promotion corner case (FP round-up to 12) bumps a full extra
     year so the form never displays a 12-month disallowed value.

  2. Person dataclass with BOTH fractional `age` AND fractional
     `retirement_age` — `Person(age=55.5, retirement_age=60.5)` —
     producing a 5.0-year working arc via `run_simulation`. The
     `is_retired(year)` boundary `is_retired(5) = (55.5 + 5) >= 60.5 =
     True` makes year 5 the FIRST retired year, so years 0..4 are
     working (5 working years). The engine's call to
     `_dc_monthly_compound(...)` is duck-typed float so this should
     compose without engine changes.

  3. Legacy int-saved-JSON regression — `Person(age=55, retirement_age=60)`
     (an int household predating the float-typed storage model).
     Python coerces both ints to floats at the dataclass boundary
     and the engine's arithmetic is unchanged, so the resulting
     `dc_pot` trajectory must match the closed-form 5-year-working
     + 5-year-pure-compound accumulator (i.e. the bytes are
     byte-identical to the pre-feature behaviour, modulo FP noise).
     This is the BC anchor — without it, a downstream page that
     reads an int-saved JSON via the float pipeline could
     silently drift by one or more years.

Mirrors the partial-year scaling applied to mortgage amortisation in
the engine's step 4 (`fraction = min(1.0, end_year - year)`) — the
retirement years-and-months feature follows the same conceptual
"what fraction of this year remains" pattern at the closing year.
"""

import unittest

import pandas as pd

from simulation.years_and_months import (
    _split_years_into_years_and_months,
    _format_years_months_caption,
    _compute_years_months_delta,
    format_age_label,
    add_age_label_column,
    attach_age_columns,
    get_p1_current_age,
)
from simulation.engine import run_simulation
from models.person import Person
from models.household import Household


# -----------------------------------------------------------------------
# Shared fixtures — mirrors the helpers in
# `tests/test_partial_year_retirement.py` so each test stands alone
# without cross-file imports (the partial-year test file keeps its
# own; this one keeps its own; rotation is cheap because both files
# import the same dataclasses and just instantiate).
# -----------------------------------------------------------------------

def _make_person(name="P1", **overrides):
    """Build a Person with sensible defaults that allow the test to vary
    just the field under test. Mirrors the `Person(...)` constructor
    fields directly.
    """
    defaults = dict(
        name=name,
        age=55,
        retirement_age=60,
        state_pension_age=99,
        dc_pot=0.0,
        db_income=0.0,
        draw_age=99,
        monthly_contrib=0.0,
        income_until_retirement=0.0,
        income_growth_rate=0.0,
        monthly_contrib_pct=0.0,
        pcls_percent=0,
        dc_growth_rate=0.0,
        db_growth_rate=0.0,
        state_pension_growth_rate=0.0,
    )
    defaults.update(overrides)
    return Person(**defaults)


def _make_household(p1, p2=None, spending_target=0, years=10):
    """Build a Household with a SILENT second partner so the active
    partner's DC pot is the only contributor to `results["dc_pot"]`.
    The silent partner's `retirement_age=99` keeps them working for
    the whole horizon; their `dc_pot=0` + `dc_growth_rate=0` keeps
    the silent pot at zero throughout, so `p1.dc_pot + p2.dc_pot`
    == `p1.dc_pot` alone at every year.
    """
    if p2 is None:
        p2 = _make_person(
            name="Silent",
            retirement_age=99,
            income_until_retirement=0.0,
        )
    h = Household(
        person1=p1,
        person2=p2,
        assets=[],
        mortgage=None,
        spending_target=spending_target,
        events=[],
    )
    return h, years


# -----------------------------------------------------------------------
# Layer 1: helper round-trip math.
# -----------------------------------------------------------------------

class TestSplitRoundTripMath(unittest.TestCase):
    """`_split_years_into_years_and_months` round-trip math.

    The widget writes back as `years + months / 12.0`; this test class
    verifies that round-trip (split then reform) preserves the input
    for typical pension-relevant ages, and that the `months == 12`
    promotion corner case (FP round-up) bumps a full extra year so the
    form never displays a 12-month disallowed value.
    """

    def test_split_55_5_yields_55_years_6_months(self):
        """Half-year age is the headline use case for the months widget."""
        years, months = _split_years_into_years_and_months(55.5)
        self.assertEqual(years, 55)
        self.assertEqual(months, 6)

    def test_split_int_value_yields_zero_months(self):
        """Whole-year values decompose cleanly to (years, 0)."""
        years, months = _split_years_into_years_and_months(60)
        self.assertEqual(years, 60)
        self.assertEqual(months, 0)

    def test_round_trip_preserves_input_for_typical_ages(self):
        """The fundamental widget contract: split + reform = input."""
        for age in (55.0, 55.5, 60.0, 60.25, 67.5, 80.5):
            with self.subTest(age=age):
                years, months = _split_years_into_years_and_months(age)
                round_tripped = years + months / 12.0
                # Header loss may be sub-ULP due to FP rounding of
                # fractional months; `places=4` tolerates that.
                self.assertAlmostEqual(
                    round_tripped, age, places=4,
                    msg=f"Round-trip for {age} -> {round_tripped}",
                )

    def test_year_promotion_corner_case_prevents_12_month_value(self):
        """FP round-up edge case: 9.99999 rounds months to 12, which
        the helper MUST promote to a full extra year (10, 0) rather
        than display a disallowed 12-month value in the form.
        """
        years, months = _split_years_into_years_and_months(9.99999)
        self.assertEqual(years, 10)
        self.assertEqual(months, 0)

    def test_split_clamp_at_zero_for_negative_input(self):
        """Defensive `max(0.0, years_float)` clamp: a negative input
        silently maps to (0, 0) rather than misleading caption text.
        """
        years, months = _split_years_into_years_and_months(-3.5)
        self.assertEqual(years, 0)
        self.assertEqual(months, 0)


class TestCaptionFormatting(unittest.TestCase):
    """`_format_years_months_caption` English formatting + pluralisation."""

    def test_both_years_and_months_renders_naturally(self):
        self.assertEqual(
            _format_years_months_caption("retires", "", 60, 6, ""),
            "retires in 60 years and 6 months.",
        )

    def test_only_months_zero_years_renders_naturally(self):
        self.assertEqual(
            _format_years_months_caption("retires", "", 0, 6, ""),
            "retires in 6 months.",
        )

    def test_only_years_zero_months_renders_naturally(self):
        self.assertEqual(
            _format_years_months_caption("retires", "", 60, 0, ""),
            "retires in 60 years.",
        )

    def test_singular_year_no_plural_suffix(self):
        """Singular noun pluralisation: '1 year' (not '1 years')."""
        self.assertEqual(
            _format_years_months_caption("retires", "", 1, 0, ""),
            "retires in 1 year.",
        )

    def test_singular_month_no_plural_suffix(self):
        self.assertEqual(
            _format_years_months_caption("retires", "", 0, 1, ""),
            "retires in 1 month.",
        )


# -----------------------------------------------------------------------
# Layer 2: `Person(age=55.5, retirement_age=60.5)` driving the engine
# to a 5.0-year working arc.
# -----------------------------------------------------------------------

class TestPersonBothFractionalDrivesFiveZeroWorkingYears(unittest.TestCase):
    """Regression test: `Person(age=55.5, retirement_age=60.5)`.

    Both current_age and retirement_age are fractional; the engine
    computes `retirement_offset = retirement_age - age = 60.5 - 55.5 =
    5.0`. Combined with the `is_retired(year) = (age + year) >= retirement_age`
    boundary (a streamlit-style ASCII check), `is_retired(5) = (55.5 +
    5) >= 60.5 = True`, so year 5 is the first retired year — making
    years 0..4 the working years (5.0-year span).

    We verify two things:
      * the Person dataclass boundary math (years_to_retirement,
        is_retired at each year) — confirms the float type composes
        cleanly.
      * the end-to-end engine: 5 years of full compound + monthly
        contribution, followed by 1 year of pure compound at year 5's
        end (the first retired year). dc_pot at year 5 must match a
        closed-form accumulator.
    """

    def test_person_helper_boundary_math(self):
        """Person-side check: years_to_retirement is exactly 5.0
        (NOT 5.5 — that would be a wrong-direction rounding error).
        """
        p = _make_person(age=55.5, retirement_age=60.5)
        self.assertEqual(p.years_to_retirement(), 5.0)

        # Boundary checks at each year — `is_retired` drives engine
        # fractional-contribution wiring (engine step 2a/2b).
        # age=55.5, year=4 -> 59.5 < 60.5 = False (still working)
        # age=55.5, year=5 -> 60.5 >= 60.5 = True (boundary-year retired)
        self.assertFalse(p.is_retired(0))
        self.assertFalse(p.is_retired(4))
        # Boundary-day retired: at year=5 we're already at retirement_age.
        self.assertTrue(p.is_retired(5))
        self.assertTrue(p.is_retired(6))

    def test_engine_produces_closed_form_dc_pot_trajectory(self):
        """End-to-end engine: dc_pot at year 5 = (5 years of full
        working compound + M) THEN (1 year of pure compound, M=0).
        Lock this against a closed-form `0.05 / 12` monthly
        accumulator so a future engine refactor can't silently drift
        the trajectory by an incorrect number of working years.
        """
        p1 = _make_person(
            age=55.5,
            retirement_age=60.5,
            dc_pot=10_000.0,
            dc_growth_rate=0.05,
            income_until_retirement=60_000.0,
            income_growth_rate=0.0,   # flat income for clean math
            monthly_contrib_pct=0.15,
        )
        h, years = _make_household(p1, years=10)
        r = run_simulation(h, years=years)

        # Closed-form expected:
        # * Years 0..4: 5 years of "12-month compound + annuity"
        # * Year 5: pure 12-month compound (M=0, post-retirement)
        M = 60_000.0 * 0.15 / 12
        r_m = 0.05 / 12
        growth_12 = (1 + r_m) ** 12
        annuity_12 = M * (growth_12 - 1) / r_m

        pot = 10_000.0
        for _ in range(5):
            pot = pot * growth_12 + annuity_12
        pot_at_year_5 = pot * growth_12  # pure compound (M=0)

        with self.subTest(year=5):
            self.assertAlmostEqual(
                r["dc_pot"][5], pot_at_year_5, places=4,
                msg=(
                    f"Y5 both-fractional closed-form drift: "
                    f"engine={r['dc_pot'][5]:.4f} vs "
                    f"closed-form={pot_at_year_5:.4f}"
                ),
            )

        # Sanity gates on the year-by-year trajectory. Year 5 must
        # be STRICTLY between the working-year pot (full compound + M)
        # and the all-retired pot (pure compound). If the engine
        # wrongly classifies year 5 as working, the pot would be
        # higher (added annuity). If wrongly classified it as M=0
        # earlier (e.g. treating 5.0 offset as already < 5), the pot
        # would be lower. This pins the boundary explicitly.
        pot_after_5_working = pot_at_year_5 / growth_12 + annuity_12  # M added one more year
        pot_after_2_retired = pot_at_year_5 * growth_12 ** 2  # Y7 = Y5 compounded by 2 retired years of pure growth (NOT `* growth_12` which would only be one year past Y5 = Y6)
        # year 5 pot must be less than "one more working year would have produced":
        self.assertLess(
            r["dc_pot"][5], pot_after_5_working,
            msg=(
                f"Y5 pot ({r['dc_pot'][5]:.4f}) must be strictly less than the "
                f"would-be-working baseline ({pot_after_5_working:.4f}) — otherwise "
                f"the engine treated year 5 as a working year."
            ),
        )
        # year 7 pot (= year 5 pot * growth_12 + M=0) — pure compound;
        # verify year 7 matches the closed form (this is the year 5
        # pot compounded by 24 months of pure growth).
        self.assertAlmostEqual(
            r["dc_pot"][7], pot_after_2_retired, places=4,
            msg=(
                f"Y7 both-fractional drift: "
                f"engine={r['dc_pot'][7]:.4f} vs "
                f"closed-form={pot_after_2_retired:.4f}"
            ),
        )


# -----------------------------------------------------------------------
# Layer 1.5: `_compute_years_months_delta` — the time-to-retirement
# helper used by `pages/2_Pensions.py`'s caption. Without this, the
# caption used to render the literal retirement-age input ("Retires
# in 60 years and 8 months.") instead of the time-until-retirement
# delta ("Retires in 4 years and 10 months."). This regression bites
# whenever the user's current_age is nonzero.
# -----------------------------------------------------------------------

class TestComputeYearsMonthsDelta(unittest.TestCase):
    """`_compute_years_months_delta(target_years, target_months,
    current_age_float) -> (delta_years, delta_months, is_past_or_now)`.

    Lock the math for the user's reported case (current 55y 10m →
    retirement 60y 8m = 4y 10m remaining) and several boundary
    scenarios. Also asserts the FP-drift guard: the helper avoids
    the `int(age * 12)` shortcut that would lose a month for
    `(55 + 10/12) * 12 = 669.9999…` in IEEE-754.
    """

    def test_user_reported_case_current_55y10m_to_retire_60y8m(self):
        """The exact case from the bug report.

        current_age = 55 years + 10 months (the form-returned float
        `55 + 10/12 = 55.8333…` in IEEE-754); retirement = 60y 8m;
        expected = 4 years + 10 months remaining.

        Note: `(55 + 10/12) * 12` evaluates to `669.99999…` in float,
        so a naive `int(age * 12)` shortcut would silently off-by-one
        to 4y 9m. The helper sidesteps this by routing through
        `_split_years_into_years_and_months` first.
        """
        delta_years, delta_months, is_past = _compute_years_months_delta(
            target_years=60,
            target_months=8,
            current_age_float=55 + 10 / 12,  # exact shape of widget return
        )
        self.assertFalse(is_past)
        self.assertEqual(delta_years, 4)
        self.assertEqual(delta_months, 10)

    def test_whole_year_ages_int_saved_json(self):
        """Legacy-int saved JSON: age=55, retirement=60 → 5y 0m.

        Also a regression for `_split_years_into_years_and_months`
        being driven by an int — Python coerces to float at the
        dataclass boundary so the helper sees `55.0` cleanly.
        """
        delta_y, delta_m, is_past = _compute_years_months_delta(
            target_years=60, target_months=0, current_age_float=55.0,
        )
        self.assertEqual((delta_y, delta_m, is_past), (5, 0, False))

    def test_exact_boundary_target_equals_age_returns_past(self):
        """When ret == current age exactly, delta is 0 and the
        helper flags `is_past_or_now=True` so the caller renders the
        'already retired today' empty-message instead of
        'retires in 0 years and 0 months.'.
        """
        delta_y, delta_m, is_past = _compute_years_months_delta(
            target_years=60, target_months=0, current_age_float=60.0,
        )
        self.assertEqual((delta_y, delta_m), (0, 0))
        self.assertTrue(is_past)

    def test_target_behind_current_age_returns_past(self):
        """Retirement age strictly less than current age → already
        retired. The caption should NOT say 'retires in -5 years.'
        """
        delta_y, delta_m, is_past = _compute_years_months_delta(
            target_years=60, target_months=0, current_age_float=65.0,
        )
        self.assertEqual((delta_y, delta_m), (0, 0))
        self.assertTrue(is_past)

    def test_target_ahead_by_less_than_a_year_renders_months_only(self):
        """ret=60y 8m, age=60y 0m → 8 months remaining."""
        delta_y, delta_m, is_past = _compute_years_months_delta(
            target_years=60, target_months=8, current_age_float=60.0,
        )
        self.assertEqual((delta_y, delta_m, is_past), (0, 8, False))

    def test_target_ahead_by_exactly_twelve_months_renders_one_year(self):
        """ret=61y 0m, age=60y 0m → exactly 1 year (12 months).

        Without the integer-math path, `(12) % 12 = 0` and
        `(12) // 12 = 1` cleanly — but flag the round-trip pin here so
        a future refactor can't silently produce '0 years and 12 months.'
        instead of '1 year.'.
        """
        delta_y, delta_m, is_past = _compute_years_months_delta(
            target_years=61, target_months=0, current_age_float=60.0,
        )
        self.assertEqual((delta_y, delta_m, is_past), (1, 0, False))

    def test_fractional_current_age_no_fp_drift(self):
        """FP-drift guard: verify `current_age_float = 55 + 10/12`
        round-trips through `_split_years_into_years_and_months` to
        `(55, 10)` (NOT `(54, 11)`, which a naive `int(age * 12)`
        would yield given the IEEE-754 representation of `10/12`).
        """
        years_i, months_i = _split_years_into_years_and_months(55 + 10 / 12)
        self.assertEqual((years_i, months_i), (55, 10))


# -----------------------------------------------------------------------
# Layer 1.6: `format_age_label(age_float) -> str` — compact "Xy Ym"
# formatter used by chart titles and Altair x-axis tick labels.
# -----------------------------------------------------------------------

class TestFormatAgeLabel(unittest.TestCase):
    """`format_age_label` returns compact age text for chart layer.

    The helper replaces the legacy `f"{age:g}"` formatter which
    truncated fractional ages to 4-6 sig figs ("Age 55.8333 →
    99.8333"). It must:
      * render whole-year ages as "Xy" (no months suffix)
      * render fractional ages as "Xy Ym" (single space, no plural "s")
      * handle 0 months cleanly (no "0m" cosmetic)
      * handle FP-rounding promotion corner case (e.g. 9.9999)
    """

    def test_whole_year_age_renders_without_month_suffix(self):
        self.assertEqual(format_age_label(55.0), "55y")
        self.assertEqual(format_age_label(60.0), "60y")
        # Legacy int-saved JSON path: int still renders cleanly.
        self.assertEqual(format_age_label(55), "55y")

    def test_half_year_age_renders_six_months(self):
        self.assertEqual(format_age_label(55.5), "55y 6m")

    def test_user_reported_case_55y_10m(self):
        """The headline use case from the bug report — the user
        saved age=55y 10m which round-trips to `55 + 10/12` in
        IEEE-754 (represented as exactly `55.833333333333336`).
        The label must show "10m" (10/12 → 10 months by round(.5=10))
        — NOT "9m" or "11m" from naive float math.
        """
        # The exact shape Page 2's `years_and_months_input` returns.
        self.assertEqual(format_age_label(55 + 10 / 12), "55y 10m")
        # And the IEEE-754 display form the user sees in the title.
        self.assertEqual(format_age_label(55.833333333333336), "55y 10m")
        # 4-sig-figs truncation (the legacy `:g` output):
        self.assertEqual(format_age_label(55.8333), "55y 10m")

    def test_quarter_year_renders_three_months(self):
        self.assertEqual(format_age_label(60.25), "60y 3m")

    def test_three_quarters_renders_nine_months(self):
        self.assertEqual(format_age_label(67.75), "67y 9m")

    def test_fp_round_up_corner_case_promotes_to_next_year(self):
        """9.9999 → months=12 → promoted to (10, 0) by
        `_split_years_into_years_and_months`. `format_age_label`
        must NOT render "9y 12m" (a disallowed value).
        """
        self.assertEqual(format_age_label(9.9999), "10y")
        self.assertEqual(format_age_label(9.99999), "10y")

    def test_singular_year_no_plural_suffix(self):
        """Single year: "1y" (not "1ys")."""
        self.assertEqual(format_age_label(1.0), "1y")
        self.assertEqual(format_age_label(1.5), "1y 6m")

    def test_zero_age_renders_zero_years(self):
        """Defensive: zero-age case should not crash."""
        self.assertEqual(format_age_label(0.0), "0y")


class TestAddAgeLabelColumn(unittest.TestCase):
    """`add_age_label_column` adds a string `AgeLabel` column.

    Used by the Altair chart pages so tick labels render "55y 10m"
    rather than the float's decimal expansion. The original `Age`
    column is preserved unchanged so the tooltip can still display
    numeric ages (and downstream `.iloc[…, Age]` indexers still work).
    """

    def test_adds_label_column_preserves_age(self):
        df = pd.DataFrame({"Age": [55.0, 55.5, 55 + 10 / 12, 60.0]})
        out = add_age_label_column(df)
        # Original column unchanged in both values AND type.
        self.assertEqual(list(out["Age"]), [55.0, 55.5, 55 + 10 / 12, 60.0])
        self.assertEqual(
            list(out["AgeLabel"]),
            ["55y", "55y 6m", "55y 10m", "60y"],
        )

    def test_does_not_mutate_input_frame(self):
        df = pd.DataFrame({"Age": [55.5, 60.0]})
        out = add_age_label_column(df)
        # Caller-owned frame must not gain the derived column.
        self.assertNotIn("AgeLabel", df.columns)
        self.assertIn("AgeLabel", out.columns)

    def test_accepts_custom_age_and_label_column_names(self):
        df = pd.DataFrame({"p1_age": [55.5, 60.25]})
        out = add_age_label_column(
            df, age_column="p1_age", label_column="p1_age_label",
        )
        self.assertEqual(list(out["p1_age_label"]), ["55y 6m", "60y 3m"])


# -----------------------------------------------------------------------
# Layer 1.7: `get_p1_current_age(household_data)` — centralised
# age-derivation helper that replaced the duplicated `try: float(...);
# except: 55` block on pages 6 / 10 / 11 / 12 / 13.
# -----------------------------------------------------------------------

class TestGetP1CurrentAge(unittest.TestCase):
    """`get_p1_current_age(household_data, default=55.0) -> float`.

    Centralises the age-derivation pattern that used to live inline on
    pages 6 / 10 / 11 / 12 / 13:
      `try: float(household_data["person1"]["age"]) except (...): 55`

    Replaces it with a single helper call that:
      * returns `float(household_data["person1"]["age"])` on the happy
        path (legacy int JSONs coerce cleanly to float via Python's
        auto-promotion at the `float(...)` boundary);
      * returns `default` (55.0) on any failure mode —
        `KeyError` / `TypeError` / `ValueError` / None / negative age.
    """

    def test_happy_path_fractional_age_returned_unchanged(self):
        """Headline use case — 55y10m saved-plan should round-trip
        as the same float (without losing the half-year precision).
        """
        result = get_p1_current_age({"person1": {"age": 55 + 10 / 12}})
        self.assertEqual(result, 55 + 10 / 12)

    def test_happy_path_legacy_int_saved_json_coerces_to_float(self):
        """BC anchor — a legacy int-saved JSON (`age=55`) composes
        cleanly through the float pipeline. The return-type is `float`
        because downstream arithmetic (`p1_current_age +
        len(results["years"]) - 1`) treats it as a float partition.
        """
        result = get_p1_current_age({"person1": {"age": 55}})
        self.assertIsInstance(result, float)
        self.assertEqual(result, 55.0)

    def test_happy_path_whole_year_float(self):
        self.assertEqual(get_p1_current_age({"person1": {"age": 60.0}}), 60.0)

    def test_none_household_returns_default(self):
        """Defensive: a page that ran before `init_household` could
        pass `None`. Must not raise.
        """
        self.assertEqual(get_p1_current_age(None), 55.0)

    def test_empty_dict_returns_default(self):
        """Reset-Plan path: `household_data = {}`. Must not raise
        `KeyError("person1")` — the page should keep rendering the
        age-axis at 55 instead of crashing.
        """
        self.assertEqual(get_p1_current_age({}), 55.0)

    def test_missing_person1_returns_default(self):
        self.assertEqual(get_p1_current_age({"other": "key"}), 55.0)

    def test_missing_age_returns_default(self):
        self.assertEqual(get_p1_current_age({"person1": {"other": "key"}}), 55.0)

    def test_non_numeric_age_returns_default(self):
        """`age=null` or `age="not-a-number"` in a saved JSON should
        fall back to the default rather than raising `ValueError`.
        """
        self.assertEqual(get_p1_current_age({"person1": {"age": None}}), 55.0)
        self.assertEqual(
            get_p1_current_age({"person1": {"age": "fifty-five"}}), 55.0,
        )

    def test_non_dict_inner_returns_default(self):
        """Malformed JSON: `person1` is a string OR a None. Guarded
        against a future refactor that accidentally replaces the inner
        dict. `TypeError` is caught.
        """
        self.assertEqual(get_p1_current_age({"person1": "Dave"}), 55.0)
        self.assertEqual(get_p1_current_age({"person1": None}), 55.0)

    def test_negative_age_clamped_to_default(self):
        """Defensive `age >= 0.0` clamp: a manual JSON edit that sets
        `age=-1` would otherwise render a misleading "Age -1 → ..."
        axis label. Map negative ages to the default for safety.
        """
        self.assertEqual(get_p1_current_age({"person1": {"age": -1.0}}), 55.0)

    def test_zero_age_passes_through(self):
        """`age = 0.0` is not negative, so the clamp allows it. A
        newborn-age household is unusual but valid (early-savings
        modelling). The helper should NOT silently swap zero for
        55 — that would be a hidden data-mutation.
        """
        self.assertEqual(get_p1_current_age({"person1": {"age": 0.0}}), 0.0)

    def test_custom_default_honored(self):
        """The kwarg `default=...` lets a future caller supply a
        different fallback (e.g. a different anchor age for a
        multi-partner view). Must not be silently coerced to 55.
        """
        self.assertEqual(
            get_p1_current_age(None, default=42.0), 42.0,
        )
        self.assertEqual(
            get_p1_current_age({}, default=42.0), 42.0,
        )


# -----------------------------------------------------------------------
# Layer 3: legacy int-saved-JSON regression — the BC anchor.
# -----------------------------------------------------------------------

class TestLegacyIntSavedJsonStillProducesFiveWorkingYears(unittest.TestCase):
    """Regression test for legacy int-saved JSON.

    A household saved BEFORE the months-precision feature landed
    carried whole-year ints (`age=55, retirement_age=60`). Python
    coerces both ints to floats at the Person dataclass boundary;
    the engine is duck-typed so the resulting `dc_pot` trajectory
    must match the closed-form 5-year-working + 5-year-pure-compound
    accumulator — byte-identical to the pre-feature behaviour.

    Without this regression, a downstream page that reads an int
    saved JSON via the float pipeline could silently drift by one
    or more years of contributions / growth.
    """

    def test_int_age_int_retirement_age_produces_five_working_years(self):
        """Even though `Person.age`/`retirement_age` are typed `float`
        now, an int saved JSON (`age=55, retirement_age=60`) still
        composes cleanly. Lock the resulting dc_pot against the
        closed-form 5-year-working accumulator.

        Identical math to the both-fractional test above — the
        engine path is duck-typed float for either input — so this
        regression asserts that an int saved JSON does NOT silently
        drift the trajectory.
        """
        p1 = _make_person(
            age=55,            # int — legacy saved JSON shape
            retirement_age=60, # int — legacy saved JSON shape
            dc_pot=10_000.0,
            dc_growth_rate=0.05,
            income_until_retirement=60_000.0,
            income_growth_rate=0.0,
            monthly_contrib_pct=0.15,
        )
        h, years = _make_household(p1, years=10)
        r = run_simulation(h, years=years)

        M = 60_000.0 * 0.15 / 12
        r_m = 0.05 / 12
        growth_12 = (1 + r_m) ** 12
        annuity_12 = M * (growth_12 - 1) / r_m

        pot = 10_000.0
        for _ in range(5):
            pot = pot * growth_12 + annuity_12
        pot_at_year_5 = pot * growth_12  # year 5 pure compound

        with self.subTest(year=5):
            self.assertAlmostEqual(
                r["dc_pot"][5], pot_at_year_5, places=4,
                msg=(
                    f"Y5 int-saved-JSON closed-form drift: "
                    f"engine={r['dc_pot'][5]:.4f} vs "
                    f"closed-form={pot_at_year_5:.4f}"
                ),
            )

    def test_int_saved_json_offset_is_exactly_five(self):
        """`Person.years_to_retirement()` on an int-saved JSON must
        return the float `5.0`, NOT an int `5` — every caller that
        treats it as a float partition (`retirement_offset - year`)
        depends on the float type to keep type-consistency with
        `retirement_age`. A return-type regression here would
        silently truncate half-year boundaries in the engine.
        """
        p = _make_person(age=55, retirement_age=60)
        years_to = p.years_to_retirement()
        self.assertIsInstance(years_to, float)
        self.assertEqual(years_to, 5.0)

        # Boundary: at year=5, is_retired is True (60 >= 60 = True).
        # at year=4, is_retired is False (59 >= 60 = False).
        self.assertFalse(p.is_retired(4))
        self.assertTrue(p.is_retired(5))


class TestAttachAgeColumns(unittest.TestCase):
    """`attach_age_columns(frame, p1_current_age)` derives both
    `Age` (float) and `AgeLabel` (string compact `"Xy Ym"`) columns from
    a Year-bearing frame in a single call. Locks in the contract
    pages 1 and 11 depend on so the consolidated helper stays
    byte-equivalent to the two prior inline helpers it replaced."""

    def test_year_only_input_produces_age_and_label(self):
        df = pd.DataFrame({"Year": [0, 1, 5]})
        out = attach_age_columns(df, 55.0)
        # Age is float (`Year + p1_current_age`), AgeLabel is string.
        self.assertEqual(list(out["Age"]), [55.0, 56.0, 60.0])
        self.assertEqual(
            list(out["AgeLabel"]),
            ["55y", "56y", "60y"],
        )
        # Year column is preserved (callers may still want raw offsets).
        self.assertEqual(list(out["Year"]), [0, 1, 5])

    def test_fractional_current_age_produces_months_in_label(self):
        """Months-precision current_age (Page 2's years_and_months_input)
        must round-trip into a fractional Age AND the "/[months]m"
        suffix in AgeLabel — failing this test would mean the
        consolidated helper silently drops fractional ages back to
        whole years."""
        df = pd.DataFrame({"Year": [0, 5]})
        out = attach_age_columns(df, 55 + 10 / 12)
        self.assertEqual(list(out["Age"]), [55 + 10 / 12, 60 + 10 / 12])
        self.assertEqual(
            list(out["AgeLabel"]),
            ["55y 10m", "60y 10m"],
        )

    def test_legacy_int_year_round_trips(self):
        """Defensive: a Year column stored as Python `int` (legacy
        pre-float house style) round-trips into a float Age and a
        clean `"Xy"` (no-month) label — passing int-only data MUST
        NOT raise."""
        df = pd.DataFrame({"Year": [0, 5, 20]})  # int Year column
        out = attach_age_columns(df, 55)
        self.assertEqual(list(out["Age"].tolist()), [55.0, 60.0, 75.0])
        self.assertEqual(
            list(out["AgeLabel"]),
            ["55y", "60y", "75y"],
        )

    def test_does_not_mutate_input_frame(self):
        """Returning a fresh copy is a fundamental contract — chart
        pages mutate `df_age.copy()` downstream (column-drop, value-
        clamp) and assume the input frame stays clean. A regression
        that returned `frame` itself would surface later as
        mysterious duplicate-state bugs."""
        before = pd.DataFrame({"Year": [0, 5]})
        # Snapshot the column count BEFORE the call so a leaky impl
        # that mutates in place fails this assert.
        before_columns = set(before.columns)
        _ = attach_age_columns(before, 55.0)
        self.assertEqual(set(before.columns), before_columns)

    def test_returned_frame_has_both_columns(self):
        """The whole point of consolidating the two prior helpers is
        that the unified one ALWAYS produces both columns (callers
        that only need one are not penalized with a flag, see the
        helper docstring)."""
        df = pd.DataFrame({"Year": [0]})
        out = attach_age_columns(df, 55.0)
        self.assertIn("Age", out.columns)
        self.assertIn("AgeLabel", out.columns)

    def test_missing_year_column_raises_keyerror(self):
        """Defensive: a caller who has only `Age` (not `Year`) on their
        frame is using the wrong helper — should call
        `add_age_label_column` instead. Native `KeyError` surfaces
        the misuse at render time rather than silently producing
        blank tick labels."""
        df = pd.DataFrame({"Age": [55.0, 60.0]})
        with self.assertRaises(KeyError):
            attach_age_columns(df, 55.0)

    def test_custom_year_column_name_respected(self):
        """Some hypothetical caller has `SimulationYear` instead of
        `Year`. The `year_column=` kwarg lets them steer the helper
        without renaming their source column."""
        df = pd.DataFrame({"SimulationYear": [0, 5]})
        out = attach_age_columns(df, 55.0, year_column="SimulationYear")
        self.assertEqual(list(out["Age"]), [55.0, 60.0])
        self.assertEqual(list(out["AgeLabel"]), ["55y", "60y"])
        # Source column is preserved.
        self.assertEqual(list(out["SimulationYear"]), [0, 5])

    def test_default_year_column_is_year(self):
        """When `year_column=` is omitted, the helper must default to
        `"Year"` — locks in the wire-protocol that pages 1, 10, 11, 12
        already depend on (their result-frame helpers all name the
        column `Year`)."""
        df_only_year = pd.DataFrame({"Year": [0, 5]})
        out = attach_age_columns(df_only_year, 55.0)
        self.assertIn("Age", out.columns)
        self.assertEqual(list(out["Age"]), [55.0, 60.0])


if __name__ == "__main__":
    unittest.main()
