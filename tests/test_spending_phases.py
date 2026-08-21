"""Regression tests for explicit age-based spending phases."""

from __future__ import annotations

import unittest

from models.asset import Asset
from models.household import Household
from models.person import Person
from simulation.engine import run_simulation
from simulation.spending import normalize_spending_phases, spending_for_age
from simulation.sustainable_spending import find_max_sustainable_spending


class TestSpendingPhases(unittest.TestCase):
    def test_phase_lookup_uses_inclusive_thresholds_and_final_phase(self):
        phases = [
            {"annual_spending": 40_000, "until_age": 70},
            {"annual_spending": 30_000, "until_age": 80},
            {"annual_spending": 20_000, "until_age": 94},
        ]

        self.assertEqual(spending_for_age(69, phases), 40_000)
        self.assertEqual(spending_for_age(70, phases), 40_000)
        self.assertEqual(spending_for_age(71, phases), 30_000)
        self.assertEqual(spending_for_age(80, phases), 30_000)
        self.assertEqual(spending_for_age(81, phases), 20_000)
        self.assertEqual(spending_for_age(100, phases), 20_000)

    def test_malformed_or_reversed_phases_are_safe(self):
        phases = normalize_spending_phases([
            {"annual_spending": 20_000, "until_age": 94},
            {"annual_spending": 40_000, "until_age": 70},
            {"annual_spending": 30_000, "until_age": 80},
        ])

        self.assertEqual(
            phases,
            [
                {"annual_spending": 40_000.0, "until_age": 70.0},
                {"annual_spending": 30_000.0, "until_age": 80.0},
                {"annual_spending": 20_000.0, "until_age": 94.0},
            ],
        )
        self.assertEqual(
            normalize_spending_phases([], fallback_spending=35_000, fallback_end_age=95),
            [{"annual_spending": 35_000.0, "until_age": 95.0}],
        )

    def test_solver_scales_active_phase_amounts_and_preserves_ages(self):
        person = Person(
            name="Person 1",
            age=60.0,
            retirement_age=60.0,
            state_pension_age=100.0,
            dc_pot=0.0,
        )
        household = Household(
            person1=person,
            person2=Person(
                name="Person 2",
                age=60.0,
                retirement_age=60.0,
                state_pension_age=100.0,
                dc_pot=0.0,
            ),
            assets=[Asset("Cash", 500_000.0, 0.01, "Cash")],
            spending_target=40_000.0,
            spending_phases=[
                {"annual_spending": 40_000, "until_age": 65},
                {"annual_spending": 30_000, "until_age": 70},
                {"annual_spending": 20_000, "until_age": 80},
            ],
            drawdown_strategy="Spending phases",
            life_expectancy_end_age=80.0,
        )

        result = find_max_sustainable_spending(household, 80.0)

        self.assertIsNone(result.error)
        self.assertIsNotNone(result.spending_phases)
        self.assertEqual(
            [phase["until_age"] for phase in result.spending_phases],
            [65.0, 70.0, 80.0],
        )
        first = result.spending_phases[0]["annual_spending"]
        self.assertAlmostEqual(
            result.spending_phases[1]["annual_spending"] / first,
            0.75,
            places=7,
        )
        self.assertAlmostEqual(
            result.spending_phases[2]["annual_spending"] / first,
            0.50,
            places=7,
        )

    def test_engine_records_explicit_phase_series(self):
        person = Person(
            name="Person 1",
            age=60.0,
            retirement_age=60.0,
            state_pension_age=100.0,
            dc_pot=0.0,
        )
        household = Household(
            person1=person,
            person2=Person(
                name="Person 2",
                age=60.0,
                retirement_age=60.0,
                state_pension_age=100.0,
                dc_pot=0.0,
            ),
            spending_target=40_000.0,
            spending_phases=[
                {"annual_spending": 40_000, "until_age": 70},
                {"annual_spending": 30_000, "until_age": 80},
                {"annual_spending": 20_000, "until_age": 94},
            ],
            drawdown_strategy="Spending phases",
            life_expectancy_end_age=94.0,
        )

        results = run_simulation(household)

        self.assertEqual(results["spending"][0], 40_000)
        self.assertEqual(results["spending"][10], 40_000)  # age 70
        self.assertEqual(results["spending"][11], 30_000)  # age 71
        self.assertEqual(results["spending"][20], 30_000)  # age 80
        self.assertEqual(results["spending"][21], 20_000)  # age 81


if __name__ == "__main__":
    unittest.main()
