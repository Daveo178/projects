"""Pre-retirement deficit signal — planning banner for Page 4 (Spending).

Extracted from `simulation/engine.py` to keep the engine file under
~1,000 lines. This module is PURELY a planning aid: the
`compute_pre_retirement_deficit_signal` function walks a lightweight
dict-based model of the household's pre-retirement years and returns
a `PreRetirementDeficitSignal` (or None). It does NOT run the full
simulation — it's designed to be called from `pages/4_Spending.py`
on every keystroke so the user gets near-instant feedback.

All helpers operate on duck-typed dicts (not `Person` instances) so
the Spending page can feed raw JSON without constructing dataclasses.
"""

from dataclasses import dataclass
from typing import Optional

from .state_pension import FULL_STATE_PENSION
from .spending import spending_for_age


@dataclass
class PreRetirementDeficitSignal:
    """Output of `compute_pre_retirement_deficit_signal(data, ...)`.

    ONLY returned when at least one pre-retirement year has a real
    cash-flow deficit (need > earned). The mere presence of this
    object is the firing condition for the Page 4 banner — there is
    no `has_deficit: bool` field because absence-of-object IS the
    no-signal answer.

    Field semantics
    ---------------
    `worst_year`                  : 0-indexed simulation year of the
                                     largest single-year shortfall.
    `worst_year_age_p1`           : person1's age at that year, used
                                     to render the message as
                                     "short by £X at age Y".
    `worst_deficit_gbp`           : £ shortfall in that one year.
                                     Always positive (this object
                                     only exists when deficit > 0).
    `cumulative_deficit_gbp`      : £ total over the full pre-
                                     retirement horizon, per-year
                                     weighted (sum of per-year
                                     shortfalls). Decorrelated from
                                     `worst_deficit_gbp`: a plan with
                                     £2k/year shortfall over 5 years
                                     (cumulative £10k) and a plan
                                     with £10k shortfall in the
                                     closing year only (cumulative
                                     £10k) have the same cumulative
                                     but different worst-year
                                     profiles.
    `pre_retirement_year_count`   : number of FULL simulated years
                                     BEFORE either partner retires
                                     (the actual horizon that the
                                     engine's drawdown gate keeps
                                     closed). Integer-truncated so
                                     that a fractional
                                     `retirement_age` doesn't extend
                                     the horizon past the year both
                                     partners definitively retire.
                                     Zero means there's no pre-
                                     retirement horizon to check.
    `need_at_worst_gbp`           : `spending + mortgage_paid` at
                                     the worst year. The
                                     `annual_spending_gbp` and
                                     `annual_mortgage_when_active_gbp`
                                     fields below carry the same
                                     split when the strategy is
                                     Fixed; for Inflation-adjusted
                                     `need_at_worst_gbp` includes the
                                     inflated lifestyle figure so
                                     the user's mental math (`spending
                                     + mortgage`) lines up at the
                                     year-0 base.
    `household_income_at_worst_gbp` : combined household income
                                          (wages + DB pension +
                                          State Pension) at the
                                          worst year. Mirrors the
                                          engine's pre-retirement
                                          `gross_income` shape —
                                          this is what the deficit
                                          is actually being compared
                                          against, so the banner
                                          phrasing ("household
                                          income") stays consistent
                                          with the field name.
                                          UFPLS is INTENTIONALLY
                                          excluded because UFPLS
                                          only crystallises post-
                                          retirement when the
                                          engine's drawdown block
                                          fires; counting it pre-
                                          retirement would double-
                                          count the same DC pot
                                          dollars on the Timeline
                                          page.
    `annual_spending_gbp`         : the year-0 (or "today") spending
                                     figure the user just typed on
                                     Page 4. Echoed for messaging
                                     clarity («your spending of £X»
                                     rather than «a number»).
    `annual_mortgage_when_active_gbp` : `annual_payment +
                                         annual_overpayment` while
                                         the mortgage is active.
                                         Capped at the year-0
                                         outstanding (rough upper
                                         bound) for the "deficit
                                         signal" math — we don't
                                         amortise the loan here,
                                         that would require running
                                         the full engine. The
                                         signal is upper-bound
                                         conservative, never
                                         under-stating the
                                         shortfall.
    `strategy`                    : the drawdown strategy used for
                                     the per-year `need` calc.
                                     Captured so the page can show
                                     it in the banner ("In your
                                     current 'Inflation-adjusted'
                                     plan...").
    """

    worst_year: int
    worst_year_age_p1: float
    worst_deficit_gbp: float
    cumulative_deficit_gbp: float
    pre_retirement_year_count: int
    need_at_worst_gbp: float
    household_income_at_worst_gbp: float
    annual_spending_gbp: float
    annual_mortgage_when_active_gbp: float
    strategy: str
    # Residual-after-drain fields — only meaningfully populated when
    # `cash_buffer_at_signal == True`. When False, all residual fields
    # stay at their defaults (0/-1) because the cash_buffer=False
    # plan NEVER touches pre-retirement assets by design (no drain
    # happens), so there is no "after drain" residual to report. The
    # Page 4 banner reads these to fire a SECOND, stricter alarm
    # when asset drain is unable to fully cover the deficit (i.e.
    # the household's liquid savings are insufficient even when the
    # cash_buffer mode is on — a structural underfunding, not just
    # a cash-flow smoothing problem).
    cash_buffer_at_signal: bool = False
    worst_residual_year: int = -1
    worst_residual_year_age_p1: float = 0.0
    worst_residual_gbp: float = 0.0
    cumulative_residual_gbp: float = 0.0
    total_assets_drained_gbp: float = 0.0


def _dict_person_is_retired(p: dict, year_offset: float) -> bool:
    """Duck-typed mirror of `Person.is_retired(year_offset)`. Tolerates
    missing/typed-loose fields so the deficit-signal helper can be
    called from pages that haven't built a full Person (e.g. Page 4
    reads the raw JSON and only renders a banner — no `Person(**d)`
    construction).
    """
    age = float(p.get("age", 55.0))
    retirement_age = float(p.get("retirement_age", 60.0))
    return (age + year_offset) >= retirement_age


def _dict_person_earned(
    p: dict,
    year_offset: float,
    *,
    inflation_rate: float = 0.025,
    today_value_mode: bool = False,
) -> float:
    """Duck-typed mirror of `_indexed_earned_income(person, year)`. Wage-
    indexed from the year-0 base by the partner's `income_growth_rate`.
    Returns 0.0 once the partner is past `retirement_age` — same shape
    as the engine helper so the `earned` sum here matches the engine's
    `results["earned_income"]` series for every pre-retirement year.

    Today's-value compatibility:
      * `today_value_mode=True` (set from the household
        `show_in_todays_value` flag by the outer caller) deflates
        the wage curve by inflation via
        `rate = income_growth_rate - inflation_rate` (simple
        subtraction, matching the user's mental model "7% nominal
        at 2.5% inflation = 4.5% real"). Mirrors
        `simulation/engine.py::_indexed_earned_income`'s
        `growth_rate_override` kwarg so the Spending-page
        planning-signal banner stays consistent with the engine
        output the user just rendered on the Home page.
      * `inflation_rate` defaults to 2.5% for legacy callers and
        is unused when `today_value_mode=False` (legacy path
        uses the user-entered `income_growth_rate` directly).
    """
    if _dict_person_is_retired(p, year_offset):
        return 0.0
    base = float(p.get("income_until_retirement", 0.0))
    rate = float(p.get("income_growth_rate", inflation_rate))
    if today_value_mode:
        rate = rate - inflation_rate
    return base * (1.0 + rate) ** year_offset


def _dict_partner_pension_income(
    p: dict,
    year_offset: float,
    *,
    inflation_rate: float = 0.025,
    today_value_mode: bool = False,
) -> float:
    """Per-year income from DB pension + State Pension for one
    partner. Duck-typed mirror of the engine's pre-retirement
    `gross_income` shape (DB from `Person.is_db_active`,
    State Pension via the same maths as `state_pension_income`).

    Why this lives here instead of being inherited from `_indexed_earned_income`:
    the engine bundles wages + DB + SP into a single `gross_income`
    per partner per year, but the deficit-signal helper needs the
    split (wages via `_dict_person_earned`, pension via this
    helper) so a pre-retirement horizon can correctly account for
    DB pension that kicks in BEFORE the partner retires (the
    common "keep working for a few years past draw_age" case).
    Without this, the helper understates household income between
    `draw_age` and `retirement_age` and fires spurious signals for
    users with their DB pension properly entered on Page 2.

    UFPLS is INTENTIONALLY excluded — it is a post-retirement
    crystallisation event triggered by the engine's drawdown
    block, not a pre-retirement income source.

    Returns 0.0 when the partner is below both `draw_age` and
    `state_pension_age` (or when both fields default to 0).
    """
    age = float(p.get("age", 55.0))

    # DB pension — indexed from `draw_age` onwards. Today's-value
    # mode zeros the growth rate so DB payouts stay flat at the
    # user-entered base from `draw_age` onwards. Otherwise the
    # user-entered rate (default 2.5%) applies.
    db_income_year = 0.0
    draw_age = float(p.get("draw_age", 60.0))
    if (age + year_offset) >= draw_age:
        db_base = float(p.get("db_income", 0.0))
        db_growth = float(p.get("db_growth_rate", inflation_rate))
        if today_value_mode:
            db_growth = 0.0
        years_active = max(0.0, (age + year_offset) - draw_age)
        db_income_year = db_base * (1.0 + db_growth) ** years_active

    # State Pension — FULL_STATE_PENSION (£11k/yr base, CPI-uprated)
    # from `state_pension_age` onwards. Mirrors
    # `simulation/state_pension.py` byte-for-byte so the per-year
    # figure here matches the engine's `state_payout` series for
    # every value of `state_pension_growth_rate`.
    sp_year = 0.0
    state_pension_age = float(p.get("state_pension_age", 67.0))
    if (age + year_offset) >= state_pension_age:
        sp_growth = float(p.get("state_pension_growth_rate", inflation_rate))
        if today_value_mode:
            sp_growth = 0.0
        years_active = max(0.0, (age + year_offset) - state_pension_age)
        sp_year = FULL_STATE_PENSION * (1.0 + sp_growth) ** years_active

    return db_income_year + sp_year


def _dict_mortgage_is_active(m: dict, year_offset: float) -> bool:
    """Duck-typed mirror of `Mortgage.is_active(year)`. Stop
    accruing interest once the term is up (`year >= end_year`) or
    the debt is cleared (`outstanding <= 0`).
    """
    outstanding = float(m.get("outstanding", 0.0) or 0.0)
    end_year = float(m.get("end_year", 0.0) or 0.0)
    if outstanding <= 0:
        return False
    return year_offset < end_year


def _drainable_asset_pool(assets: list) -> float:
    """Total £ the engine's `drawdown_from_assets` could drain from
    the household's liquid savings at year 0. Mirrors the priority
    whitelist in `simulation/drawdown.py::drawdown_from_assets`
    (Cash → ISA → GIA) — Property and DC are intentionally excluded
    because Property is handled by LifeEvents only (downsizing) and
    DC is unwound via UFPLS post-retirement only.

    Used by `compute_pre_retirement_deficit_signal` to MODEL the
    pre-retirement cash_buffer drain when computing the
    residual-after-drain shortfall (the second, stricter signal
    that fires for underfunded households even with the cash_buffer
    opt-in engaged). The helper does NOT call `drawdown_from_assets`
    — it just sums the pool — because the deficit-signal helper
    needs to mutate the pool year over year to track the
    monotonically-draining residual, without firing the engine's
    full `drawdown_from_assets` tax recompute (out of scope for a
    planning signal).

    Returns 0.0 when `assets` is missing or empty, or when no asset
    has `asset_type in {"Cash", "ISA", "GIA"}`. Asset values that
    are None or non-numeric fall back to 0.0 (defensive read so a
    hand-edited household_data.json with a typo doesn't crash the
    planning-signal computation).
    """
    if not isinstance(assets, list):
        return 0.0
    pool = 0.0
    for a in assets:
        if not isinstance(a, dict):
            continue
        if a.get("asset_type") not in ("Cash", "ISA", "GIA"):
            continue
        try:
            pool += float(a.get("value", 0.0))
        except (TypeError, ValueError):
            continue
    return pool


def _strategy_needs_inflation(strategy: str) -> bool:
    """Whether the helper should inflate lifestyle spending across
    years (mirrors the engine's step 6 ladder). Fixed-strategy users
    see a constant £X; Inflation-adjusted users see a per-year
    £X*(1.025)**y; Tapered (down with age) also inflates because
    the engine's step 4b uplifts the base BEFORE the taper is
    applied (`base_nominal = spending_target * (1.025)**y` then
    `(1-rate)**years_past_start`), so the planning signal here uses
    the same inflated base. The `taper_start_age` default (75)
    is well past typical retirement_age, so the pre-retirement
    horizon ends before the taper kicks in — the inflation-only
    approximation is "good enough" for a planning signal. Safe
    Withdrawal (4%) is asset-driven and the helper returns None
    (no signal) for that strategy because the year-0 input
    isn't predictive of the multi-year trajectory.
    """
    return strategy in ("Inflation-adjusted", "Tapered (down with age)")


def compute_pre_retirement_deficit_signal(
    data: dict,
    *,
    years: int = 45,
) -> Optional["PreRetirementDeficitSignal"]:
    """Compute a planning-signal for the Page 4 (Spending) banner.

    Walks simulation years 0..N while at least one partner is still
    pre-retirement. For each year, computes (need - earned) where:
        earned = `_dict_person_earned(p1, y) + _dict_person_earned(p2, y)`
        need   = spending(at year y) + mortgage_paid(at year y, if active)

    Returns a `PreRetirementDeficitSignal` only when at least one
    year's deficit is positive (i.e. earned < need). Returns `None`
    in any of the following cases — safe by construction:

        * Neither partner has data (deficit risk = 0 because no
          running household to flag).
        * One or both partners is already past `retirement_age`
          (`years_to_retirement() == 0`) — there's no pre-retirement
          horizon to check.
        * Strategy is "Safe Withdrawal (4%)" — spending is
          asset-driven; we don't predict it from current inputs.
        * Lifetime `spending == 0` AND no active mortgage — there's
          nothing to compare against, so no deficit is possible.
        * `need <= earned` for every year in the horizon — the plan
          is balanced pre-retirement and no banner should fire.

    Notes
    -----
    The deficit math is conservative — we use the full annual
    mortgage payment+overpayment for every active year (capped at
    outstanding) rather than amortising the loan. This means a plan
    with a 9y6m mortgage potentially shows a slightly higher deficit
    in the closing year than the engine will eventually report
    (£{annual + overpayment} vs the engine's pro-rata fraction
    slice). The banner wording surfaces this as "while the mortgage
    is active" so users don't expect exact engine fidelity from
    the planning signal — the signal's job is to surface a real
    cash-flow gap, not to reproduce the engine's mortgage line
    down to the penny.

    Compatible with fractional `retirement_age` and fractional
    `Mortgage.end_year` (matches `Person.is_retired`'s and
    `Mortgage.is_active`'s float-aware contracts).
    """
    p1 = data.get("person1")
    p2 = data.get("person2")
    mortgage = data.get("mortgage") or {}

    if not isinstance(p1, dict) or not isinstance(p2, dict):
        return None

    # Pre-retirement horizon length — number of FULL years before
    # the active household reaches retirement. In single-retiree mode
    # Person 2's retirement date is irrelevant, just as it is in the
    # engine; otherwise the first partner to retire opens drawdown.
    single_retiree = bool(data.get("single_retiree", False))
    p1_years_to_ret = p1.get("retirement_age", 60.0) - p1.get("age", 55.0)
    if single_retiree:
        years_to_ret = p1_years_to_ret
    else:
        years_to_ret = min(
            p1_years_to_ret,
            p2.get("retirement_age", 60.0) - p2.get("age", 55.0),
        )
    if years_to_ret <= 0:
        return None
    horizon = int(min(years_to_ret, years))  # truncate fractional
    if horizon <= 0:
        return None

    strategy = data.get("drawdown_strategy", "Fixed")
    if strategy not in ("Fixed", "Inflation-adjusted", "Spending phases"):
        # Safe Withdrawal (4%) and unknown strategies are asset-driven,
        # not predictable from the simple spending inputs.
        return None

    spending_year0 = float(data.get("spending", 0.0) or 0.0)
    annual_mortgage = (
        float(mortgage.get("annual_payment", 0.0) or 0.0)
        + float(mortgage.get("annual_overpayment", 0.0) or 0.0)
    )
    # `include_in_spending` semantics mirror the engine's step-7
    # `total_need` (see simulation/engine.py): when True the user's
    # spending figure ALREADY covers the mortgage, so the deficit
    # signal must NOT add the mortgage payment on top again (that
    # would double-count the loan and over-report the pre-retirement
    # shortfall — e.g. a £38,000 spending figure that includes a
    # £16,608 mortgage must compare against £38,000 need, not
    # £54,608). When False (default), spending is lifestyle-only and
    # the mortgage is added to `need` as before.
    mortgage_in_spending = bool(
        mortgage.get("include_in_spending", False)
    )
    # Suppress the deficit math if there's nothing to compare against:
    # no lifestyle spend AND no active mortgage across the whole
    # horizon. (Saving £0 while working is a degenerate case; the
    # banner would just say "your empty spending equals your empty
    # income", which is noise.)
    if spending_year0 <= 0 and annual_mortgage <= 0:
        return None

    # Read the household's today's-value flag once. When ON, the
    # planning signal runs in today's-money mode too — the
    # lifestyle inflation uplift is suppressed AND the partner
    # pension growth rates are zeroed via the `today_value_mode`
    # kwarg passed to `_dict_partner_pension_income` below.
    # Without this, the banner would predict a real-terms shortfall
    # that the engine itself doesn't produce (compute-side and UI-
    # side divergence with the user's foreground mode).
    today_value_data_mode = bool(data.get("show_in_todays_value", False))
    data_inflation_rate = float(
        data.get("inflation_rate", 0.025)
    )
    inflate = (
        _strategy_needs_inflation(strategy) and not today_value_data_mode
    )

    # cash_buffer-mode residual tracking. When `cash_buffer=True`,
    # the engine's step-7 `elif cash_buffer_enabled and income <
    # total_need:` branch would drain assets to cover the deficit;
    # we mirror that here on a local pool (no tax recompute, no
    # dataclass instance mutation) so we can report the residual
    # shortfall AFTER the drain as the helper's second-tier signal.
    # When `cash_buffer=False`, no drain happens by design — every
    # residual field stays at zero, and the Page 4 banner fires only
    # the existing main "Pre-retirement cash flow is in deficit"
    # warning. Assumes no per-year asset growth (year-0 pool
    # monotonically drained) — conservative over-estimate of the
    # residual vs the engine's actual behaviour, which DOES grow
    # assets in `Asset.grow()` before the drawdown block each year.
    # Acceptable trade-off for a planning signal that doesn't run
    # the full simulation.
    cash_buffer_enabled = bool(data.get("cash_buffer", False))
    drainable_pool = _drainable_asset_pool(data.get("assets") or [])

    worst_year = -1
    worst_deficit = 0.0
    cumulative_deficit = 0.0
    worst_need = 0.0
    worst_income = 0.0
    # Residual accumulators (post cash_buffer drain).
    worst_residual_year = -1
    worst_residual = 0.0
    cumulative_residual = 0.0
    total_drained = 0.0

    for y in range(horizon):
        if strategy == "Spending phases":
            # Explicit phase amounts are already in today's money and are
            # intentionally not inflated; this mirrors the engine's phase
            # strategy and keeps the warning aligned with the chart.
            need = spending_for_age(
                float(p1.get("age", 55.0)) + y,
                data.get("spending_phases", []),
                fallback_spending=spending_year0,
            )
        else:
            need = (
                spending_year0 * ((1 + data_inflation_rate) ** y)
                if inflate
                else spending_year0
            )
        if not mortgage_in_spending and _dict_mortgage_is_active(mortgage, y):
            need += min(annual_mortgage, mortgage.get("outstanding", 0.0) or 0.0)
        # Household income for this year — wages + DB + SP for both
        # partners. UFPLS is intentionally excluded (post-retirement
        # only). This mirrors the engine's pre-retirement
        # `gross_income` shape so a household with DB pension
        # entered on Page 2 doesn't get a spurious signal — the DB
        # pension closes the gap that wages alone can't. Today's-value
        # mode also zeros DB / SP growth via the
        # `today_value_mode=true` kwarg below.
        income_year = (
            _dict_person_earned(
                p1, y,
                inflation_rate=data_inflation_rate,
                today_value_mode=today_value_data_mode,
            )
            + _dict_partner_pension_income(
                p1, y,
                inflation_rate=data_inflation_rate,
                today_value_mode=today_value_data_mode,
            )
        )
        if not single_retiree:
            income_year += (
                _dict_person_earned(
                    p2, y,
                    inflation_rate=data_inflation_rate,
                    today_value_mode=today_value_data_mode,
                )
                + _dict_partner_pension_income(
                    p2, y,
                    inflation_rate=data_inflation_rate,
                    today_value_mode=today_value_data_mode,
                )
            )
        deficit = need - income_year
        if deficit > 0:
            cumulative_deficit += deficit
            if deficit > worst_deficit:
                worst_deficit = deficit
                worst_year = y
                worst_need = need
                worst_income = income_year
            # Residual-after-drain modelling — track the
            # STRUCTURAL underfunding that even the cash_buffer
            # opt-in cannot bridge. Three explicit branches so
            # the Page 4 banner reads a consistent residual
            # profile regardless of whether the drainable pool
            # is fresh, partially-exhausted, or empty from year 0:
            #
            #   1. `cash_buffer=True AND drainable_pool > 0` →
            #      drain as much as possible, residual =
            #      max(0, deficit - drained). The drainable pool
            #      is decremented so subsequent years see the
            #      smaller pool.
            #   2. `cash_buffer=True AND drainable_pool <= 0` →
            #      pool already exhausted (or never had any
            #      drainable assets). No drain is possible; the
            #      FULL deficit is residual for this year. Year
            #      AFTER year 0 with an empty pool is the
            #      "structural underfunding" alarm — asset draw
            #      alone cannot close the gap, the household
            #      genuinely needs more income, lower spending,
            #      or an asset sale. (Without this explicit
            #      branch the helper was treating "pool empty"
            #      as "no residual to report", which silently
            #      under-reported the underfunding for
            #      cash_buffer=True plans without assets.)
            #   3. `cash_buffer=False` → no drain attempted by
            #      design (the cash_buffer=False plan never
            #      touches pre-retirement assets), so residual
            #      stays 0. The Page 4 banner's firing condition
            #      (`cash_buffer_at_signal and
            #      worst_residual_gbp > 0`) short-circuits on
            #      the cash_buffer=False case at the page level,
            #      so the residual=0 default is the correct
            #      "nothing to report here" answer.
            #
            # `residual` is initialised to 0.0 here so
            # subsequent tests of `residual > worst_residual`
            # etc. never hit `NameError` for a year where
            # neither drain branch fires — a regression issue
            # the original buggy implementation had where
            # `residual` was only assigned inside the
            # sub-branch.
            residual = 0.0
            if cash_buffer_enabled:
                if drainable_pool > 0:
                    drain = min(drainable_pool, deficit)
                    drainable_pool -= drain
                    total_drained += drain
                    residual = deficit - drain
                else:
                    # Pool exhausted — full deficit is residual.
                    # Mirrors the engine's behaviour when the
                    # `drawdown_from_assets` helper returns 0
                    # because all drainable assets are at 0;
                    # the deficit is uncovered.
                    residual = deficit
            if residual > worst_residual:
                worst_residual = residual
                worst_residual_year = y
            cumulative_residual += residual

    if worst_year < 0:
        return None  # No deficit year found — no signal.

    return PreRetirementDeficitSignal(
        worst_year=worst_year,
        worst_year_age_p1=float(p1.get("age", 55.0)) + worst_year,
        worst_deficit_gbp=worst_deficit,
        cumulative_deficit_gbp=cumulative_deficit,
        pre_retirement_year_count=horizon,
        need_at_worst_gbp=worst_need,
        household_income_at_worst_gbp=worst_income,
        annual_spending_gbp=spending_year0,
        annual_mortgage_when_active_gbp=annual_mortgage,
        strategy=strategy,
        cash_buffer_at_signal=cash_buffer_enabled,
        worst_residual_year=worst_residual_year,
        worst_residual_year_age_p1=(
            float(p1.get("age", 55.0)) + worst_residual_year
            if worst_residual_year >= 0
            else 0.0
        ),
        worst_residual_gbp=worst_residual,
        cumulative_residual_gbp=cumulative_residual,
        total_assets_drained_gbp=total_drained,
    )
