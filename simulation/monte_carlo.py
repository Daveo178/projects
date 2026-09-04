"""Monte Carlo simulation with optional today's-money output.

The stochastic engine runs each path in nominal pounds so sampled market
returns and sampled inflation are not double-adjusted. Monetary tax thresholds
are indexed by each path's cumulative inflation, avoiding artificial fiscal
drag in nominal paths. When the caller asks for today's-money output, the
completed path is converted component-by-component using that path's
cumulative inflation:

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
from .spending import (
    apply_late_life_spending_reductions,
    spending_for_age,
)

# -----------------------------
# Monte Carlo configuration
# -----------------------------

# Standard deviation used around the user's pension growth-rate inputs when
# the MC samples year-by-year values. DC gets the most dispersion (markets
# are volatile). DB payments are assumed guaranteed by default: the saved
# DB indexation rate is used without annual noise unless the user explicitly
# selects a non-zero DB volatility range. State Pension has no dispersion of
# its own; it is indexed to that run's sampled inflation path
# (triple-lock-style behaviour), which also keeps it flat in today's-value
# mode.
DC_RATE_MC_STD = 0.05
DB_RATE_MC_STD = 0.0
INCOME_RATE_MC_STD = 0.01  # Wage inflation volatility.

# Floor applied to each sampled DC growth year. With std=0.05 around a
# default user mean of 0.05, ~16% of sampled years would otherwise be
# non-positive and over a 30–45-year horizon the DC pot would collapse.
# Capping single-year drawdown at -30% bounds the worst case while keeping
# realistic equity-crash scenarios in the distribution tail.
DC_RATE_FLOOR = -0.30

DEFAULT_RUNS = 1000

# Optional one-off early-retirement stress range. It is off in the balanced
# baseline because ordinary annual DC volatility already includes first-year
# market risk. Users can enable it for a deliberately harsher sequence test.
DEFAULT_FIRST_YEAR_DC_SHOCK_RANGE = (0.0, 0.0)

# Occasional-cost defaults are deliberately conservative planning prompts,
# rather than forecasts. Each category's probability is per year and its
# amount is a today-money range; an occurrence is inflation-linked in the
# nominal MC path and charged in addition to the selected spending plan.
DEFAULT_OCCASIONAL_COSTS = {
    "house": {"label": "House repairs", "probability": (0.03, 0.07), "amount": (5_000.0, 25_000.0)},
    "car": {"label": "Car replacement / major repairs", "probability": (0.08, 0.15), "amount": (8_000.0, 30_000.0)},            "major": {"label": "Major one-off costs", "probability": (0.01, 0.03), "amount": (10_000.0, 50_000.0)},
}

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

# Suggested UI ranges for the standard deviations used by each stochastic
# impact. The midpoint of each range is based on the original model
# assumptions; the bounds let users decide how much uncertainty to include.
# These are expressed as decimals (0.05 = 5 percentage points).
DEFAULT_VOLATILITY_RANGES = {
    "dc": (0.06, 0.09),
    "isa_gia": (0.06, 0.09),
    "property": (0.03, 0.06),
    "cash": (0.0025, 0.0075),
    "inflation": (0.0075, 0.015),
    # Annual spending variability is off for the balanced baseline. Users can
    # enable it as a lifestyle-uncertainty stress test; occasional repairs
    # and replacements have a separate event-based model below.
    "spending": (0.0, 0.0),
    # DB pension payments are guaranteed in the baseline. Set a non-zero
    # range on the Monte Carlo page only to stress the scheme's indexation
    # assumption; the saved DB amount itself is never randomly reduced.
    "db": (0.0, 0.0),
    "income": (0.0075, 0.015),
}


def _normalise_range(value, fallback):
    """Return a finite, ordered ``(low, high)`` decimal range."""
    try:
        low, high = value
        low, high = float(low), float(high)
    except (TypeError, ValueError):
        return fallback
    if not np.isfinite(low) or not np.isfinite(high):
        return fallback
    return max(0.0, min(low, high)), max(0.0, max(low, high))


def _resolve_volatility_ranges(volatility_ranges):
    """Resolve caller-supplied volatility bounds with legacy fallbacks."""
    legacy = {
        "dc": (DC_RATE_MC_STD, DC_RATE_MC_STD),
        "isa_gia": (RETURN_ASSUMPTIONS["ISA"][1], RETURN_ASSUMPTIONS["ISA"][1]),
        "property": (RETURN_ASSUMPTIONS["Property"][1], RETURN_ASSUMPTIONS["Property"][1]),
        "cash": (RETURN_ASSUMPTIONS["Cash"][1], RETURN_ASSUMPTIONS["Cash"][1]),
        "inflation": (INFLATION_STD, INFLATION_STD),
        "spending": (SPENDING_SHOCK_STD, SPENDING_SHOCK_STD),
        "db": (DB_RATE_MC_STD, DB_RATE_MC_STD),
        "income": (INCOME_RATE_MC_STD, INCOME_RATE_MC_STD),
    }
    supplied = volatility_ranges or {}
    return {
        key: _normalise_range(supplied.get(key), fallback)
        for key, fallback in legacy.items()
    }


def _sample_volatilities(volatility_ranges):
    """Choose one SD for each impact for the current simulation run."""
    return {
        key: float(np.random.uniform(low, high))
        for key, (low, high) in volatility_ranges.items()
    }


def _sample_occasional_costs(
    run_years,
    inflation_path,
    retirement_offsets,
    occasional_costs,
):
    """Sample one-off retirement costs for a single nominal MC path.

    Each enabled category can produce at most one event per year. Its
    occurrence probability is sampled once per run from the configured range;
    each occurrence then receives a fresh amount from that category's range.
    Costs are expressed in today's pounds and inflated by the path's
    cumulative inflation. ``retirement_offsets`` starts the model when the
    first partner retires, so working-life expenses are unaffected.
    """
    cumulative_inflation = np.cumprod(1.0 + np.asarray(inflation_path))
    post_retirement = np.arange(run_years) >= max(
        0.0,
        min(retirement_offsets),
    )
    cost_path = np.zeros(run_years)
    events = []
    for key, settings in occasional_costs.items():
        if not settings["enabled"]:
            continue
        probability_low, probability_high = settings["probability"]
        amount_low, amount_high = settings["amount"]
        probability = float(np.random.uniform(probability_low, probability_high))
        occurrence = (
            np.random.random(run_years) < probability
        ) & post_retirement
        amounts = np.random.uniform(amount_low, amount_high, run_years)
        nominal_costs = amounts * cumulative_inflation
        cost_path += occurrence * nominal_costs
        for year, happened in enumerate(occurrence):
            if happened:
                events.append({
                    "year": year,
                    "category": key,
                    "amount": float(nominal_costs[year]),
                })
    return cost_path, events


def randomised_growth_rates(asset_means=None, volatility_by_type=None):
    """Generate one stochastic nominal growth rate per asset class.

    ``asset_means`` comes from the household being simulated. Keeping the
    stochastic spread here while taking the mean from the household makes
    scenario controls (notably What-If's investment-growth slider) affect
    Monte Carlo as well as the deterministic projection. Hard-coded means
    remain fallbacks for asset classes absent from a legacy household.
    """
    asset_means = asset_means or {}
    volatility_by_type = volatility_by_type or {}
    rates = {}
    for asset_type, (fallback_mean, std) in RETURN_ASSUMPTIONS.items():
        mean = asset_means.get(asset_type, fallback_mean)
        rates[asset_type] = np.random.normal(
            mean,
            volatility_by_type.get(asset_type, std),
        )
    return rates


def _resolve_horizon(household, years):
    """Resolve the MC horizon using the engine's joint-life convention."""
    if years is not None:
        return int(years)
    end_age = float(getattr(household, "life_expectancy_end_age", 95.0))
    p1_age = float(getattr(household.person1, "age", 55.0))
    p2_age = float(getattr(household.person2, "age", 55.0))
    remaining_years = [int(round(end_age - p1_age))]
    if not bool(getattr(household, "single_retiree", False)):
        remaining_years.append(int(round(end_age - p2_age)))
    return max(5, max(remaining_years))


def monte_carlo_simulation(
    household,
    runs=DEFAULT_RUNS,
    years=None,
    *,
    today_value_mode=False,
    volatility_ranges=None,
    first_year_dc_shock_range=(0.0, 0.0),
    occasional_costs=None,
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
    volatility_ranges : dict, optional
        Lower/upper bounds for the standard deviation of each stochastic
        impact. Bounds are sampled once per run. Supported keys are ``dc``,
        ``isa_gia``, ``property``, ``cash``, ``inflation``, ``spending``,
        ``db`` and ``income``. When omitted, legacy fixed standard
        deviations are retained for API compatibility.
    first_year_dc_shock_range : tuple, optional
        Lower/upper percentage drop applied once to both DC pots at the
        beginning of the first simulated year. Values are decimals, so
        ``(0.0, 0.20)`` represents a random 0%–20% first-year shock. Pass
        ``(0.0, 0.0)`` to disable it.
    occasional_costs : dict, optional
        Optional event-based expense settings. Supported categories are
        ``house``, ``car`` and ``major``. Each value may contain ``enabled``,
        ``probability`` and ``amount`` lower/upper decimal ranges. Probability
        is the chance of one event in each year; amount is in today's pounds.
        Occasional costs are disabled when omitted.
    """
    all_paths = []
    failure_years = []
    run_diagnostics = []
    failed_run_rate_rows = []
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
    resolved_volatility_ranges = _resolve_volatility_ranges(
        volatility_ranges
    )
    first_year_shock_low, first_year_shock_high = _normalise_range(
        first_year_dc_shock_range,
        DEFAULT_FIRST_YEAR_DC_SHOCK_RANGE,
    )
    resolved_occasional_costs = {}
    for key, defaults in DEFAULT_OCCASIONAL_COSTS.items():
        supplied = (occasional_costs or {}).get(key, {})
        if not isinstance(supplied, dict):
            supplied = {}
        resolved_occasional_costs[key] = {
            "label": defaults["label"],
            "enabled": bool(supplied.get("enabled", False)),
            "probability": _normalise_range(
                supplied.get("probability"), defaults["probability"]
            ),
            "amount": _normalise_range(
                supplied.get("amount"), defaults["amount"]
            ),
        }

    for run_index in range(runs):
        h = deepcopy(household)

        # Run the internal engine path nominally. The optional today-value
        # conversion is applied after the path completes, using that path's
        # own sampled inflation; this avoids mixing the deterministic
        # household inflation setting with the stochastic MC path. Tax bands
        # are indexed by the same cumulative inflation path so the nominal
        # run does not manufacture fiscal drag merely because future pounds
        # are larger.
        h.show_in_todays_value = False

        # Reset PCLS state for the simulation run
        h.person1.pcls_taken = 0.0
        h.person1.pcls_available = 0.0
        h.person2.pcls_taken = 0.0
        h.person2.pcls_available = 0.0

        # Honour the caller-provided `years` for every run so each path
        # is the same length — the fan chart, percentile bands and
        # best/worst-case paths all share an axis on that assumption.
        # Varied horizons would crash `np.array(all_paths)` with
        # "inhomogeneous shape after 1 dimensions" (1k-run reproduction).
        sampled_volatilities = _sample_volatilities(
            resolved_volatility_ranges
        )
        inflation_path = np.random.normal(
            inflation_mean, sampled_volatilities["inflation"], run_years
        )
        spending_shocks = np.random.normal(
            1.0, sampled_volatilities["spending"], run_years
        )
        asset_volatility_by_type = {
            "ISA": sampled_volatilities["isa_gia"],
            "GIA": sampled_volatilities["isa_gia"],
            "Property": sampled_volatilities["property"],
            "Cash": sampled_volatilities["cash"],
            "DC": sampled_volatilities["dc"],
        }
        growth_paths = [
            randomised_growth_rates(
                asset_means,
                asset_volatility_by_type,
            )
            for _ in range(run_years)
        ]

        # Every growth rate in a run is now sampled PER YEAR, so each
        # simulation year carries its own market return / indexation rate
        # (sequence-of-returns risk) rather than one fixed rate for the
        # whole run. The engine consumes these paths via the person's
        # `*_growth_path` attributes and each asset's `growth_path`.
        #
        # DC: fresh sample every year around the user's mean, floored at
        # `DC_RATE_FLOOR` so a single bad draw cannot collapse the pot over
        # a 30–45-year horizon (see DC_RATE_FLOOR comment).
        # DB: fresh sample every year around the user's mean with optional
        # indexation volatility. The default range is 0%–0% because the DB
        # amount is assumed guaranteed; a user can deliberately add noise
        # to stress the indexation assumption.
        # State Pension: NO separate sampling — it is triple-lock /
        # inflation-linked, so it tracks that run's sampled inflation path
        # exactly. The engine's today's-value transform then keeps it flat
        # in today's-money view, matching the deterministic model.
        # Wage inflation (earned income): a slow-moving planning assumption,
        # so it stays a single per-run rate sampled around the user's input.
        h.person1.dc_growth_path = np.maximum(
            DC_RATE_FLOOR,
            np.random.normal(
                h.person1.dc_growth_rate,
                sampled_volatilities["dc"],
                run_years,
            ),
        ).tolist()
        h.person2.dc_growth_path = np.maximum(
            DC_RATE_FLOOR,
            np.random.normal(
                h.person2.dc_growth_rate,
                sampled_volatilities["dc"],
                run_years,
            ),
        ).tolist()
        h.person1.db_growth_path = np.random.normal(
            h.person1.db_growth_rate,
            sampled_volatilities["db"],
            run_years,
        ).tolist()
        h.person2.db_growth_path = np.random.normal(
            h.person2.db_growth_rate,
            sampled_volatilities["db"],
            run_years,
        ).tolist()
        h.person1.state_pension_growth_path = inflation_path.tolist()
        h.person2.state_pension_growth_path = inflation_path.tolist()
        h.person1.income_growth_rate = np.random.normal(
            h.person1.income_growth_rate, sampled_volatilities["income"]
        )
        h.person2.income_growth_rate = np.random.normal(
            h.person2.income_growth_rate, sampled_volatilities["income"]
        )

        # Apply the one-off first-year DC shock before year 0's normal
        # investment growth. It is sampled per run, not repeated annually.
        first_year_dc_shock = float(
            np.random.uniform(first_year_shock_low, first_year_shock_high)
        )
        h.person1.dc_pot *= 1.0 - first_year_dc_shock
        if not bool(getattr(h, "single_retiree", False)):
            h.person2.dc_pot *= 1.0 - first_year_dc_shock

        # Always simulate the same nominal stochastic path in both display
        # modes. Today's-value mode is a presentation conversion below; it
        # must not change property cashflows (especially downsizing
        # proceeds) or the success outcome.
        for asset in h.assets:
            asset.growth_path = [
                growth_paths[year][asset.asset_type]
                for year in range(run_years)
            ]

        base_spending = h.spending_target
        cumulative_inflation = np.cumprod(1.0 + inflation_path)

        # Pension amounts in the plan are today's-money starting amounts.
        # A nominal MC path must therefore uplift a pension before its
        # payment starts, just as it uplifts the spending phases. Without
        # this, a DB pension or State Pension beginning at age 60/67 is
        # incorrectly paid at its today's-money amount in future pounds,
        # creating an artificial shortfall in the 60s–90s. In today's-money
        # display mode the completed wealth path is deflated again, so the
        # same nominal cash-flow treatment remains currency-consistent.
        def _start_date_inflation_factor(start_age):
            offset = max(0, int(round(float(start_age) - h.person1.age)))
            if offset == 0:
                return 1.0
            return float(cumulative_inflation[min(offset - 1, run_years - 1)])

        h.person1.db_base_factor = _start_date_inflation_factor(
            h.person1.draw_age
        )
        h.person2.db_base_factor = _start_date_inflation_factor(
            h.person2.draw_age
        )
        h.person1.state_pension_base_factor = _start_date_inflation_factor(
            h.person1.state_pension_age
        )
        h.person2.state_pension_base_factor = _start_date_inflation_factor(
            h.person2.state_pension_age
        )

        # Generate enabled retirement-cost categories once for this path.
        # The first partner's retirement opens the household's retirement
        # spending window, matching the engine's `any_retired` drawdown gate.
        retirement_offsets = [
            h.person1.retirement_age - h.person1.age,
        ]
        if not bool(getattr(h, "single_retiree", False)):
            retirement_offsets.append(
                h.person2.retirement_age - h.person2.age
            )
        occasional_cost_path, occasional_cost_events = _sample_occasional_costs(
            run_years,
            inflation_path,
            retirement_offsets,
            resolved_occasional_costs,
        )
        # Tax allowances and bands are monetary thresholds. Index them by
        # the same path-specific cumulative inflation used for nominal
        # pensions and spending, otherwise the nominal MC path introduces
        # fiscal drag that is absent from the deterministic today's-money
        # projection. This path is consumed by the engine for each year.
        h.tax_band_factor_path = cumulative_inflation.tolist()
        strategy = getattr(h, "drawdown_strategy", "Fixed")
        # Keep this path attached for every strategy, including Safe
        # Withdrawal. The engine adds it after resolving the base target.
        h.occasional_cost_path = occasional_cost_path.tolist()
        if strategy == "Safe Withdrawal (4%)":
            h.spending_target_path = None
        else:
            spending_path = []
            for year in range(run_years):
                # Build the nominal equivalent of the selected strategy.
                # The engine consumes this optional path in preference to
                # its deterministic inflation formula.
                if strategy == "Spending phases":
                    # Phase amounts are real/today's-money figures. MC runs
                    # internally in nominal pounds, so apply each path's
                    # sampled cumulative inflation after selecting the age
                    # band, then apply the existing spending shock.
                    base = spending_for_age(
                        h.person1.age + year,
                        getattr(h, "spending_phases", []),
                        fallback_spending=base_spending,
                    ) * cumulative_inflation[year]
                else:
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
        # The engine's `income` series is the actual annual wallet fill:
        # earned income + DB/State Pension + successful pension/asset
        # drawdown. Therefore a run fails only when the engine cannot meet
        # that year's spending requirement. Property is intentionally not
        # part of this test; it is not assumed to be sold.
        spending_path_result = np.asarray(
            results.get("spending", [0.0] * run_years), dtype=float
        )
        income_path_result = np.asarray(
            results.get("income", [0.0] * run_years), dtype=float
        )
        failure_year = None
        for y, (income, spending) in enumerate(
            zip(income_path_result, spending_path_result)
        ):
            if income + 1e-6 < spending:
                failure_year = y
                break
        failure_years.append(failure_year)

        # Keep exact annual rates for failed paths only. This makes a failed
        # run reproducible for inspection without multiplying memory use by
        # the full number of successful paths.
        if failure_year is not None:
            for year, growth_path in enumerate(growth_paths):
                failed_run_rate_rows.append({
                    "Run": run_index + 1,
                    "Year": year,
                    "Age": float(h.person1.age + year),
                    "Failure year": failure_year,
                    "Inflation": float(inflation_path[year]),
                    "Spending shock": float(spending_shocks[year]),
                    "Occasional costs": float(occasional_cost_path[year]),
                    "First-year DC shock": first_year_dc_shock,
                    "ISA return": float(growth_path["ISA"]),
                    "GIA return": float(growth_path["GIA"]),
                    "Cash return": float(growth_path["Cash"]),
                    "Property return": float(growth_path["Property"]),
                    "P1 DC growth": float(h.person1.dc_growth_path[year]),
                    "P2 DC growth": float(h.person2.dc_growth_path[year]),
                    "P1 DB growth": float(h.person1.db_growth_path[year]),
                    "P2 DB growth": float(h.person2.db_growth_path[year]),
                    "P1 State Pension growth": float(
                        h.person1.state_pension_growth_path[year]
                    ),
                    "P2 State Pension growth": float(
                        h.person2.state_pension_growth_path[year]
                    ),
                    "P1 income growth": float(h.person1.income_growth_rate),
                    "P2 income growth": float(h.person2.income_growth_rate),
                })

        # Keep one compact diagnostic row per simulation. This makes it
        # possible to inspect the assumptions behind a failed run without
        # forcing the UI to render every annual rate for every path.
        def _path_stats(values):
            values = np.asarray(values, dtype=float)
            return float(np.mean(values)), float(np.min(values)), float(np.max(values))

        inflation_stats = _path_stats(inflation_path)
        spending_stats = _path_stats(spending_shocks)
        occasional_cost_stats = _path_stats(occasional_cost_path)
        asset_stats = {
            asset_type: _path_stats(
                [growth_path.get(asset_type, np.nan) for growth_path in growth_paths]
            )
            for asset_type in ("ISA", "GIA", "Cash", "Property")
        }
        # Pension-style rates are now per-year paths, so the per-run
        # diagnostic reports their mean/min/max across the run's years
        # (same shape as the asset-return columns). Wage inflation stays a
        # single per-run value (it is sampled once per run).
        dc1_stats = _path_stats(h.person1.dc_growth_path)
        dc2_stats = _path_stats(h.person2.dc_growth_path)
        db1_stats = _path_stats(h.person1.db_growth_path)
        db2_stats = _path_stats(h.person2.db_growth_path)
        sp1_stats = _path_stats(h.person1.state_pension_growth_path)
        sp2_stats = _path_stats(h.person2.state_pension_growth_path)
        run_diagnostics.append({
            "Run": run_index + 1,
            "Outcome": "Failed" if failure_year is not None else "Succeeded",
            "Failure year": failure_year,
            "Failure age": (
                float(h.person1.age + failure_year)
                if failure_year is not None
                else None
            ),
            "P1 DC growth": dc1_stats[0],
            "P1 DC growth min": dc1_stats[1],
            "P1 DC growth max": dc1_stats[2],
            "P2 DC growth": dc2_stats[0],
            "P2 DC growth min": dc2_stats[1],
            "P2 DC growth max": dc2_stats[2],
            "P1 DB growth": db1_stats[0],
            "P1 DB growth min": db1_stats[1],
            "P1 DB growth max": db1_stats[2],
            "P2 DB growth": db2_stats[0],
            "P2 DB growth min": db2_stats[1],
            "P2 DB growth max": db2_stats[2],
            "P1 State Pension growth": sp1_stats[0],
            "P1 State Pension growth min": sp1_stats[1],
            "P1 State Pension growth max": sp1_stats[2],
            "P2 State Pension growth": sp2_stats[0],
            "P2 State Pension growth min": sp2_stats[1],
            "P2 State Pension growth max": sp2_stats[2],
            "P1 income growth": float(h.person1.income_growth_rate),
            "P2 income growth": float(h.person2.income_growth_rate),
            "Inflation mean": inflation_stats[0],
            "Inflation min": inflation_stats[1],
            "Inflation max": inflation_stats[2],
            "Spending shock mean": spending_stats[0],
            "Spending shock min": spending_stats[1],
            "Spending shock max": spending_stats[2],
            "Occasional costs mean": occasional_cost_stats[0],
            "Occasional costs max": occasional_cost_stats[2],
            "Occasional cost events": len(occasional_cost_events),
            "First-year DC shock": first_year_dc_shock,
            "DC volatility": sampled_volatilities["dc"],
            "ISA/GIA volatility": sampled_volatilities["isa_gia"],
            "Property volatility": sampled_volatilities["property"],
            "Cash volatility": sampled_volatilities["cash"],
            "Inflation volatility": sampled_volatilities["inflation"],
            "Spending volatility": sampled_volatilities["spending"],
            "DB volatility": sampled_volatilities["db"],
            "Income volatility": sampled_volatilities["income"],
            "ISA return mean": asset_stats["ISA"][0],
            "ISA return min": asset_stats["ISA"][1],
            "ISA return max": asset_stats["ISA"][2],
            "GIA return mean": asset_stats["GIA"][0],
            "GIA return min": asset_stats["GIA"][1],
            "GIA return max": asset_stats["GIA"][2],
            "Cash return mean": asset_stats["Cash"][0],
            "Cash return min": asset_stats["Cash"][1],
            "Cash return max": asset_stats["Cash"][2],
            "Property return mean": asset_stats["Property"][0],
            "Property return min": asset_stats["Property"][1],
            "Property return max": asset_stats["Property"][2],
        })

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
        "run_diagnostics": run_diagnostics,
        "failed_run_rate_rows": failed_run_rate_rows,
    }
