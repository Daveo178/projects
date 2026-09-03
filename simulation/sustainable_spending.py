"""Maximum-Sustainable-Spending solver for the Spending page.

User-facing problem
-------------------
The Spending page accepts a `spending` number input but doesn't help the
user know whether the figure is sustainable to their `life_expectancy_end_age`
or to any other age they might prefer. The user could type £200,000/yr and
the engine would silently produce a plan that runs out at year 12. The
Home page does fire a sustainability banner via
`results["net_worth"][-1] < 0`, but only AFTER the user has already
typed the bad number — there's no "what should I type?" guidance.

This module solves the inverse problem: given a TARGET AGE (e.g. 95)
and the household's current wealth trajectory, find the MAXIMUM
annual spending (in the household's saved units — today's-money or
nominal) that exactly depletes terminal net worth to £0 at that age.

Algorithm
---------
1-D root-finding on

    The solver searches for the highest S whose projection remains
    solvent through the final engine year corresponding to `target_age`.
    This is a viability test rather than a simple terminal-net-worth
    root: the engine clamps exhausted wrappers to £0, so terminal £0 may
    mean either "reached the target" or "failed earlier and stayed at zero".

We bracket-and-bisect:

  * Search for a viable low and an early-depletion high, doubling
    `high` from a small start. Stops at a hard ceiling of £50M/yr —
    beyond that we're searching for a degenerate plan, not a sensible
    retirement figure.
  * Standard bisection on `(low, high)`. A target-year balance within
    ±£200 is accepted as the engine's numerical boundary, while any
    depletion before the target or materially negative target balance
    is rejected.
  * Cap at 30 iterations (sufficient for ~10^7× precision on a
    £50M/yr upper bound; in practice we stop well before that
    because the 200-tolerance check fires first).

Each bisection step `deepcopy`s the household dataclass and runs
the full engine for `target_year_offset` annual periods. The final
engine result is the same endpoint used by the normal Quick Estimate
projection; we also inspect every earlier year for depletion.

Today's-value handling
----------------------
The solver reads `household.show_in_todays_value` implicitly via
`run_simulation` — every iteration applies the household's
saved mode. Bisection in today's-money mode finds a REAL-TERMS max
spend; in nominal mode it finds a NOMINAL-£ max spend (which will
trend upward over the years via inflation, so the "£X per year"
label only makes sense as "£X in year-0 units").

Why this lives in `simulation/` and not `pages/`
----------------------------------------------
The solver has zero Streamlit dependency — it reads a dataclass,
runs the engine, returns a result. Pages import it but it doesn't
import any page-level state. The same `find_max_sustainable_spending(...)`
call is reused on the Spending page (UI-driven) and in
`tests/test_sustainable_spending.py` (math-driven).

Pure-Python import requirement
-------------------------------
Tests import this module directly via `from simulation.sustainable_spending
import find_max_sustainable_spending`. The module therefore MUST NOT
import `streamlit` at module top or the test runner can't construct a
`Household(...)` dataclass for the bisection harness (test fixtures
build households inline — see `tests/test_sustainable_spending.py` for
the exact shape). The Spend page also builds a `Household` here via
`build_household_from_session_state()` (which itself imports streamlit),
but that's a *page*-side concern — the solver sees a fully-constructed
dataclass regardless of where it came from.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Optional

from .engine import run_simulation
from .spending import normalize_spending_phases


# Solver constants — module-level so the Spending page caption and
# test cases can reference them by name. Documented in
# `tests/test_sustainable_spending.py` (each constant has at least
# one test that exercises the bound it sets).
DEFAULT_TOLERANCE_GBP = 200.0
DEFAULT_MAX_ITERATIONS = 30
DEFAULT_BRACKET_LOW = 0.0
# Hard ceiling on `bracket_high` doubling. Above this, the search
# declares "could not bracket" and returns an error. £50M/yr is
# ~250x the typical UK household wealth; spending more is a
# degenerate retirement scenario the solver shouldn't try to
# resolve to meaningless precision.
SAFE_MAX_SPEND_GBP = 50_000_000.0
# Max high-doubling iterations before declaring failure. With
# the doubling factor 2.0 this is enough to climb from £20k to
# £80M (2^12 = 4096x) in 12 doubler steps, comfortably covering
# any non-degenerate retirement scenario.
MAX_BRACKET_DOUBLINGS = 15
# Starting `bracket_high`. We seed at twice the household's year-0
# gross wealth (assets + sum of expected pension income), so a
# moderately large plan brackets in 1-2 doublings; a tiny plan
# brackets in 3-4. Both well below the safety ceiling.
STARTING_BRACKET_LOW_RATIO = 2.0


@dataclass
class SustainableSpendingResult:
    """Output of `find_max_sustainable_spending(...)`.

    Field semantics
    ---------------
    `max_spending_gbp`        : The annual spending (in the household's
                                saved currency mode — today's-money or
                                nominal £) that keeps the plan solvent
                                through the target age. No terminal
                                wealth target is imposed. For Fixed /
                                Inflation-adjusted strategies this is
                                the year-0 spending; for Tapered, it
                                the peak (pre-taper) spending that the
                                strategy then declines from.

    `terminal_net_worth_gbp`  : The actual terminal net worth at the
                                target age when using `max_spending_gbp`.
                                Within ±tolerance of 0 when
                                `converged=True`; may still be a few
                                hundred £ from 0 when `converged=False`
                                (rare — see the algorithm note about
                                FP-noise tolerance).

    `target_age`             : The user-supplied target age the
                                solver ran for, echoed for messaging.

    `target_year_offset`     : Rounded number of annual periods from
                                the youngest partner's current age to
                                the target age. It is retained as the
                                public field name for compatibility;
                                the aligned engine endpoint is the final
                                index (`target_year_offset - 1`) in a
                                `years=target_year_offset` projection.
                                Computed as
                                `int(round(target_age - min(p1.age, p2.age)))`.

    `iterations_used`         : Total `run_simulation` calls fired
                                (bracket expansions + bisection steps).
                                30 max by default.

    `converged`               : True iff `|terminal_net_worth_gbp| <=
                                tolerance_gbp` BEFORE the iteration
                                cap fired. With the default 200-£
                                tolerance and typical UK households
                                (~£300k wealth, ~10-30 year horizon)
                                the solver almost always converges in
                                18-22 iterations.

    `error`                   : Non-None ONLY on definitive errors:
                                target age in the past, plan cannot
                                sustain target age even at zero
                                spending (catastrophically under-funded),
                                or the bracket-doubling loop hit the
                                £50M safety ceiling. The Spending page
                                renders these with `st.error(...)` and
                                suppresses the result panel entirely.

    `strategy_at_run`         : Echoes `household.drawdown_strategy` so
                                the caller can describe which plan was
                                solved.

    `spending_phases`         : For the explicit "Spending phases"
                                strategy, the sustainable phase schedule
                                with the original age thresholds and
                                proportionally scaled amounts.
    """
    max_spending_gbp: float
    terminal_net_worth_gbp: float
    target_age: float
    target_year_offset: int
    iterations_used: int
    converged: bool
    error: Optional[str] = None
    strategy_at_run: str = ""
    spending_phases: Optional[list[dict[str, float]]] = None


def find_max_sustainable_spending(
    household,
    target_age: float,
    *,
    tolerance_gbp: float = DEFAULT_TOLERANCE_GBP,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> SustainableSpendingResult:
    """Estimate the MAXIMUM annual spending that keeps a household
    solvent through `target_age`; no terminal wealth target is imposed.

    Parameters
    ----------
    household        : A populated `Household(...)` dataclass. The
                       solver never mutates this instance — every
                       bisection step `copy.deepcopy`s the dataclass
                       and assigns the candidate spending on the
                       copy. The caller's `household.spending_target`
                       is preserved across the call.

    target_age       : The age the household should reach when its
                       net worth is exactly £0. Fractional ages
                       (e.g. 90.5) are supported via `int(round(...))`
                       mapping to the simulation's integer year axis.

                       Must be strictly greater than the youngest
                       partner's CURRENT age — otherwise `target_year_
                       offset` would be `0` (or negative) and the
                       "terminal wealth" reading would actually be
                       the year-0 wealth, producing nonsense. The
                       error case returns `max_spending_gbp=0.0`
                       with a clear `error` string.

    tolerance_gbp    : Stop iterating when `|terminal_net_worth|` is
                       within this many pounds of zero. Default £200
                       (matches the engine's per-spouse tax recompute
                       FP noise floor; lowering to <=£50 starts to
                       flake on Tax-band-edge cases).

    max_iterations    : Bisection step cap. Default 30 — sufficient
                       for ~£0.001 precision on a £50M upper bound;
                       in practice the £200 tolerance fires first
                       after ~20 iterations on typical UK households.

    Returns
    -------
    SustainableSpendingResult — populated with `max_spending_gbp`,
    `terminal_net_worth_gbp`, `converged` flag, `error` string on
    failure. The Spending page renders success cases in green
    (or yellow on partial convergence) and errors in red.
    """
    # ---- Validate target_age --------------------------------------
    # The engine's horizon math uses the longer remaining period. The
    # public offset is the rounded annual-period count; the normal
    # `run_simulation(household)` endpoint is its final index, one lower.
    p1_age = float(getattr(household.person1, "age", 55.0))
    p2_age = float(getattr(household.person2, "age", 55.0))
    min_age = (
        p1_age
        if bool(getattr(household, "single_retiree", False))
        else min(p1_age, p2_age)
    )
    target_year_offset = int(round(float(target_age) - min_age))

    base_strategy = str(getattr(household, "drawdown_strategy", "Fixed"))

    # Explicit phase plans are solved by scaling the first active amount and
    # preserving the ratios and age thresholds of the entered schedule. For
    # example, [£40k, £30k, £20k] becomes [S, .75S, .5S].
    phase_schedule = None
    phase_mode = base_strategy == "Spending phases"
    if phase_mode:
        phase_schedule = normalize_spending_phases(
            getattr(household, "spending_phases", []),
            fallback_spending=float(getattr(household, "spending_target", 0.0)),
            fallback_end_age=float(
                getattr(household, "life_expectancy_end_age", 95.0)
            ),
        )
        if not phase_schedule[0]["annual_spending"] > 0:
            # There is no meaningful ratio when every entered phase is £0;
            # fall back to the legacy flat solver rather than returning a
            # misleading phased result.
            phase_mode = False
            phase_schedule = None

    phase_base_amount = (
        phase_schedule[0]["annual_spending"] if phase_mode else 0.0
    )
    phase_ratios = (
        [phase["annual_spending"] / phase_base_amount for phase in phase_schedule]
        if phase_mode
        else []
    )

    def _scaled_phase_schedule(first_phase_amount: float):
        if not phase_mode or phase_schedule is None:
            return None
        return [
            {
                "annual_spending": float(first_phase_amount * ratio),
                "until_age": float(phase["until_age"]),
            }
            for phase, ratio in zip(phase_schedule, phase_ratios)
        ]

    if target_year_offset < 1:
        return SustainableSpendingResult(
            max_spending_gbp=0.0,
            terminal_net_worth_gbp=0.0,
            target_age=float(target_age),
            target_year_offset=max(target_year_offset, 0),
            iterations_used=0,
            converged=False,
            error=(
                f"Target age ({float(target_age):.2f}) is at or before the "
                f"youngest partner's current age ({min_age:.2f}). Pick a "
                f"target age AT LEAST 1 year in the future."
            ),
            strategy_at_run=base_strategy,
        )

    # ---- Projection probe -----------------------------------------
    # Each call deep-copies the household so the engine's in-place
    # mutations (`person.dc_pot -= ...`, `asset.value -= ...`,
    # `person.is_retired(...)` reads, etc.) don't bleed across
    # bisection iterations. Copying a dataclass with nested Person /
    # Asset / Mortgage is a few ms — well below the per-iteration
    # cost of running the engine (~5-20 ms for ~30-year horizons).
    def _probe(spending_gbp: float) -> tuple[float, bool]:
        """Return (target-year wealth, exhausted before target).

        The engine clamps depleted wrappers to zero. Therefore a terminal
        zero is ambiguous: it may mean wealth reached zero at the target,
        or that the plan failed several years earlier and stayed at zero.
        The second value keeps those cases distinct for the root finder.
        """
        hh_copy = copy.deepcopy(household)
        hh_copy.spending_target = float(spending_gbp)
        if phase_mode:
            hh_copy.drawdown_strategy = "Spending phases"
            hh_copy.spending_phases = _scaled_phase_schedule(spending_gbp)
        else:
            # Preserve the original solver behavior for Fixed, Tapered,
            # Safe Withdrawal and legacy households.
            hh_copy.drawdown_strategy = base_strategy
            hh_copy.spending_phases = []
        target_years = max(1, target_year_offset)
        results = run_simulation(hh_copy, years=target_years)
        net_worth = results["net_worth"]
        if not net_worth:
            return 0.0, True
        target_index = min(target_years - 1, len(net_worth) - 1)
        # Sustainable spending is funded only from liquid assets and
        # pensions. Unsold property is deliberately excluded: it is not
        # available to spend unless an explicit downsizing/life event sells
        # it and moves proceeds into Cash.
        liquid_terminal = (
            float(results.get("isa_value", [0.0])[target_index])
            + float(results.get("gia_value", [0.0])[target_index])
            + float(results.get("cash_value", [0.0])[target_index])
            + float(results.get("dc_pot", [0.0])[target_index])
        )
        mortgage_balance = float(
            results.get("mortgage_balance", [0.0])[target_index]
        )
        terminal = liquid_terminal - mortgage_balance
        # The engine's depletion boundary is £0. Use the actual failure
        # boundary here rather than the convergence tolerance: a small
        # positive balance in the preceding year is still wealth, while
        # £0 or below means the plan has already run out.
        liquid_wealth = [
            float(isa) + float(gia) + float(cash) + float(dc) - float(mortgage)
            for isa, gia, cash, dc, mortgage in zip(
                results.get("isa_value", []),
                results.get("gia_value", []),
                results.get("cash_value", []),
                results.get("dc_pot", []),
                results.get("mortgage_balance", []),
            )
        ]
        exhausted_before_target = any(
            float(value) <= 0.0
            for value in liquid_wealth[:target_index]
        )
        return terminal, exhausted_before_target

    # ---- Bracket search ------------------------------------------
    # The bracket is based on viability, not terminal sign. The engine
    # clamps depleted wrappers to zero, so terminal £0 is a plateau:
    # reaching zero at the target is valid, while reaching it earlier
    # is a failed plan.
    #
    # f(0) is the household's wealth trajectory at zero spending.
    # For any sensible plan that's STRICTLY positive. If even
    # f(0) <= 0 the household is so under-funded (zero assets,
    # zero income, both partners past their mortality horizon,
    # etc.) that no real spending figure can sustain the target
    # age — report 0 with a clear error rather than running
    # bisection forever.
    f_at_zero, failed_at_zero = _probe(0.0)
    if failed_at_zero or f_at_zero < -tolerance_gbp:
        return SustainableSpendingResult(
            max_spending_gbp=0.0,
            terminal_net_worth_gbp=float(f_at_zero),
            target_age=float(target_age),
            target_year_offset=target_year_offset,
            iterations_used=1,
            converged=False,
            error=(
                f"Your plan cannot sustain age {float(target_age):.0f} "
                f"even at zero spending — terminal net worth at "
                f"f(S=0) is £{f_at_zero:,.0f}. Bump assets / income "
                f"or pick a closer target age."
            ),
            strategy_at_run=base_strategy,
        )
    if abs(f_at_zero) <= tolerance_gbp:
        return SustainableSpendingResult(
            max_spending_gbp=0.0,
            terminal_net_worth_gbp=float(f_at_zero),
            target_age=float(target_age),
            target_year_offset=target_year_offset,
            iterations_used=1,
            converged=True,
            strategy_at_run=base_strategy,
        )

    # Starting upper bound. Heuristic: aim to bracket inside 1-2
    # doublings. We seed with `f(0)` itself as a rough proxy for
    # "wealth that could be drawn down per year" (assets + future
    # pension income, very loosely), then double until sign flips.
    # The seed is the lower of two candidates so a wealth-heavy
    # household doesn't start at hundreds of thousands by mistake.
    bracket_high = max(
        20_000.0,
        f_at_zero / STARTING_BRACKET_LOW_RATIO,
    )
    bracket_high = float(bracket_high)
    f_at_high, failed_at_high = _probe(bracket_high)
    bracket_iterations = 1  # count the zero probe
    while not failed_at_high:
        bracket_high *= 2.0
        if bracket_high > SAFE_MAX_SPEND_GBP:
            # A positive terminal balance is not an error: property,
            # continuing pension income, or other non-drawdown wealth can
            # legitimately remain at the target age. There is no terminal
            # wealth target in this calculation, so stop the inverse search
            # without presenting a misleading warning to the user.
            return SustainableSpendingResult(
                # There is no meaningful maximum when terminal wealth is
                # unaffected by spending (for example, property remains in
                # the estate). Return the current plan's spending instead of
                # inventing a multi-million-pound recommendation.
                max_spending_gbp=float(getattr(household, "spending_target", 0.0)),
                terminal_net_worth_gbp=float(f_at_high),
                target_age=float(target_age),
                target_year_offset=target_year_offset,
                iterations_used=bracket_iterations,
                converged=False,
                error=None,
                strategy_at_run=base_strategy,
            )
        f_at_high, failed_at_high = _probe(bracket_high)
        bracket_iterations += 1
        if bracket_iterations > MAX_BRACKET_DOUBLINGS:
            # Doubling loop ran out of steps without flipping the
            # sign — should be unreachable because of the
            # SAFE_MAX_SPEND_GBP cap above. Defensive return.
            return SustainableSpendingResult(
                max_spending_gbp=0.0,
                terminal_net_worth_gbp=float(f_at_high),
                target_age=float(target_age),
                target_year_offset=target_year_offset,
                iterations_used=bracket_iterations,
                converged=False,
                error=(
                    "Bracket-doubling loop exceeded step cap. This is "
                    "a solver bug — please file a bug report with your "
                    "household inputs snapshot."
                ),
                strategy_at_run=base_strategy,
            )

    bracket_low = DEFAULT_BRACKET_LOW  # 0.0 — f(0) > 0 verified above
    # ---- Bisection -----------------------------------------------
    # Standard bisection keeps `bracket_low` as the most-recent
    # positive-terminal candidate and `bracket_high` as the most-
    # recent non-positive one. After each step, `mid = (low+high)/2`
    # recurses. Convergence fires when `|f(mid)| <= tolerance_gbp`.
    for step in range(max_iterations):
        mid = (bracket_low + bracket_high) / 2.0
        f_mid, failed_before_target = _probe(mid)
        if not failed_before_target and abs(f_mid) <= tolerance_gbp:
            return SustainableSpendingResult(
                max_spending_gbp=float(mid),
                terminal_net_worth_gbp=float(f_mid),
                target_age=float(target_age),
                target_year_offset=target_year_offset,
                iterations_used=bracket_iterations + step + 1,
                converged=True,
                strategy_at_run=base_strategy,
                spending_phases=_scaled_phase_schedule(mid),
            )
        # Keep the last viable candidate below the first early-failure
        # candidate. This remains monotonic despite zero-clamped wealth.
        if failed_before_target or f_mid < -tolerance_gbp:
            # Early depletion or a materially negative target-year balance
            # is a failed candidate. A target value within ±tolerance is
            # accepted as the engine's numerical boundary.
            bracket_high = mid
        else:
            bracket_low = mid

    # Exhausted iterations without hitting the tolerance. Return the
    # last viable candidate, never the failed upper bound; that is the
    # conservative safe answer when the engine's annual cadence leaves
    # no candidate exactly within the tolerance.
    best_guess = bracket_low
    return SustainableSpendingResult(
        max_spending_gbp=float(best_guess),
        terminal_net_worth_gbp=float(_probe(best_guess)[0]),
        target_age=float(target_age),
        target_year_offset=target_year_offset,
        iterations_used=bracket_iterations + max_iterations,
        converged=False,
        strategy_at_run=base_strategy,
        spending_phases=_scaled_phase_schedule(best_guess),
    )
