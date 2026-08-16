import unittest

from pages_helpers.strategy_options import (
    DRAW_DOWN_STRATEGIES,
    normalize_drawdown_strategy,
)


class TestDrawdownStrategyOptions(unittest.TestCase):
    def test_all_supported_strategies_are_preserved(self):
        for strategy in DRAW_DOWN_STRATEGIES:
            with self.subTest(strategy=strategy):
                self.assertEqual(normalize_drawdown_strategy(strategy), strategy)

    def test_tapered_strategy_is_available_for_scenarios(self):
        self.assertIn("Tapered (down with age)", DRAW_DOWN_STRATEGIES)

    def test_unknown_or_missing_strategy_falls_back_to_fixed(self):
        for value in (None, "", "legacy-value", 4):
            with self.subTest(value=value):
                self.assertEqual(normalize_drawdown_strategy(value), "Fixed")


if __name__ == "__main__":
    unittest.main()
