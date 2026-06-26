import numpy as np
from copy import deepcopy
from .engine import run_simulation
from .longevity import sample_longevity

# -----------------------------
# Monte Carlo configuration
# -----------------------------

# Simple 60/40-style glide path for DC (SIPP)
DC_GLIDE_YEARS = 20  # years before retirement over which we de-risk

def dc_glidepath_return(person, year_index):
    """
    Generate a DC return for this year using a glide path:
    - Higher equity exposure far from retirement
    - More bond-like near and after retirement
    """
    current_age = person.age + year_index
    retirement_age = person.retirement_age

    years_to_ret = retirement_age - current_age
    years_to_ret = max(0, years_to_ret)

    # 1 = far from retirement (more equity), 0 = at/after retirement (more bonds)
    weight_equity = min(DC_GLIDE_YEARS, years_to_ret) / DC_GLIDE_YEARS

    # Equity-like parameters
    equity_mean = 0.07
    equity_std = 0.15

    # Bond-like parameters
    bond_mean = 0.02
    bond_std = 0.05

    mean = weight_equity * equity_mean + (1 - weight_equity) * bond_mean
    std = weight_equity * equity_std + (1 - weight_equity) * bond_std

    return np.random.normal(mean, std)

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
    lifetimes = []

    for _ in range(runs):
        h = deepcopy(household)

        # Reset PCLS state for the simulation run
        h.person1.pcls_taken = 0.0
        h.person1.pcls_available = 0.0
        h.person2.pcls_taken = 0.0
        h.person2.pcls_available = 0.0

        run_years = sample_longevity(base_years=years, std_years=5)
        lifetimes.append(run_years)

        inflation_path = np.random.normal(INFLATION_MEAN, INFLATION_STD, run_years)
        spending_shocks = np.random.normal(1.0, SPENDING_SHOCK_STD, run_years)
        growth_paths = [randomised_growth_rates() for _ in range(run_years)]

        for year in range(run_years):
            for asset in h.assets:
                asset.growth_rate = growth_paths[year][asset.asset_type]
        
        # 2. Apply randomised growth to DC pots (THIS is the new code)
        dc_growth = dc_glidepath_return(h.person1, year)
        h.person1.dc_pot *= (1 + dc_growth)
        h.person2.dc_pot *= (1 + dc_growth)
        
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
        "lifetimes": lifetimes,
        "all_paths": all_paths.tolist()
    }
