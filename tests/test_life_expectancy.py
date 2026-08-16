"""Tests for the life_expectancy_end_age-driven horizon added to
`simulation/engine.py::run_simulation`.

The new contract replaces the hardcoded `years=45` default with a
dynamic horizon read off the Household:

    years = max(end_age - p1.age, end_age - p2.age), floored at 5

Joint-life "last to die" semantics: the longer of the two partners'
remaining years to `end_age` is the horizon — that means BOTH
partners are funded to the target age. A floor at 5 protects the
engine when both partners are already past `end_age` (avoids a
0-length axis that would crash `np.array(all_paths)` in the Monte
Carlo percentile step).

Key contracts locked down by this test class:

  * The default `years=None` reads `life_expectancy_end_age` and
    resolves the horizon via the joint-life formula.
  * Explicit `years=N` call-time override wins over the
    `life_expectancy_end_age` dynamic calculation (used by the
    Monte Carlo sampler and the What If page).
  * The 5-year floor kicks in when both partners are already past
    the target (e.g. end_age=95 with both partners aged 96+).
  * Legacy `Household(...)` instances without the field default
    to 95.0 and run cleanly.
"""

from __future__ import annotations

import unittest

from models.household import Household
from models.person import Person
from simulation.engine import run_simulation


def _make_person(name: str, age: float) -> Person:
    """Trivial Person constructor. Zero income / DC / DB so the
    simulation produces a sustainable ignored-asset trajectory for
    all ages — we only care about the year-axis length here, not
    the financial output.
    """
    return Person(
        name=name,
        age=age,
        retirement_age=60.0,
        state_pension_age=67.0,
        dc_pot=0.0,
        income_until_retirement=0.0,
        db_income=0.0,
        draw_age=60.0,
        pcls_percent=0,
    )


def _build_household(
    age_p1: float = 55.0,
    age_p2: float = 55.0,
    life_expectancy_end_age: float = 95.0,
) -> Household:
    """Two-partner baseline. Returns a Household with the new
    `life_expectancy_end_age` set explicitly so the dynamic
    horizon calc has data to read. To test legacy paths, simply
    `del h.life_expectancy_end_age` before `run_simulation`.
    """
    return Household(
        person1=_make_person("Dave", age_p1),
        person2=_make_person("Shaz", age_p2),
        assets=[],
        mortgage=None,
        spending_target=30_000.0,
        drawdown_strategy="Fixed",
        events=[],
        cash_buffer=False,
        taper_start_age=75.0,
        taper_rate=0.02,
        taper_floor_gbp=10_000.0,
        life_expectancy_end_age=life_expectancy_end_age,
    )


class TestLifeExpectancyHorizon(unittest.TestCase):
    """Verifies `run_simulation(household)` resolves the horizon
    from `life_expectancy_end_age` via the joint-life last-to-die
    formula."""

    def test_default_horizon_uses_life_expectancy_end_age(self):
        """A 55-year-old couple with end_age=95 should run 40
        years (`max(95-55, 95-55) = 40`)."""
        h = _build_household(age_p1=55.0, age_p2=55.0,
                             life_expectancy_end_age=95.0)
        res = run_simulation(h)
        self.assertEqual(
            len(res["years"]), 40,
            msg=(
                f"expected 40 years for (55, 55) -> 95, got "
                f"{len(res['years'])}"
            ),
        )

    def test_joint_math_uses_longest_remaining_years(self):
        """55 + 60 + end_age=95 → 40 years (the OLDER partner's
        remaining years drive the horizon, so the younger partner
        is also covered through 95)."""
        h = _build_household(age_p1=55.0, age_p2=60.0,
                             life_expectancy_end_age=95.0)
        res = run_simulation(h)
        # max(95-55, 95-60) = max(40, 35) = 40
        self.assertEqual(
            len(res["years"]), 40,
            msg=(
                f"expected 40 years for (55, 60) -> 95, got "
                f"{len(res['years'])}"
            ),
        )

    def test_joint_math_swapped_person1_offset(self):
        """Same numbers, swap ages: 60 + 55 + end_age=95 → still
        40 (max is symmetric). Locks down that the formula is
        `max(end - p1.age, end - p2.age)` not `end - p1.age` —
        i.e. the field-order independence contract."""
        h = _build_household(age_p1=60.0, age_p2=55.0,
                             life_expectancy_end_age=95.0)
        res = run_simulation(h)
        self.assertEqual(len(res["years"]), 40)

    def test_floor_at_5_years_when_both_already_past_target(self):
        """Both partners already older than target — e.g. 96 + 97,
        end_age=95. `max(95-96, 95-97) = max(-1, -2) = -1`,
        floored at 5 — engine must NOT crash with a negative-
        length axis or a 0-length array."""
        h = _build_household(age_p1=96.0, age_p2=97.0,
                             life_expectancy_end_age=95.0)
        res = run_simulation(h)
        self.assertEqual(
            len(res["years"]), 5,
            msg=(
                f"expected 5-year floor for (96, 97) past target "
                f"95, got {len(res['years'])}"
            ),
        )

    def test_shorter_horizon_than_default_45(self):
        """User hands it a 25-year horizon (end_age=80 for a
        55-year-old couple, max delta = 25). Verifies the engine
        can produce horizons SHORTER than the historical
        45-year hardcoded default."""
        h = _build_household(age_p1=55.0, age_p2=55.0,
                             life_expectancy_end_age=80.0)
        res = run_simulation(h)
        self.assertEqual(len(res["years"]), 25)

    def test_longer_horizon_than_45(self):
        """A 35-year-old couple with end_age=95 → 60 years. The
        old hardcoded default would have capped at 45 and
        silently truncated the timeline — under the new
        contract the horizon is dynamic."""
        h = _build_household(age_p1=35.0, age_p2=35.0,
                             life_expectancy_end_age=95.0)
        res = run_simulation(h)
        self.assertEqual(len(res["years"]), 60)


class TestExplicitYearsOverrides(unittest.TestCase):
    """Verifies explicit `years=N` caller override beats the
    `life_expectancy_end_age` dynamic calculation."""

    def test_explicit_years_short_circuits_dynamic_calc(self):
        """Even with end_age=95 set, a caller passing `years=10`
        gets a 10-year horizon. Monte Carlo and What If rely on
        this for sensitivity analysis."""
        h = _build_household(age_p1=55.0, age_p2=55.0,
                             life_expectancy_end_age=95.0)
        res = run_simulation(h, years=10)
        self.assertEqual(len(res["years"]), 10)

    def test_explicit_years_can_extend_beyond_life_expectancy(self):
        """Caller explicitly asks for `years=80` even though
        end_age=95 for a 35-year-old couple would yield 60.
        The override wins (used for stress-testing)."""
        h = _build_household(age_p1=35.0, age_p2=35.0,
                             life_expectancy_end_age=95.0)
        res = run_simulation(h, years=80)
        self.assertEqual(len(res["years"]), 80)


class TestBackCompat(unittest.TestCase):
    """Legacy Household instances without `life_expectancy_end_age`
    default to 95.0 via the engine's `getattr(..., 95.0)` defensive
    read."""

    def test_legacy_household_without_end_age_runs(self):
        """Simulate a legacy saved-JSON plan that pre-dates the
        new field by `del`-ing the field after construction."""
        h = _build_household(age_p1=55.0, age_p2=55.0,
                             life_expectancy_end_age=95.0)
        del h.life_expectancy_end_age
        res = run_simulation(h)
        # `getattr(h, "life_expectancy_end_age", 95.0)` → 95.0,
        # so horizon = max(95-55, 95-55) = 40 — the same as the
        # historical 45-year default would have produced for a
        # 55-year-old couple.
        self.assertEqual(len(res["years"]), 40)

    def test_dataclass_default_is_95(self):
        """The dataclass-level default for the new field is 95.0
        — agentless `Household(...)` constructions without
        explicit `life_expectancy_end_age=` should pick this up
        via the regular `__init__` path."""
        h = Household(
            person1=_make_person("Dave", 55.0),
            person2=_make_person("Shaz", 55.0),
            assets=[],
            mortgage=None,
            spending_target=30_000.0,
            drawdown_strategy="Fixed",
        )
        self.assertEqual(h.life_expectancy_end_age, 95.0)


if __name__ == "__main__":
    unittest.main()
