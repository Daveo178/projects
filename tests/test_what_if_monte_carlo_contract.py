"""Regression coverage for the What-If → Monte Carlo contract."""

import copy
import unittest

import numpy as np

from models.asset import Asset
from models.household import Household
from models.person import Person
from simulation.monte_carlo import monte_carlo_simulation


def _household():
    return Household(
        person1=Person(
            name="Person 1", age=65.0, retirement_age=60.0,
            state_pension_age=99.0, dc_pot=1_000_000.0,
            db_income=0.0, draw_age=99.0,
            income_until_retirement=60_000.0,
            monthly_contrib=0.0, monthly_contrib_pct=0.15,
            dc_growth_rate=0.05,
        ),
        person2=Person(
            name="Person 2", age=65.0, retirement_age=60.0,
            state_pension_age=99.0, dc_pot=0.0,
            db_income=0.0, draw_age=99.0,
            income_until_retirement=0.0,
            monthly_contrib=0.0, monthly_contrib_pct=0.0,
            dc_growth_rate=0.05,
        ),
        assets=[Asset(
            name="ISA",            value=500_000.0, growth_rate=0.05,

            asset_type="ISA",
        )],
        spending_target=5_000.0,
        events=[],
        life_expectancy_end_age=75.0,
    )


class TestWhatIfMonteCarloContract(unittest.TestCase):
    def test_growth_and_inflation_overrides_change_same_seed_output(self):
        baseline = _household()
        scenario = copy.deepcopy(baseline)
        scenario.person1.dc_growth_rate = 0.08
        scenario.assets[0].growth_rate = 0.08
        scenario.inflation_rate = 0.04

        np.random.seed(111)
        base_result = monte_carlo_simulation(baseline, runs=20, years=10)
        np.random.seed(111)
        scenario_result = monte_carlo_simulation(scenario, runs=20, years=10)

        self.assertNotEqual(
            base_result["percentiles"]["p50"][-1],
            scenario_result["percentiles"]["p50"][-1],
        )

    def test_legacy_monthly_contribution_override_is_not_shadowed(self):
        household = _household()
        person = household.person1
        person.monthly_contrib = 500.0
        person.monthly_contrib_pct = 0.0
        person.personal_contrib_pct = 0.0
        person.personal_contrib_flat_monthly = 0.0
        person.employer_contrib_pct = 0.0

        # The engine's legacy branch now uses £500/12 per month, rather
        # than the original saved 15% percentage, which What-If controls
        # are intended to replace.
        from simulation.engine import _monthly_dc_contrib
        self.assertAlmostEqual(
            _monthly_dc_contrib(person, 60_000.0),
            500.0 / 12.0,
        )


if __name__ == "__main__":
    unittest.main()
