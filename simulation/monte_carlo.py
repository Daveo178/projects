"""Monte Carlo simulation with optional today's-money output.

The stochastic engine runs each path in nominal pounds so sampled market
returns and sampled inflation are not double-adjusted. When the caller asks
for today's-money output, the completed path is converted component-by-
component using that path's cumulative inflation:

* DC, ISA, GIA, Cash and Property are deflated by cumulative sampled
  inflation so the displayed wealth is in one consistent real-terms basis.
* Mortgage balance is left unchanged, matching the deterministic model's
  treatment of mortgage interest as a real liability rate.
* Success/failure is always evaluated on the raw nominal cash-flow path,
  because a display-currency conversion must not change whether a plan
  actually runs out of money.

This gives the Monte Carlo page a currency basis consistent with Quick
Estimate while preserving the stochastic nominal simulation internally.
"""

import numpy as np
from copy import deepcopy
from .engine import run_simulation
from .spending import apply_late_life_spending_reductions

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


def randomised_growth_rates(asset_means=None):
    """Generate one stochastic nominal growth rate per asset class.

    ``asset_means`` comes from the household being simulated. Keeping the
    stochastic spread here while taking the mean from the household makes
    scenario controls (notably What-If's investment-growth slider) affect
    Monte Carlo as well as the deterministic projection. Hard-coded means
    remain fallbacks for asset classes absent from a legacy household.
    """
    asset_means = asset_means or {}
    rates = {}
    for asset_type, (fallback_mean, std) in RETURN_ASSUMPTIONS.items():
        mean = asset_means.get(asset_type, fallback_mean)
        rates[asset_type] = np.random.normal(mean, std)
    return rates


def _resolve_horizon(household, years):
    """Resolve the MC horizon using the engine's joint-life convention."""
    if years is not None:
        return int(years)
    end_age = float(getattr(household, "life_expectancy_end_age", 95.0))
    p1_age = float(getattr(household.person1, "age", 55.0))
    p2_age = float(getattr(household.person2, "age", 55.0))
    return max(
        5,
        max(
            int(round(end_age - p1_age)),
            int(round(end_age - p2_age)),
        ),
    )


def monte_carlo_simulation(
    household,
    runs=DEFAULT_RUNS,
    years=None,
    *,
    today_value_mode=False,
):
    """Run `runs` MC paths and return percentile bands of net worth.

    Parameters
    ----------
    household : Household
        Source plan. Each stochastic iteration runs nominally internally.
    runs : int, optional
        Number of MC paths to simulate. Default 1000.
    years : int, optional
        Horizon length. Every path uses this same length. When omitted,
        resolve the household's joint-life horizon using the same
        ``life_expectancy_end_age`` convention as ``run_simulation``.
    today_value_mode : bool, optional
        If true, convert each completed nominal path to today's money using
        its own sampled cumulative inflation path. Defaults to false so
        existing callers (including What-If) retain nominal MC output.
    """
    all_paths = []
    failure_years = []
    run_years = _resolve_horizon(household, years)
    asset_means = {}
    for asset in household.assets:
        # The engine stores assets as a list. For the normal one-row-per-
        # wrapper shape this is exact; retain the first value as the
        # class-level stochastic mean for legacy duplicate rows.
        asset_means.setdefault(asset.asset_type, float(asset.growth_rate))
    inflation_mean = float(
        getattr(household, "inflation_rate", INFLATION_MEAN)
    )

    for _ in range(runs):
        h = deepcopy(household)

        # Run the internal engine path nominally. The optional today-value
        # conversion is applied after the path completes, using that path's
        # own sampled inflation; this avoids mixing the deterministic
        # household inflation setting with the stochastic MC path.
        h.show_in_todays_value = False

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
        inflation_path = np.random.normal(
            inflation_mean, INFLATION_STD, run_years
        )
        spending_shocks = np.random.normal(1.0, SPENDING_SHOCK_STD, run_years)
        growth_paths = [
            randomised_growth_rates(asset_means)
            for _ in range(run_years)
        ]

        for year in range(run_years):
            for asset in h.assets:
                # Always simulate the same nominal stochastic path in both
                # display modes. Today's-value mode is a presentation
                # conversion below; it must not change property cashflows
                # (especially downsizing proceeds) or the success outcome.
                asset.growth_rate = growth_paths[year][asset.asset_type]

        base_spending = h.spending_target
        cumulative_inflation = np.cumprod(1.0 + inflation_path)
        strategy = getattr(h, "drawdown_strategy", "Fixed")
        if strategy == "Safe Withdrawal (4%)":
            h.spending_target_path = None
        else:
            spending_path = []
            for year in range(run_years):
                # Build the nominal equivalent of the selected strategy.
                # The engine consumes this optional path in preference to
                # its deterministic inflation formula.
                base = base_spending * cumulative_inflation[year]
                if strategy == "Tapered (down with age)":
                    age = h.person1.age + year
                    years_to_retirement = max(
                        0.0,
                        h.person1.retirement_age - h.person1.age,
                    )
                    if year < years_to_retirement:
                        factor = 1.0
                    elif age < getattr(h, "taper_start_age", 75.0):
                        years_into_retirement = max(
                            0.0, year - years_to_retirement
                        )
                        factor = (
                            1.0 + getattr(h, "gogo_bump_pct", 0.0) / 100.0
                        ) ** years_into_retirement
                    else:
                        peak_years = max(
                            0.0,
                            getattr(h, "taper_start_age", 75.0)
                            - h.person1.retirement_age,
                        )
                        years_past_peak = max(
                            0.0,
                            age - getattr(h, "taper_start_age", 75.0),
                        )
                        factor = (
                            1.0 + getattr(h, "gogo_bump_pct", 0.0) / 100.0
                        ) ** peak_years * (
                            1.0 - getattr(h, "taper_rate", 0.02)
                        ) ** years_past_peak
                    if year >= years_to_retirement:
                        # Keep these explicit reductions post-retirement,
                        # even if hand-edited ages are below retirement.
                        base = apply_late_life_spending_reductions(
                            base * factor,
                            age,
                            step_1_age=getattr(
                                h, "late_life_step_1_age", 75.0
                            ),
                            step_1_rate=getattr(
                                h, "late_life_step_1_rate", 0.0
                            ),
                            step_2_age=getattr(
                                h, "late_life_step_2_age", 85.0
                            ),
                            step_2_rate=getattr(
                                h, "late_life_step_2_rate", 0.0
                            ),
                        )
                    else:
                        base = base * factor
                    base = max(
                        base,
                        getattr(h, "taper_floor_gbp", 10_000.0),
                    )
                spending_path.append(base * spending_shocks[year])
            h.spending_target_path = spending_path

        results = run_simulation(h, years=run_years)
        nominal_path = list(results["net_worth"])
        path = nominal_path
        if today_value_mode:
            # Convert every asset component to today's money. Mortgage is
            # deliberately left unchanged because the deterministic model
            # treats its interest rate as a real liability rate.
            investable = (
                np.asarray(results.get("dc_pot", [0.0] * run_years), dtype=float)
                + np.asarray(results.get("isa_value", [0.0] * run_years), dtype=float)
                + np.asarray(results.get("gia_value", [0.0] * run_years), dtype=float)
                + np.asarray(results.get("cash_value", [0.0] * run_years), dtype=float)
            )
            property_value = np.asarray(
                results.get("property_value", [0.0] * run_years),
                dtype=float,
            )
            mortgage_balance = np.asarray(
                results.get("mortgage_balance", [0.0] * run_years),
                dtype=float,
            )
            path = (
                (investable / cumulative_inflation)
                + (property_value / cumulative_inflation)
                - mortgage_balance
            ).tolist()
        all_paths.append(path)

        # A nominal-vs-real display conversion cannot change whether the
        # underlying cash-flow simulation ran out. Evaluate this invariant
        # on the raw nominal engine output, not on the partially converted
        # chart path (which mixes real assets with the nominal mortgage).
        failure_year = None
        for y, nw in enumerate(nominal_path):
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
