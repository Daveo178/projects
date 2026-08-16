"""Tests for the chart-layer rounding helper and the two chart-builder
helpers in `simulation/charts.py`.

The contract we're pinning down:

  - `to_int_pounds([float])` -> list[int] (rounded to nearest pound)
  - `to_int_pounds([int])`   -> list[int] (idempotent — no spurious cast)
  - `to_int_pounds([None / NaN / pd.NA / np.nan])` -> unchanged, no raise
  - `net_worth_chart` / `income_vs_spending_chart` emit integer-typed
    monetary columns, never float64 (so Streamlit's chart axes / tooltips
    show whole pounds, not `120000.00000003`)

Engine precision is preserved — the engine still returns float Series;
only the DataFrame boundary round-trips to int.
"""

import math
import unittest

import numpy as np
import pandas as pd

from simulation.charts import (
    failure_age_histogram,
    income_vs_spending_chart,
    net_worth_chart,
    to_int_pounds,
)


class TestToIntPoundsBasics(unittest.TestCase):
    """Rounding correctness + idempotence on already-integer input."""

    def test_rounds_basic_floats(self):
        self.assertEqual(
            to_int_pounds([120_000.000_000_03, 50_000.4, -12.6, 0.0]),
            [120_000, 50_000, -13, 0],
        )

    def test_idempotent_on_ints(self):
        # An int in must come out as the same int type — no silent
        # float -> int truncation path that could surprise callers.
        self.assertEqual(
            to_int_pounds([100, 200, 0, -5]),
            [100, 200, 0, -5],
        )

    def test_idempotent_on_numpy_int(self):
        # `numpy.int64` is what an int `results[...]` Series yields after
        # a slice / `.tolist()`; the helper must round-trip with dtype
        # preserved as Python int.
        out = to_int_pounds([np.int64(7), np.int64(-3)])
        self.assertEqual(out, [7, -3])
        self.assertTrue(all(type(v) is int for v in out))


class TestToIntPoundsPassThrough(unittest.TestCase):
    """None / NaN / pd.NA all flow through unchanged without raising."""

    def test_passes_none_through(self):
        self.assertEqual(
            to_int_pounds([None, 100.4, None]),
            [None, 100, None],
        )

    def test_passes_python_nan_through(self):
        out = to_int_pounds([float("nan"), 100.4])
        self.assertEqual(out[1], 100)
        self.assertTrue(math.isnan(out[0]))

    def test_passes_numpy_nan_through(self):
        out = to_int_pounds([np.nan, 100.4, np.nan])
        self.assertEqual(out[1], 100)
        self.assertTrue(pd.isna(out[0]))
        self.assertTrue(pd.isna(out[2]))

    def test_passes_pd_NA_through(self):
        # pd.NA is pandas's nullable NA marker — used by Int64 columns.
        # `pd.isna(pd.NA)` is True, so the helper should pass it through
        # cleanly rather than crash on the float() conversion downstream.
        out = to_int_pounds([pd.NA, 100.4])
        self.assertEqual(out[1], 100)
        self.assertTrue(pd.isna(out[0]))

    def test_mixed_list_does_not_raise(self):
        # The Stephen Hawking test — every kind of missing-data carrier
        # mixed in with real numbers must come out the other side alive.
        out = to_int_pounds([
            120_000.000_000_03,
            float("nan"),
            None,
            np.nan,
            pd.NA,
            0.0,
            -12.6,
        ])
        self.assertEqual(out[0], 120_000)
        self.assertEqual(out[5], 0)
        self.assertEqual(out[6], -13)
        self.assertTrue(all(pd.isna(out[i]) for i in (1, 2, 3, 4)))


class TestFailureAgeHistogram(unittest.TestCase):
    """Failure ages are categorical month labels, not raw float noise."""

    def test_labels_fractional_current_age_in_months_and_sort_chronologically(self):
        frame = failure_age_histogram(
            [20, 0, 20, 1],
            55 + 10 / 12,
        )
        self.assertEqual(
            frame.to_dict("records"),
            [
                {"Failure Age": "55y 10m", "Failed Runs": 1},
                {"Failure Age": "56y 10m", "Failed Runs": 1},
                {"Failure Age": "75y 10m", "Failed Runs": 2},
            ],
        )

    def test_ignores_success_sentinels(self):
        frame = failure_age_histogram([None, 5, None], 60.0)
        self.assertEqual(
            frame.to_dict("records"),
            [{"Failure Age": "65y", "Failed Runs": 1}],
        )


class TestChartHelpersEmitInts(unittest.TestCase):
    """The two chart-builder helpers must downcast monetary float Series
    into int columns. Engine precision is preserved upstream; only the
    UI layer rounds."""

    def _results(self):
        # Minimal schema — these helpers only read the keys they touch.
        return {
            "years": [0, 1, 2],
            "net_worth": [100_000.7, 200_000.2, -1_234.6],
            "income": [60_000.9, 60_500.5, 0.0],
            "spending": [30_000.1, 30_000.1, 30_000.0],
        }

    def test_net_worth_chart_emits_int_column(self):
        df = net_worth_chart(self._results())
        # 'Year' stays int (engine range() output). 'Net Worth' must be
        # int-typed so the line chart tooltip shows whole pounds.
        self.assertEqual(
            df["Net Worth"].tolist(),
            [100_001, 200_000, -1_235],
        )
        self.assertTrue(
            pd.api.types.is_integer_dtype(df["Net Worth"]),
            f"expected integer dtype, got {df['Net Worth'].dtype}",
        )

    def test_income_vs_spending_chart_emits_int_columns(self):
        df = income_vs_spending_chart(self._results())
        for col in ("Income", "Spending", "Mortgage Payment"):
            self.assertTrue(
                pd.api.types.is_integer_dtype(df[col]),
                f"{col} dtype was {df[col].dtype}, expected integer",
            )
        self.assertEqual(df["Income"].tolist(), [60_001, 60_500, 0])
        self.assertEqual(df["Spending"].tolist(), [30_000, 30_000, 30_000])

    def test_income_vs_spending_chart_handles_missing_mortgage_field(self):
        # Older saved sessions may not carry `mortgage_payment`; the
        # helper falls back to all-zeros. The fallback must also be
        # integer-typed, not float64.
        results = {
            "years": [0, 1],
            "income": [60_000.5, 60_001.5],
            "spending": [30_000.0, 30_000.0],
        }
        df = income_vs_spending_chart(results)
        self.assertTrue(
            pd.api.types.is_integer_dtype(df["Mortgage Payment"])
        )
        self.assertEqual(df["Mortgage Payment"].tolist(), [0, 0])


if __name__ == "__main__":
    unittest.main()
