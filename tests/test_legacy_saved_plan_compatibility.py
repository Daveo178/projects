"""Compatibility tests for plans saved by older app versions."""

import unittest

from models.person import Person
from pages_helpers.household_builder import _construct_from_saved_dict


class TestLegacySavedPlanCompatibility(unittest.TestCase):
    def test_obsolete_saved_fields_do_not_block_model_construction(self):
        """Old UI-only fields are ignored when rebuilding a Person."""
        person = _construct_from_saved_dict(
            Person,
            {
                "name": "Person 1",
                "age": 55.0,
                "retirement_age": 60.0,
                "state_pension_age": 67.0,
                "dc_pot": 100_000.0,
                "retirement_date": "2031-01-01",
                "obsolete_ui_field": "from an older export",
            },
        )

        self.assertEqual(person.name, "Person 1")
        self.assertEqual(person.dc_pot, 100_000.0)
        self.assertEqual(person.retirement_date, "2031-01-01")
        self.assertFalse(hasattr(person, "obsolete_ui_field"))


if __name__ == "__main__":
    unittest.main()
