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

    def test_run_diagnostics_match_paths_and_include_sampled_rates(self):
        _seed()
        h = _minimal_household()
        mc = monte_carlo_simulation(h, runs=4, years=8)

        self.assertEqual(len(mc["run_diagnostics"]), 4)
        self.assertEqual(
            [row["Run"] for row in mc["run_diagnostics"]],
            [1, 2, 3, 4],
        )
        for row in mc["run_diagnostics"]:
            self.assertIn(row["Outcome"], ("Succeeded", "Failed"))
            self.assertIn("P1 DC growth", row)
            self.assertIn("Inflation min", row)
            self.assertIn("ISA return max", row)
            self.assertIn("Spending shock min", row)

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

    def test_today_value_mode_deflates_each_path(self):
        """Explicit today's-money output removes each path's sampled
        cumulative inflation, while the default remains nominal."""
        import copy

        h = _minimal_household()
        h.person1.retirement_age = 99
        h.person1.dc_pot = 100_000.0
        h.spending_target = 0.0
        h_today = copy.deepcopy(h)
        h_today.show_in_todays_value = True

        np.random.seed(1234)
        nominal = monte_carlo_simulation(h, runs=20, years=15)
        np.random.seed(1234)
        today = monte_carlo_simulation(
            h_today, runs=20, years=15, today_value_mode=True
        )

        self.assertLess(
            today["all_paths"][0][0],
            nominal["all_paths"][0][0],
        )
        self.assertLess(
            today["percentiles"]["p50"][-1],
            nominal["percentiles"]["p50"][-1],
        )
        for band in ("p10", "p25", "p50", "p75", "p90"):
            self.assertEqual(len(today["percentiles"][band]), 15)

    def test_display_currency_does_not_change_success_rate(self):
        """Success is a nominal cash-flow outcome, not a chart unit.

        With identical random draws, requesting today's-money output may
        change displayed percentile values but must not change which paths
        ran out of money.
        """
        import copy

        h = _minimal_household()
        h.person1.dc_pot = 100_000.0
        h.spending_target = 10_000.0
        h_today = copy.deepcopy(h)

        np.random.seed(9876)
        nominal = monte_carlo_simulation(h, runs=40, years=20)
        np.random.seed(9876)
        today = monte_carlo_simulation(
            h_today, runs=40, years=20, today_value_mode=True
        )

        self.assertEqual(nominal["success_rate"], today["success_rate"])
        self.assertEqual(nominal["failure_years"], today["failure_years"])

    def test_household_growth_means_affect_monte_carlo(self):
        """MC keeps its stochastic spread but honours household means."""
        import copy

        low = _minimal_household()
        low.person1.dc_pot = 100_000.0
        high = copy.deepcopy(low)
        high.person1.dc_growth_rate = 0.20

        np.random.seed(2468)
        low_result = monte_carlo_simulation(low, runs=20, years=10)
        np.random.seed(2468)
        high_result = monte_carlo_simulation(high, runs=20, years=10)

        self.assertGreater(
            high_result["percentiles"]["p50"][-1],
            low_result["percentiles"]["p50"][-1],
        )

    def test_household_inflation_mean_affects_monte_carlo_spending(self):
        """MC uses the household inflation assumption, not only its
        module-level default, when constructing nominal spending paths."""
        import copy

        low = _minimal_household()
        low.person1.age = 65.0
        low.person1.retirement_age = 60.0
        low.person2.age = 65.0
        low.person2.retirement_age = 60.0
        low.person1.dc_pot = 100_000.0
        low.spending_target = 10_000.0
        high = copy.deepcopy(low)
        high.inflation_rate = 0.08

        np.random.seed(1357)
        low_result = monte_carlo_simulation(low, runs=20, years=10)
        np.random.seed(1357)
        high_result = monte_carlo_simulation(high, runs=20, years=10)

        self.assertNotEqual(
            low_result["all_paths"][0][-1],
            high_result["all_paths"][0][-1],
        )

    def test_default_horizon_matches_household_joint_life_horizon(self):
        """Omitting ``years`` uses the same horizon as run_simulation."""
        h = _minimal_household()
        h.life_expectancy_end_age = 70.0
        result = monte_carlo_simulation(h, runs=2)
        self.assertEqual(len(result["all_paths"][0]), 15)

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


class TestMonteCarloPerYearGrowthPaths(unittest.TestCase):
    """Growth rates are sampled per year, not once per run.

    The user flagged that DC pension growth looked fixed for all years of
    a run while ISA/cash/GIA reported per-year ranges. Two problems were
    fixed:

    1. Pension-style rates (DC/DB) were sampled ONCE per run and held
       fixed for every year. They are now sampled fresh each year, and
       the State Pension is indexed to that run's sampled inflation path.
    2. Asset rates WERE sampled per year but the assignment loop ran
       before the engine and only the last year's sample stuck, so the
       simulation actually used one fixed rate for all years while the
       diagnostics table showed ranges from samples that were never
       applied. The per-year path is now consumed by the engine.
    """

    def test_dc_growth_varies_year_to_year_within_a_run(self):
        """A single run's DC growth is not constant across its years."""
        _seed()
        h = _minimal_household()
        h.person1.dc_pot = 100_000.0
        mc = monte_carlo_simulation(h, runs=1, years=12)
        row = mc["run_diagnostics"][0]
        self.assertIn("P1 DC growth min", row)
        self.assertIn("P1 DC growth max", row)
        self.assertLess(row["P1 DC growth min"], row["P1 DC growth max"])

    def test_state_pension_tracks_sampled_inflation(self):
        """State Pension indexation equals that run's sampled inflation."""
        _seed()
        h = _minimal_household()
        h.person1.state_pension_age = 66.0
        h.person1.age = 65.0
        mc = monte_carlo_simulation(h, runs=1, years=8)
        row = mc["run_diagnostics"][0]
        self.assertAlmostEqual(
            row["P1 State Pension growth min"], row["Inflation min"]
        )
        self.assertAlmostEqual(
            row["P1 State Pension growth max"], row["Inflation max"]
        )

    def test_engine_consumes_per_year_dc_growth_path(self):
        """The DC pot compounds with each year's own rate, not one fixed rate."""
        from simulation.engine import _dc_monthly_compound, run_simulation

        h = _minimal_household()
        h.person1.dc_pot = 100_000.0
        rates = [0.01, 0.05, 0.09, 0.02]
        h.person1.dc_growth_path = rates
        results = run_simulation(h, years=len(rates))
        expected = 100_000.0
        for r in rates:
            expected = _dc_monthly_compound(expected, r, 0.0)
        self.assertAlmostEqual(results["dc_pot"][-1], expected, places=2)

    def test_engine_consumes_per_year_asset_growth_path(self):
        """ISA value appreciates at each year's sampled rate."""
        from models.asset import Asset
        from simulation.engine import run_simulation

        h = _minimal_household()
        isa = Asset(
            name="ISA", value=10_000.0, growth_rate=0.05, asset_type="ISA"
        )
        isa.growth_path = [0.01, 0.10, 0.02]
        h.assets = [isa]
        results = run_simulation(h, years=len(isa.growth_path))
        expected = 10_000.0 * 1.01 * 1.10 * 1.02
        self.assertAlmostEqual(results["isa_value"][-1], expected, places=2)

    def test_engine_state_pension_path_compounds_cumulatively(self):
        """State Pension payouts follow the per-year indexation path."""
        from simulation.engine import run_simulation
        from simulation.state_pension import FULL_STATE_PENSION

        h = _minimal_household()
        h.person1.age = 66.0
        h.person1.state_pension_age = 66.0
        h.person1.state_pension_growth_path = [0.01, 0.03, 0.02]
        results = run_simulation(h, years=3)
        self.assertAlmostEqual(
            results["state_payout"][0], FULL_STATE_PENSION, places=2
        )
        self.assertAlmostEqual(
            results["state_payout"][1],
            FULL_STATE_PENSION * 1.01,
            places=2,
        )
        self.assertAlmostEqual(
            results["state_payout"][2],
            FULL_STATE_PENSION * 1.01 * 1.03,
            places=2,
        )

    def test_engine_scalar_rates_unchanged_without_paths(self):
        """Deterministic runs without paths keep the scalar compounding."""
        from simulation.engine import run_simulation

        h = _minimal_household()
        h.person1.dc_pot = 100_000.0
        h.person1.dc_growth_rate = 0.05
        results = run_simulation(h, years=3)
        expected = 100_000.0 * (1 + 0.05 / 12) ** 36
        self.assertAlmostEqual(results["dc_pot"][-1], expected, places=2)

    def test_default_db_volatility_is_zero_for_guaranteed_db_income(self):
        """The suggested baseline does not randomly reduce DB indexation."""
        from simulation.monte_carlo import DEFAULT_VOLATILITY_RANGES

        self.assertEqual(DEFAULT_VOLATILITY_RANGES["db"], (0.0, 0.0))

    def test_nominal_pensions_are_indexed_before_their_start_date(self):
        """Nominal MC uplifts today's-money pension bases before payment.

        A pension beginning next year must not start at the same nominal
        pounds as today's value; otherwise inflation-indexed spending is
        overstated relative to guaranteed income and creates false failures.
        """
        h = _minimal_household()
        h.person1.age = 65.0
        h.person1.retirement_age = 60.0
        h.person1.draw_age = 65.0
        h.person1.db_income = 10_000.0
        h.person1.state_pension_age = 66.0
        h.spending_target = 0.0

        zero_volatility = {
            key: (0.0, 0.0) for key in (
                "dc", "isa_gia", "property", "cash", "inflation",
                "spending", "db", "income",
            )
        }
        result = monte_carlo_simulation(
            h,
            runs=1,
            years=3,
            volatility_ranges=zero_volatility,
        )

        # State Pension starts in year 1, after one 2.5% inflation year.
        self.assertAlmostEqual(result["run_diagnostics"][0]["Inflation mean"], 0.025)
        self.assertAlmostEqual(result["all_paths"][0][1], 0.0, places=6)

        # The DB is £10,000 gross and is the only guaranteed income in
        # year 0; keep the test spending below its after-tax amount. The
        # State Pension starts in year 1 and is checked by the direct
        # engine/path tests above.
        h.spending_target = 9_000.0
        funded = monte_carlo_simulation(
            h,
            runs=1,
            years=2,
            volatility_ranges=zero_volatility,
        )
        self.assertEqual(funded["failure_years"], [None])

    def test_custom_volatility_ranges_are_sampled_per_run(self):
        """Custom lower/upper bounds reach diagnostics and preserve
        annual randomness when the bounds are non-zero."""
        _seed()
        h = _minimal_household()
        result = monte_carlo_simulation(
            h,
            runs=4,
            years=10,
            volatility_ranges={
                "dc": (0.04, 0.06),
                "isa_gia": (0.08, 0.12),
                "property": (0.04, 0.06),
                "cash": (0.005, 0.015),
                "inflation": (0.0075, 0.0125),
                "spending": (0.03, 0.07),
                "db": (0.0075, 0.0125),
                "income": (0.0075, 0.0125),
            },
        )
        for row in result["run_diagnostics"]:
            self.assertGreaterEqual(row["DC volatility"], 0.04)
            self.assertLessEqual(row["DC volatility"], 0.06)
            self.assertGreaterEqual(row["Spending volatility"], 0.03)
            self.assertLessEqual(row["Spending volatility"], 0.07)
        self.assertLess(
            result["run_diagnostics"][0]["P1 DC growth min"],
            result["run_diagnostics"][0]["P1 DC growth max"],
        )

    def test_occasional_costs_are_optional_and_inflation_linked(self):
        """A guaranteed cost is charged once in its selected year path.

        The event model must remain disabled for legacy callers, and an
        enabled cost must increase the spending requirement without becoming
        a recurring annual charge.
        """
        _seed()
        no_cost_household = _minimal_household()
        no_cost_household.person1.age = 65.0
        no_cost_household.person1.retirement_age = 60.0
        no_cost_household.person1.dc_pot = 100_000.0
        no_cost = monte_carlo_simulation(
            no_cost_household,
            runs=1,
            years=4,
            volatility_ranges={key: (0.0, 0.0) for key in (
                "dc", "isa_gia", "property", "cash", "inflation",
                "spending", "db", "income",
            )},
        )

        _seed()
        cost_household = _minimal_household()
        cost_household.person1.age = 65.0
        cost_household.person1.retirement_age = 60.0
        cost_household.person1.dc_pot = 100_000.0
        with_cost = monte_carlo_simulation(
            cost_household,
            runs=1,
            years=4,
            volatility_ranges={key: (0.0, 0.0) for key in (
                "dc", "isa_gia", "property", "cash", "inflation",
                "spending", "db", "income",
            )},
            occasional_costs={
                "house": {
                    "enabled": True,
                    "probability": (1.0, 1.0),
                    "amount": (1_000.0, 1_000.0),
                },
            },
        )

        costs = with_cost["run_diagnostics"][0]
        self.assertEqual(costs["Occasional cost events"], 4)
        self.assertLess(
            with_cost["all_paths"][0][-1],
            no_cost["all_paths"][0][-1],
        )
        self.assertEqual(with_cost["failure_years"], [None])
        self.assertAlmostEqual(
            with_cost["run_diagnostics"][0]["Occasional costs mean"],
            1_000.0,
            delta=100.0,
        )
        self.assertAlmostEqual(
            with_cost["run_diagnostics"][0]["Occasional costs max"],
            1_000.0 * 1.025 ** 3,
            delta=100.0,
        )

    def test_occasional_costs_do_not_apply_before_retirement(self):
        """Working-life years do not receive retirement repair costs."""
        _seed()
        household = _minimal_household()
        result = monte_carlo_simulation(
            household,
            runs=1,
            years=4,
            volatility_ranges={key: (0.0, 0.0) for key in (
                "dc", "isa_gia", "property", "cash", "inflation",
                "spending", "db", "income",
            )},
            occasional_costs={
                "car": {
                    "enabled": True,
                    "probability": (1.0, 1.0),
                    "amount": (2_000.0, 2_000.0),
                },
            },
        )
        self.assertEqual(
            result["run_diagnostics"][0]["Occasional cost events"],
            0,
        )
        self.assertEqual(result["run_diagnostics"][0]["Occasional costs mean"], 0.0)

    def test_first_year_dc_shock_is_one_off_and_range_is_honoured(self):
        """A fixed 20% shock reduces the opening DC pot once, rather
        than reducing it by 20% in every simulated year."""
        _seed()
        no_shock_household = _minimal_household()
        no_shock_household.person1.dc_pot = 100_000.0
        no_shock = monte_carlo_simulation(
            no_shock_household,
            runs=1,
            years=5,
            volatility_ranges={key: (0.0, 0.0) for key in (
                "dc", "isa_gia", "property", "cash", "inflation",
                "spending", "db", "income",
            )},
            first_year_dc_shock_range=(0.0, 0.0),
        )
        _seed()
        with_shock_household = _minimal_household()
        with_shock_household.person1.dc_pot = 100_000.0
        with_shock = monte_carlo_simulation(
            with_shock_household,
            runs=1,
            years=5,
            volatility_ranges={key: (0.0, 0.0) for key in (
                "dc", "isa_gia", "property", "cash", "inflation",
                "spending", "db", "income",
            )},
            first_year_dc_shock_range=(0.20, 0.20),
        )
        self.assertAlmostEqual(
            with_shock["run_diagnostics"][0]["First-year DC shock"],
            0.20,
        )
        self.assertLess(
            with_shock["all_paths"][0][-1],
            no_shock["all_paths"][0][-1],
        )
        # The source household is not modified by either MC run.
        self.assertEqual(_minimal_household().person1.dc_pot, 0.0)


if __name__ == "__main__":
    unittest.main()
