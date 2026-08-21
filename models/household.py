from dataclasses import dataclass, field
from typing import List
from .person import Person
from .asset import Asset
from .mortgage import Mortgage
from .events import LifeEvent

@dataclass
class Household:
    person1: Person
    person2: Person
    assets: List[Asset] = field(default_factory=list)
    mortgage: Mortgage = None
    spending_target: float = 0.0
    # Explicit age-based spending phases. Each item is a dict with
    # `annual_spending` and `until_age`, expressed in today's money.
    # The engine uses the first phase whose age threshold has not been
    # passed, then continues using the final phase after the last threshold.
    spending_phases: List[dict] = field(default_factory=list)
    drawdown_amount: float = 0.0
    drawdown_strategy: str = "Fixed"

    # All life events — cash one-offs AND downsizing — share a single
    # `LifeEvent` dataclass now (downsizing is distinguished by a
    # non-zero `sell_property_value` field within the same dataclass,
    # not by a separate sibling dataclass). See `models/events.py`.
    events: List[LifeEvent] = field(default_factory=list)

    # Opt-in planning mode that fixes the engine's pre-retirement
    # phantom-cash effect on the mortgage. When False (default), the
    # engine pretends the household has the cash to service the
    # mortgage each year — `mortgage.outstanding` reduces without a
    # matching Cash / ISA / GIA drain, so `net_worth` artificially
    # rises by `mortgage_paid` on pre-retirement deficit years. When
    # True, the engine lifts the pre-retirement asset-drawdown gate
    # so Cash / ISA / GIA dip to cover BOTH (a) any mortgage shortfall
    # the household can't fund from earned income AND (b) any
    # lifestyle shortfall pre-retirement — restoring correct
    # net-worth accounting for cash-flow deficit years. PCLS / UFPLS
    # / DB drawdown remain strictly retired-gated under the existing
    # `if any_retired` waterfall block. Re-using the existing
    # `drawdown_from_assets` priority (Cash → ISA → GIA) means the
    # on-chart `Cash Draw` / `ISA Draw` / `GIA Draw` stacked-bar
    # segments automatically render pre-retirement drains when this
    # mode is on — no chart code change needed. See the
    # `TestCashBuffer` regression tests in `tests/test_cash_buffer.py`
    # for the locked-down contract and `simulation/engine.py` step 7
    # for the implementation.
    cash_buffer: bool = False

    # When True, this is a single-retiree plan. Person 2's persisted
    # inputs remain available for a future switch back to a couple, but
    # the simulation must not use any of them (including State Pension,
    # DC pension, DB pension, wages, contributions, tax, or horizon).
    single_retiree: bool = False

    # Tapered (down with age) spending strategy params. Defaults
    # reflect a typical "go-go → slow-go" late-life curve: real
    # spending declines 2%/yr starting at age 75, with a £10,000/yr
    # floor so it doesn't asymptotically approach zero in extreme
    # old age (where State Pension would still be topping up).
    # All three are `getattr`'d safely in `simulation/engine.py`
    # step 6 so a legacy `Household(...)` instance without the
    # fields constructs cleanly (no `Household.__init__()` crash
    # on `TypeError: ... unexpected keyword argument 'taper_...'`).
    taper_start_age: float = 75.0
    taper_rate: float = 0.02
    taper_floor_gbp: float = 10_000.0

    # Optional later-life step-downs. Each reduction is applied once, in
    # the year Person 1 reaches the configured age, after the continuous
    # taper above. A 0% default preserves existing plans byte-for-byte.
    late_life_step_1_age: float = 75.0
    late_life_step_1_rate: float = 0.0
    late_life_step_2_age: float = 85.0
    late_life_step_2_rate: float = 0.0

    # Optional go-go bump on top of the Tapered strategy. Real-
    # terms % increase applied to the inflation-adjusted base
    # every year between `retirement_age` and `taper_start_age`
    # (= the peak; the existing `taper_start_age` field doubles
    # as the peak-age anchor so we don't proliferate widgets).
    # Default 0.0% — meaning pure-taper behaviour identical to
    # the pre-bump engine. With bump=5% + taper_start_age=70 +
    # retirement_age=60, spending peaks at 10 years of
    # compounding = (1.05)^10 ≈ 1.629× the inflation-adjusted
    # base, then declines. Phase boundaries anchored on person1
    # (matches existing pre-retirement code path — partial-year
    # DCs, mortgage amortisation, etc.).
    gogo_bump_pct: float = 0.0

    # Joint-life (last-to-die) end age for the simulation horizon.
    # 95 is roughly the upper-end (≈p10 mortality scenario) for a
    # 65-year-old UK couple today and matches the existing 45-year
    # default when both partners start at 55. The engine computes
    # `run_simulation` years from the active person(s): in couple mode
    # `max(end_age - p1.age, end_age - p2.age)` funds both partners;
    # single-retiree mode uses Person 1 only.
    # Floor at 5 years inside the engine protects against the
    # both-already-past-target corner case. Page 2 exposes this as
    # a `years_and_months_input` widget so users can also enter
    # fractional end dates (e.g. "95 years 6 months" → 95.5).
    life_expectancy_end_age: float = 95.0

    # Drawdown priority — the order in which the engine drains tax
    # wrappers when the household is post-retirement and has a
    # cash-flow deficit. The default `["Pension", "Cash", "ISA",
    # "GIA"]` preserves the prior engine's behaviour byte-for-byte
    # (UFPLS/PCLS pulled first via the 25%-tax-free preference, then
    # Cash → ISA → GIA waterfall for any residual). The "Pension"
    # entry triggers the engine's PCLS/UFPLS waterfall block; the
    # other entries route through `drain_single_asset_class` with
    # the user's relative order. Users can move "Pension" to the
    # tail of the list to defer DC draws (preserves inheritance
    # outside IHT) — the engine strips "Pension" from the list for
    # the pre-retirement `cash_buffer` block, since DC is not
    # drawable pre-retirement. Defensively populated by
    # `_resolve_priority_list` in `simulation/engine.py` so a
    # partial list (e.g. from `st.multiselect` de-selection) is
    # always extended back to all four wrappers at the tail in a
    # deterministic order. Locked down by
    # `tests/test_drawdown_priority.py`.
    drawdown_priority: list = field(
        default_factory=lambda: ["Pension", "Cash", "ISA", "GIA"]
    )

    # ---------------- "Show in today's value" toggle ----------------
    # Opt-in educational mode that strips inflation out of the
    # simulation. When True, the engine (`simulation/engine.py`)
    # rewrites every growth rate so the entire projection is in
    # TODAY'S purchasing power rather than nominal £. The
    # transformations applied when this flag is True:
    #
    #   * DB pension growth → 0% (payouts stay flat at the
    #     user-entered annual base from draw_age onwards).
    #   * State Pension growth → 0% (payouts stay flat at
    #     `FULL_STATE_PENSION` from `state_pension_age` onwards).
    #   * DC pot growth → `dc_growth_rate - inflation_rate`
    #     (simple subtraction, matching the user's mental model
    #     "7% nominal at 2.5% inflation = 4.5% in today's
    #     money"). Same formula applied to wage growth on the
    #     `_indexed_earned_income` helper so a 2.5% wage growth
    #     with 2.5% inflation reads as exactly 0%.
    #   * Asset growth → `growth_rate - inflation_rate` for
    #     ISA / GIA / Cash assets; `growth_rate = 0` for
    #     Property assets specifically (the user pays no
    #     inflation uplift on property capital appreciation in
    #     this view — the home's nominal £ value is frozen at
    #     its current figure).
    #   * Mortgage interest → UNCHANGED. The mortgage is a real
    #     (not inflation-linked) liability in the model, so its
    #     quoted `rate` keeps applying in both modes.
    #   * Spending (Inflation-adjusted / Tapered strategies) →
    #     no inflation step. The base £ stays flat (no
    #     `* (1 + 0.025) ** year` compounding); only the taper
    #     factor still applies for the Tapered strategy.
    #
    # All transformations are lossless reversals: turning the
    # flag back off (`False`) reproduces the prior engine output
    # byte-for-byte because the effective-rate formulas collapse
    # to the user-entered rate when `show_in_todays_value=False`.
    # Default False preserves existing saved plans' behaviour.
    # Locked down by `tests/test_todays_value.py`.
    show_in_todays_value: bool = False

    # ---------------- Inflation assumption ----------------
    # Centralised household-level inflation assumption. The
    # engine previously hard-coded `0.025` in six places
    # (Inflation-adjusted spending step 6, Tapered strategy
    # base uplift, the deficit-signal helper, `_indexed_earned_
    # income`'s wage curve baseline test — and indirectly via
    # the Pension page's `db_growth=0.025` / `sp_growth=0.025`
    # / `income_growth_rate=0.025` defaults). Default 2.5%
    # preserves all existing test contracts. The to-day-value
    # toggle above uses this rate as the deflator; turning the
    # toggle ON effectively means "strip this inflation out of
    # every growth-rate calculation". Not exposed as a widget
    # yet (keeps scope tight) — the rate is intentionally
    # configurable here so a future Pensions-page slider can
    # offer "what if inflation averages 3%?" sensitivity without
    # an engine change.
    inflation_rate: float = 0.025

    def total_assets(self):
        return sum(a.value for a in self.assets)

    def ages_in_year(self, year_offset: int):
        """Return projected ages keyed by the generic planner slots.

        The persisted ``Person.name`` field may contain a legacy display
        name from an older saved plan. Slot labels keep this helper's output
        generic and stable without changing the ``person1``/``person2``
        storage schema.
        """
        return {
            "Person 1": self.person1.age + year_offset,
            "Person 2": self.person2.age + year_offset,
        }
