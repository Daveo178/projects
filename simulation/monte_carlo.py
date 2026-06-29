import numpy as np
from copy import deepcopy
from .engine import run_simulation

# -----------------------------
# Monte Carlo configuration
# -----------------------------

# Standard deviation used around the user's pension growth-rate inputs when
# the MC samples per-run values. DC gets the most dispersion (markets are
# vol); DB and State Pension indexation are tied to inflation / triple-lock
# policy and have far less dispersion.
DC_RATE_MC_STD = 0.05
DB_RATE_MC_STD = 0.01
SP_RATE_MC_STD = 0.01
INCOME_RATE_MC_STD = 0.01  # Wage inflation volatility — same magnitude as DB / SP indexation.

# Floor applied to the sampled DC growth rate per MC run. With std=0.05
# around a default user mean of 0.05, ~16% of runs would otherwise sample
# a non-positive DC rate and over a 30–45-year horizon the DC pot would
# collapse. Capping single-year drawdown at -30% bounds the worst case
# while keeping realistic equity-crash scenarios in the distribution tail.
DC_RATE_FLOOR = -0.30

DEFAULT_RUNS = 1000

# Annual return assumptions (mean, stdev)
RETURN_ASSUMPTIONS = {
    "ISA": (0.05, 0.10),
    "GIA": (0.05, 0.10),
    "DC":  (0.05, 0.10),
    "Property": (0.02, 0.05),
    "Cash": (0.01, 0.01)
}

# Inflation assumptions
INFLATION_MEAN = 0.025
INFLATION_STD = 0.01

# Spending shock assumptions
SPENDING_SHOCK_STD = 0.05  # ±5% random variation


def randomised_growth_rates():
    """
    Generate a randomised growth rate for each asset class.
    """
    rates = {}
    for asset_type, (mean, std) in RETURN_ASSUMPTIONS.items():
        rates[asset_type] = np.random.normal(mean, std)
    return rates


def monte_carlo_simulation(household, runs=DEFAULT_RUNS, years=45):
    all_paths = []
    failure_years = []

    for _ in range(runs):
        h = deepcopy(household)

        # Reset PCLS state for the simulation run
        h.person1.pcls_taken = 0.0
        h.person1.pcls_available = 0.0
        h.person2.pcls_taken = 0.0
        h.person2.pcls_available = 0.0

        # Sample pension growth rates PER RUN around the user's mean input.
        # Per-person rates can diverge (different scheme rules) so we sample
        # each partner separately, but the spread is small for DB / State
        # Pension (inflation-linked) and larger for DC (market vol). DC is
        # floored at `DC_RATE_FLOOR` to avoid runaway compounding of negative
        # samples over a 30–45-year horizon (see DC_RATE_FLOOR comment).
        h.person1.dc_growth_rate = max(
            DC_RATE_FLOOR,
            np.random.normal(h.person1.dc_growth_rate, DC_RATE_MC_STD),
        )
        h.person2.dc_growth_rate = max(
            DC_RATE_FLOOR,
            np.random.normal(h.person2.dc_growth_rate, DC_RATE_MC_STD),
        )
        h.person1.db_growth_rate = np.random.normal(
            h.person1.db_growth_rate, DB_RATE_MC_STD
        )
        h.person2.db_growth_rate = np.random.normal(
            h.person2.db_growth_rate, DB_RATE_MC_STD
        )
        h.person1.state_pension_growth_rate = np.random.normal(
            h.person1.state_pension_growth_rate, SP_RATE_MC_STD
        )
        h.person2.state_pension_growth_rate = np.random.normal(
            h.person2.state_pension_growth_rate, SP_RATE_MC_STD
        )
        # Wage-inflation indexed earned income — sampled per-partner with the
        # same dispersion as DB / SP (both are inflation-policy linked).
        h.person1.income_growth_rate = np.random.normal(
            h.person1.income_growth_rate, INCOME_RATE_MC_STD
        )
        h.person2.income_growth_rate = np.random.normal(
            h.person2.income_growth_rate, INCOME_RATE_MC_STD
        )

        # Honour the caller-provided `years` for every run so each path
        # is the same length — the fan chart, percentile bands and
        # best/worst-case paths all share an axis on that assumption.
        # Varied horizons would crash `np.array(all_paths)` with
        # "inhomogeneous shape after 1 dimensions" (1k-run reproduction).
        run_years = years

        inflation_path = np.random.normal(INFLATION_MEAN, INFLATION_STD, run_years)
        spending_shocks = np.random.normal(1.0, SPENDING_SHOCK_STD, run_years)
        growth_paths = [randomised_growth_rates() for _ in range(run_years)]

        for year in range(run_years):
            for asset in h.assets:
                asset.growth_rate = growth_paths[year][asset.asset_type]

        base_spending = h.spending_target
        h.spending_target_path = [
            base_spending * (1 + inflation_path[y]) * spending_shocks[y]
            for y in range(run_years)
        ]

        results = run_simulation(h, years=run_years)
        all_paths.append(results["net_worth"])

        failure_year = None
        for y, nw in enumerate(results["net_worth"]):
            if nw <= 0:
                failure_year = y
                break
        failure_years.append(failure_year)

    all_paths = np.array(all_paths)

    percentiles = {
        "p10": np.percentile(all_paths, 10, axis=0).tolist(),
        "p25": np.percentile(all_paths, 25, axis=0).tolist(),
        "p50": np.percentile(all_paths, 50, axis=0).tolist(),
        "p75": np.percentile(all_paths, 75, axis=0).tolist(),
        "p90": np.percentile(all_paths, 90, axis=0).tolist(),
    }

    success_rate = sum(f is None for f in failure_years) / runs

    return {
        "percentiles": percentiles,
        "success_rate": success_rate,
        "failure_years": failure_years,
        "all_paths": all_paths.tolist(),
    }
