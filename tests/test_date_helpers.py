"""Unit tests for the date-of-birth computation helpers.

Covers `_compute_age_from_dob` and `_years_from_dates` from
`simulation/years_and_months.py`. These helpers replaced the old
"Current age" years+months widget with DOB date pickers on the
Pensions page and Quick Estimate page.

Tests exercise:
  * Basic age computation from a known DOB
  * `as_of` reference-date override
  * Today-as-default path
  * Feb 29 birthday (leap-year born) on a non-leap-year reference
  * Future DOB → floor at 18.0
  * Birthday exactly on the reference date → age just past integer
  * Negative delta for `_years_from_dates` → floor at 0.0
  * Exact-year and fractional-year spans
"""

import unittest
from datetime import date

from simulation.years_and_months import (
    _compute_age_from_dob,
    _years_from_dates,
)

# Fractional-age tolerance: 365.25-day years mean a 55-year span
# can differ from exact calendar years by ~0.5 days. We assert
# to 1 decimal place for human-sensible assertions.
_AGE_TOLERANCE = 0.1  # ~36.5 days — generous but fair for 365.25 math


# -----------------------------------------------------------------------
# _compute_age_from_dob
# -----------------------------------------------------------------------

class TestComputeAgeFromDob(unittest.TestCase):
    """`_compute_age_from_dob(dob_str, as_of=None) -> float`."""

    # -- Basic computation with known reference date -------------------

    def test_age_55_years(self):
        """DOB 1970-01-01, as_of 2025-07-01 = 55 years + ~181 days."""
        age = _compute_age_from_dob(
            "1970-01-01", as_of=date(2025, 7, 1),
        )
        self.assertAlmostEqual(age, 55.5, delta=_AGE_TOLERANCE)

    def test_age_exactly_integer_years(self):
        """DOB 1970-07-01, as_of 2025-07-01 = exactly 55 years."""
        age = _compute_age_from_dob(
            "1970-07-01", as_of=date(2025, 7, 1),
        )
        self.assertAlmostEqual(age, 55.0, delta=_AGE_TOLERANCE)

    def test_age_one_day_old(self):
        """DOB = as_of - 1 day = ~0.0027 years."""
        age = _compute_age_from_dob(
            "2025-06-30", as_of=date(2025, 7, 1),
        )
        self.assertGreater(age, 0.0)
        self.assertLess(age, 0.01)

    # -- Default as_of (today) -----------------------------------------

    def test_default_as_of_is_today(self):
        """Passing dob_str only uses date.today() as reference.

        Can't pin an exact value because the test runs on any date,
        but we CAN assert the result is positive, finite, and
        consistent with a reasonable human age for a recent-ish DOB.
        """
        # Pick a DOB known to be in the past: Jan 1, 2000.
        age = _compute_age_from_dob("2000-01-01")
        self.assertGreater(age, 0.0)
        self.assertLess(age, 150.0)  # sanity cap

    # -- Feb 29 (leap-year birthday) -----------------------------------

    def test_feb29_birthday_in_leap_year(self):
        """Born Feb 29 1976 (leap year), as_of Feb 29 2020 (leap year).

        `date.fromisoformat` parses "1976-02-29" cleanly. The age
        should be exactly 44 years.
        """
        age = _compute_age_from_dob(
            "1976-02-29", as_of=date(2020, 2, 29),
        )
        self.assertAlmostEqual(age, 44.0, delta=_AGE_TOLERANCE)

    def test_feb29_birthday_in_non_leap_year(self):
        """Born Feb 29 1976, as_of Feb 28 2021 (day before would-be 45th).

        The reference date is NOT a leap year, so the birthday
        hasn't occurred yet in 2021 — the age should be just under
        45 by a few days. The helper uses `(ref - dob).days / 365.25`
        which handles this naturally since both dates are valid.
        """
        age = _compute_age_from_dob(
            "1976-02-29", as_of=date(2021, 2, 28),
        )
        self.assertAlmostEqual(age, 45.0, delta=_AGE_TOLERANCE)

    def test_feb29_birthday_day_after_in_leap_year(self):
        """Born Feb 29 1976, as_of Mar 1 2020 (day after 44th birthday).

        Should be fractionally past 44.0.
        """
        age = _compute_age_from_dob(
            "1976-02-29", as_of=date(2020, 3, 1),
        )
        self.assertGreater(age, 44.0)
        self.assertLess(age, 44.01)

    # -- Future DOB → floor at 18 --------------------------------------

    def test_future_dob_floors_at_18(self):
        """A user fat-fingering a future DOB (e.g. "2070") must
        NOT produce a negative age. The helper floors at 18.0.
        """
        age = _compute_age_from_dob(
            "2070-01-01", as_of=date(2025, 7, 1),
        )
        self.assertEqual(age, 18.0)

    def test_dob_is_today_floors_at_18(self):
        """DOB exactly equal to as_of (age 0 days) → floor at 18.

        A newborn can't really plan retirement, but a user
        entering today's date accidentally shouldn't crash.
        """
        age = _compute_age_from_dob(
            "2025-07-01", as_of=date(2025, 7, 1),
        )
        self.assertEqual(age, 18.0)

    # -- Centenarian ---------------------------------------------------

    def test_centenarian(self):
        """100-year span still computes cleanly."""
        age = _compute_age_from_dob(
            "1925-01-01", as_of=date(2025, 1, 1),
        )
        self.assertAlmostEqual(age, 100.0, delta=_AGE_TOLERANCE)

    # -- Common real-world DOB shapes ----------------------------------

    def test_realistic_dob_55_year_old(self):
        """A current 55-year-old (born mid-1970, as_of mid-2026)."""
        age = _compute_age_from_dob(
            "1970-09-15", as_of=date(2026, 7, 15),
        )
        # Should be just under 56 (birthday hasn't happened yet this year).
        self.assertGreater(age, 55.0)
        self.assertLess(age, 56.0)

    def test_birthday_just_passed(self):
        """Born July 10 1970, as_of July 15 2026 — birthday just passed
        by 5 days. Age should be 56 + ~5/365.25 ≈ 56.014."""
        age = _compute_age_from_dob(
            "1970-07-10", as_of=date(2026, 7, 15),
        )
        self.assertGreater(age, 56.0)
        self.assertLess(age, 56.02)

    # -- Malformed input ------------------------------------------------

    def test_raises_on_non_iso_date_string(self):
        """Garbage input should raise ValueError from date.fromisoformat.

        The caller (UI page) is responsible for passing a valid ISO
        string. The helper should let the exception propagate rather
        than silently returning a fake age.
        """
        with self.assertRaises(ValueError):
            _compute_age_from_dob("not-a-date")


# -----------------------------------------------------------------------
# _years_from_dates
# -----------------------------------------------------------------------

class TestYearsFromDates(unittest.TestCase):
    """`_years_from_dates(start_str, end_str) -> float`."""

    # -- Exact year spans ----------------------------------------------

    def test_5_year_span(self):
        # 365*5 / 365.25 = 1825 / 365.25 ≈ 4.997 (short of 5.0 by ~1.25 days).
        # The 365.25 divisor averages out over spans that include leap years.
        self.assertAlmostEqual(
            _years_from_dates("2025-01-01", "2030-01-01"),
            5.0, delta=0.01,
        )

    def test_1_year_span(self):
        # 365 / 365.25 ≈ 0.9993 — 365.25 averages over leap-year spans.
        self.assertAlmostEqual(
            _years_from_dates("2025-01-01", "2026-01-01"),
            1.0, delta=0.01,
        )

    def test_10_year_span(self):
        self.assertAlmostEqual(
            _years_from_dates("2020-01-01", "2030-01-01"),
            10.0,
            delta=_AGE_TOLERANCE,
        )

    # -- Fractional-year spans -----------------------------------------

    def test_half_year_span(self):
        """~182.625 days → ~0.5 years."""
        years = _years_from_dates("2025-01-01", "2025-07-02")
        self.assertAlmostEqual(years, 0.5, delta=0.01)

    def test_quarter_year_span(self):
        """~91.3 days → ~0.25 years."""
        years = _years_from_dates("2025-01-01", "2025-04-02")
        self.assertAlmostEqual(years, 0.25, delta=0.01)

    def test_one_day_span(self):
        """Minimal positive delta — just under 0.003 years."""
        years = _years_from_dates("2025-01-01", "2025-01-02")
        self.assertGreater(years, 0.0)
        self.assertLess(years, 0.003)

    # -- Edge cases: zero and negative deltas --------------------------

    def test_same_date_returns_zero(self):
        self.assertEqual(
            _years_from_dates("2025-07-01", "2025-07-01"),
            0.0,
        )

    def test_end_before_start_returns_zero(self):
        """Defensive: a retirement date in the past means 'already
        retired' — the helper returns 0.0 rather than negative.
        """
        self.assertEqual(
            _years_from_dates("2030-01-01", "2025-01-01"),
            0.0,
        )

    def test_end_one_day_before_start_returns_zero(self):
        """Just-barely-negative delta is still floored to 0."""
        self.assertEqual(
            _years_from_dates("2025-01-02", "2025-01-01"),
            0.0,
        )

    # -- Leap year spans -----------------------------------------------

    def test_span_across_leap_year(self):
        """2023-01-01 → 2025-01-01 spans 2024 (leap year) = 731 days."""
        years = _years_from_dates("2023-01-01", "2025-01-01")
        # 731 / 365.25 ≈ 2.001
        self.assertAlmostEqual(years, 2.0, delta=0.01)

    def test_span_across_multiple_leap_years(self):
        """2019-01-01 → 2025-01-01 spans 2020 and 2024 (2 leap years)
        = 2192 days → 2192 / 365.25 ≈ 6.001.
        """
        years = _years_from_dates("2019-01-01", "2025-01-01")
        self.assertAlmostEqual(years, 6.0, delta=0.01)

    # -- Large spans ---------------------------------------------------

    def test_century_span(self):
        """100-year span from 1900-01-01 to 2000-01-01.

        This spans 1900 (NOT a leap year — century rule) through
        1999. Actual = 36524 days / 365.25 ≈ 99.99. The 365.25
        approximation gives 100.0 exactly for this specific pair
        because 1900 wasn't a leap year (divisible by 100 but not
        400) → 36524 days total. 36524 / 365.25 = 99.993...
        """
        years = _years_from_dates("1900-01-01", "2000-01-01")
        self.assertAlmostEqual(years, 100.0, delta=0.02)

    # -- Typical retirement-planning spans -----------------------------

    def test_5_years_to_retirement(self):
        """Today → 5 years from now is the typical working horizon."""
        today = date.today()
        target = today.replace(year=today.year + 5)
        years = _years_from_dates(today.isoformat(), target.isoformat())
        self.assertAlmostEqual(years, 5.0, delta=_AGE_TOLERANCE)

    def test_15_years_to_retirement(self):
        """Long working horizon."""
        today = date.today()
        target = today.replace(year=today.year + 15)
        years = _years_from_dates(today.isoformat(), target.isoformat())
        self.assertAlmostEqual(years, 15.0, delta=_AGE_TOLERANCE)

    # -- Malformed input ------------------------------------------------

    def test_raises_on_non_iso_start_string(self):
        with self.assertRaises(ValueError):
            _years_from_dates("not-a-date", "2030-01-01")

    def test_raises_on_non_iso_end_string(self):
        with self.assertRaises(ValueError):
            _years_from_dates("2025-01-01", "not-a-date")


# -----------------------------------------------------------------------
# Cross-helper integration: compute age then years-to-retirement
# as the pages do (age = _compute_age_from_dob, then
# retirement_age = age + _years_from_dates(today, retirement_date)).
# -----------------------------------------------------------------------

class TestEndToEndAgeAndRetirement(unittest.TestCase):
    """Integration test mirroring the page-level math."""

    def test_full_pipeline_age_then_retirement_age(self):
        """DOB 1970-06-15, today 2026-07-28, retires 2030-06-15.

        Age today = ~56.12. Years to retirement = ~3.88.
        retirement_age = 56.12 + 3.88 ≈ 60.0.
        """
        today = date(2026, 7, 28)
        dob = "1970-06-15"
        ret_date = "2030-06-15"

        age = _compute_age_from_dob(dob, as_of=today)
        years_to_ret = _years_from_dates(today.isoformat(), ret_date)
        retirement_age = age + years_to_ret

        # Should be approximately 60 (exact: 60 years from DOB to ret_date,
        # but today sits in the middle, so age + years_to_ret must = 60).
        self.assertAlmostEqual(retirement_age, 60.0, delta=_AGE_TOLERANCE)

    def test_retirement_date_is_today(self):
        """DOB 1970-01-01, today 2030-01-01, retires TODAY.

        Age = 60. years_to_ret = 0 (same date). retirement_age = 60.
        """
        today = date(2030, 1, 1)
        dob = "1970-01-01"
        ret_date = "2030-01-01"

        age = _compute_age_from_dob(dob, as_of=today)
        years_to_ret = _years_from_dates(today.isoformat(), ret_date)
        retirement_age = age + years_to_ret

        self.assertAlmostEqual(age, 60.0, delta=_AGE_TOLERANCE)
        self.assertEqual(years_to_ret, 0.0)
        self.assertAlmostEqual(retirement_age, 60.0, delta=_AGE_TOLERANCE)

    def test_already_retired_retirement_date_in_past(self):
        """DOB 1960-01-01, today 2026-01-01, 'retired' 2020-01-01.

        Age = 66. years_to_ret = 0 (past → floor). retirement_age = 66.
        """
        today = date(2026, 1, 1)
        dob = "1960-01-01"
        ret_date = "2020-01-01"  # in the past

        age = _compute_age_from_dob(dob, as_of=today)
        years_to_ret = _years_from_dates(today.isoformat(), ret_date)
        retirement_age = age + years_to_ret

        self.assertEqual(years_to_ret, 0.0)
        self.assertAlmostEqual(age, 66.0, delta=_AGE_TOLERANCE)
        self.assertAlmostEqual(retirement_age, 66.0, delta=_AGE_TOLERANCE)


if __name__ == "__main__":
    unittest.main()
