"""
Regression tests for ``simulation/monte_carlo.monte_carlo_simulation``.

The headline property under test: every returned path has the same length
as the caller-provided ``years``.

History
-------
``monte_carlo_simulation`` used to call ``sample_longevity(...)`` inside
the run loop to randomly vary the per-run horizon (~normal(45, 5),
clamped to [20, 70]). That produced variable-length paths per run and the
tail ``np.array(all_paths)`` blew up with::

    ValueError: setting an array element with a sequence. The requested
    array has an inhomogeneous shape after 1 dimensions. The detected
    shape was (1000,) + inhomogeneous part.

The fix is to honour the caller-provided ``years`` for every path. This
file pins that invariant so a regression cannot silently re-introduce
variable-length paths via a future refactor.
"""
import unittest

import numpy as np

from models.person import Person
from models.household import Household
from simulation.monte_carlo import monte_carlo_simulation


def _minimal_household():
    """Household shaped for a small fast MC. No assets, no DB / SP."""
    p1 = Person(
        name="P1",
        age=55,
        retirement_age=99,        # never retire — no drawdown in the test
        state_pension_age=99,
        dc_pot=0.0,
        db_income=0.0,
        monthly_contrib=0.0,
        income_until_retirement=0.0,
        draw_age=99,
        pcls_percent=0,
        income_growth_rate=0.0,
        monthly_contrib_pct=0.0,
        dc_growth_rate=0.05,
        db_growth_rate=0.0,
        state_pension_growth_rate=0.0,
    )
    p2 = Person(
        name="P2",
        age=55,
        retirement_age=99,
        state_pension_age=99,
        dc_pot=0.0,
        db_income=0.0,
        monthly_contrib=0.0,
        income_until_retirement=0.0,
        draw_age=99,
        pcls_percent=0,
        income_growth_rate=0.0,
        monthly_contrib_pct=0.0,
        dc_growth_rate=0.05,
        db_growth_rate=0.0,
        state_pension_growth_rate=0.0,
    )
    return Household(
        person1=p1, person2=p2, assets=[], mortgage=None,
        spending_target=0, events=[],
    )


def _seed():
    """Deterministic seed keeps the test repeatable across runs."""
    np.random.seed(20260628)


class TestMonteCarloSameLengthPaths(unittest.TestCase):
    """Lock the homogeneous-paths invariant under the np.array call."""

    def test_all_paths_have_same_length_as_horizon(self):
        _seed()
        h = _minimal_household()
        years = 30
        runs = 20
        mc = monte_carlo_simulation(h, runs=runs, years=years)

        self.assertEqual(len(mc["all_paths"]), runs)
        # The regressed crash was at the array() call inside the engine,
        # so the public-facing symptom is "every returned path must be of
        # length == years."
        for i, path in enumerate(mc["all_paths"]):
            with self.subTest(run=i):
                self.assertEqual(len(path), years)
        # Every percentile list must also be length-years.
        for k in ("p10", "p25", "p50", "p75", "p90"):
            self.assertEqual(len(mc["percentiles"][k]), years)

    def test_all_paths_round_trip_through_np_array(self):
        # Defence in depth — even if a future refactor relaxes the
        # same-length invariant, this would have caught the original
        # ValueError directly. The page collapses all_paths back through
        # np.array at line 140, so the array-call path must succeed.
        _seed()
        h = _minimal_household()
        years = 25
        runs = 15
        mc = monte_carlo_simulation(h, runs=runs, years=years)
        arr = np.array(mc["all_paths"])
        self.assertEqual(arr.shape, (runs, years))

    def test_all_paths_are_finite(self):
        # Sanity: no NaN / inf leaks into the fan-chart inputs. Cheap to
        # check given same-length paths are already guaranteed.
        _seed()
        h = _minimal_household()
        years = 20
        runs = 10
        mc = monte_carlo_simulation(h, runs=runs, years=years)
        for i, path in enumerate(mc["all_paths"]):
            for y, nw in enumerate(path):
                with self.subTest(run=i, year=y):
                    self.assertFalse(
                        nw != nw,  # NaN != NaN is True
                        f"NaN at run {i}, year {y}",
                    )
                    self.assertLess(abs(nw), 1e12)

    def test_success_rate_is_between_zero_and_one(self):
        _seed()
        h = _minimal_household()
        mc = monte_carlo_simulation(h, runs=10, years=20)
        self.assertGreaterEqual(mc["success_rate"], 0.0)
        self.assertLessEqual(mc["success_rate"], 1.0)

    def test_return_dict_does_not_carry_lifetimes(self):
        # `lifetimes` used to be returned but was unused by both pages
        # and produced the variable-length bug. Pinning absence locks
        # the fix.
        _seed()
        h = _minimal_household()
        mc = monte_carlo_simulation(h, runs=5, years=10)
        self.assertNotIn("lifetimes", mc)
        # The four public keys are present and have sensible shapes.
        self.assertIn("percentiles", mc)
        self.assertIn("success_rate", mc)
        self.assertIn("failure_years", mc)
        self.assertIn("all_paths", mc)
        self.assertEqual(len(mc["failure_years"]), 5)


if __name__ == "__main__":
    unittest.main()
