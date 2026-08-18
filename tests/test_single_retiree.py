"""Regression tests for single-retiree household projections."""
from __future__ import annotations

import unittest

from models.asset import Asset
from models.household import Household
from models.person import Person
from simulation.engine import run_simulation
from simulation.monte_carlo import _resolve_horizon


def _person(
    name: str,
    *,
    age: float,
    retirement_age: float,
    state_pension_age: float,
    dc_pot: float = 0.0,
    db_income: float = 0.0,
    income: float = 0.0,
) -> Person:
    return Person(
        name=name,
        age=age,
        retirement_age=retirement_age,
        state_pension_age=state_pension_age,
        dc_pot=dc_pot,
        db_income=db_income,
        draw_age=age,
        income_until_retirement=income,
        pcls_percent=25,
        monthly_contrib=0.0,
        monthly_contrib_pct=0.0,
        income_growth_rate=0.0,
        dc_growth_rate=0.0,
        db_growth_rate=0.0,
        state_pension_growth_rate=0.0,
    )


def _household(*, single_retiree: bool) -> Household:
    return Household(
        person1=_person(
            "P1",
            age=55.0,
            retirement_age=60.0,
            state_pension_age=100.0,
            dc_pot=10_000.0,
        ),
        person2=_person(
            "P2",
            age=30.0,
            retirement_age=35.0,
            state_pension_age=30.0,
            dc_pot=100_000.0,
            db_income=50_000.0,
            income=100_000.0,
        ),
        assets=[
            Asset(name="Cash", value=0.0, growth_rate=0.0, asset_type="Cash")
        ],
        spending_target=20_000.0,
        life_expectancy_end_age=70.0,
        single_retiree=single_retiree,
    )


class TestSingleRetiree(unittest.TestCase):
    def test_person2_is_completely_excluded_including_state_pension(self):
        household = _household(single_retiree=True)
        result = run_simulation(household)

        # Only Person 1 drives the horizon: 70 - 55, not Person 2's
        # 40 years to the plan-end age.
        self.assertEqual(len(result["years"]), 15)
        self.assertEqual(_resolve_horizon(household, None), 15)

        # Person 2 reaches State Pension age immediately and has large
        # wages, DB, and DC inputs, but none may enter any result series.
        self.assertTrue(all(value == 0 for value in result["p2_gross_income"]))
        self.assertTrue(all(value == 0 for value in result["p2_tax"]))
        self.assertTrue(all(value == 0 for value in result["p2_ni"]))
        self.assertTrue(all(value == 0 for value in result["state_payout"]))
        self.assertEqual(household.person2.dc_pot, 100_000.0)
        self.assertEqual(result["dc_pot"][0], 10_000.0)

    def test_single_mode_matches_person1_only_baseline(self):
        single = _household(single_retiree=True)
        baseline = _household(single_retiree=False)
        baseline.person2 = _person(
            "P2",
            age=55.0,
            retirement_age=60.0,
            state_pension_age=100.0,
        )

        single_result = run_simulation(single)
        baseline_result = run_simulation(baseline, years=15)

        self.assertEqual(single_result["net_worth"], baseline_result["net_worth"])
        self.assertEqual(single_result["income"], baseline_result["income"])
        self.assertEqual(single_result["state_payout"], baseline_result["state_payout"])


if __name__ == "__main__":
    unittest.main()
