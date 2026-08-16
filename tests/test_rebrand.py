"""Regression tests for the generic Couples' Retirement Planner branding."""

import unittest

from model_defaults import default_partner_dict
from models.household import Household
from models.person import Person


class TestGenericPartnerDefaults(unittest.TestCase):
    def test_blank_plan_defaults_use_generic_display_names(self):
        self.assertEqual(
            default_partner_dict("Person 1", p1=True)["name"],
            "Person 1",
        )
        self.assertEqual(
            default_partner_dict("Person 2", p1=False)["name"],
            "Person 2",
        )

    def test_age_projection_uses_stable_generic_slot_labels(self):
        household = Household(
            person1=Person(name="Dave", age=55.0, retirement_age=60.0,
                           state_pension_age=67.0, dc_pot=0.0,
                           db_income=0.0),
            person2=Person(name="Shaz", age=56.0, retirement_age=60.0,
                           state_pension_age=67.0, dc_pot=0.0,
                           db_income=0.0),
        )
        self.assertEqual(
            household.ages_in_year(2),
            {"Person 1": 57.0, "Person 2": 58.0},
        )


class TestGenericAIPrompts(unittest.TestCase):
    def test_branding_title_is_consistent_in_entry_points(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for relative_path in ("main.py", "brand_chrome.py", "pages/0_Quick_Estimate.py"):
            text = (root / relative_path).read_text(encoding="utf-8")
            self.assertIn("Couples' Retirement Planner", text)
            self.assertNotIn("Shaz and Dave's Road to Retirement", text)


if __name__ == "__main__":
    unittest.main()
