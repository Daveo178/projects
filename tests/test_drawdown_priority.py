"""Tests for the user-configurable drawdown-priority list feature on
`simulation/engine.py` step 7.

The feature exposes a new top-level `drawdown_priority` field on
`Household` (default `["Pension", "Cash", "ISA", "GIA"]`) that
controls the order in which the engine drains tax wrappers when the
household is in cash-flow deficit. Pre-PR the engine always did
Pension (UFPLS) → Cash → ISA → GIA in a fixed order; the new
contract lets a user defer pension to preserve outside-IHT
inheritance, or drain ISA/GIA first to manage the basic-rate band.

Test groups
-----------

1. `TestResolvePriorityList` — pure-Python unit tests for the
   defensive resolver `_resolve_priority_list`. Covers None /
   empty / partial / invalid / duplicate inputs, all of which the
   engine's step-7 block might receive from a hand-edited
   household_data.json or a legacy pre-PR saved plan.

2. `TestDrawdownPriorityEngine` — end-to-end tests that build a
   full `Household` and run `run_simulation(...)`, asserting
   that the priority list actually changes the drawdown
   sequence in the engine's per-year results. Covers:
     * default priority preserves the pre-PR behaviour
     * ISA-first order drains ISA before pension
     * pension-last order skips UFPLS entirely until asset
       classes are exhausted
     * pre-retirement `cash_buffer` strips Pension from the
       list automatically (DC isn't drawable pre-retirement)
     * legacy `Household(...)` without the `drawdown_priority`
       field falls back to the canonical default
"""

import unittest

from models.person import Person
from models.asset import Asset
from models.mortgage import Mortgage
from models.household import Household
from simulation.ufpls import (
    _resolve_priority_list,
    _PRIORITY_VALID_WRAPPERS,
)
from simulation.engine import (
    run_simulation,
)


def _make_person(
    name="Alex",
    age=60.0,
    retirement_age=60.0,
    state_pension_age=67.0,
    dc_pot=0.0,
    db_income=0.0,
    draw_age=60.0,
    income_until_retirement=0.0,
    income_growth_rate=0.025,
    pcls_percent=0.0,
    dc_growth_rate=0.0,
):
    """Tiny `Person` factory — defaults to an already-retired 60-year-old
    with no DC pot, no DB pension, and no earned income. Lets the
    test class fire the post-retirement drawdown block immediately
    at year 0 with a predictable income (= 0). Tests then
    control the deficit via the assets list / DC pot.

    `dc_growth_rate` defaults to 0.0 (NOT the dataclass default of
    0.05) so tests that assert on `dc_pot` after a 1-year
    simulation don't have to account for compound growth. Tests
    that want growth can pass `dc_growth_rate=0.05` explicitly.
    """
    return Person(
        name=name,
        age=age,
        retirement_age=retirement_age,
        state_pension_age=state_pension_age,
        dc_pot=dc_pot,
        monthly_contrib=0.0,
        income_until_retirement=income_until_retirement,
        income_growth_rate=income_growth_rate,
        db_income=db_income,
        draw_age=draw_age,
        pcls_percent=pcls_percent,
        dc_growth_rate=dc_growth_rate,
        db_growth_rate=0.025,
        state_pension_growth_rate=0.025,
    )


def _make_household(
    *,
    assets=None,
    mortgage=None,
    spending_target=0.0,
    drawdown_strategy="Fixed",
    drawdown_priority=None,
    cash_buffer=False,
    life_expectancy_end_age=95.0,
    person1=None,
    person2=None,
):
    """Tiny `Household` factory. Defaults to a minimal retired
    couple with no assets, no mortgage, and a £30k spending need —
    just enough to fire the post-retirement drawdown block at
    year 0 in every test.
    """
    p1 = person1 or _make_person()
    p2 = person2 or _make_person(name="Sam")
    return Household(
        person1=p1,
        person2=p2,
        assets=assets or [],
        mortgage=mortgage,
        spending_target=spending_target,
        drawdown_strategy=drawdown_strategy,
        drawdown_priority=drawdown_priority if drawdown_priority is not None else list(_PRIORITY_VALID_WRAPPERS),
        cash_buffer=cash_buffer,
        life_expectancy_end_age=life_expectancy_end_age,
    )


# -----------------------------------------------------------------
# 1. Pure-Python unit tests for `_resolve_priority_list`
# -----------------------------------------------------------------
class TestResolvePriorityList(unittest.TestCase):
    """The defensive resolver that turns a possibly-malformed
    `household.drawdown_priority` into a canonical 4-wrapper
    list. The engine's step-7 block calls this on EVERY
    simulated year, so any bug here fires 35+ times per
    simulation run — fast feedback matters.
    """

    def test_none_returns_canonical_default(self):
        """`getattr(...)` returns `None` for legacy Household
        instances without the field. The resolver must return
        the full default (matches the pre-PR engine's fixed
        order byte-for-byte so legacy plans are unaffected)."""
        hh = _make_household()
        hh.drawdown_priority = None
        self.assertEqual(
            _resolve_priority_list(hh),
            ["Pension", "Cash", "ISA", "GIA"],
        )

    def test_empty_list_returns_canonical_default(self):
        """A user de-selecting all 4 wrappers in the multiselect
        should still get the canonical default (otherwise the
        engine's step-7 loop walks an empty priority list and
        falls through with no drawdown at all — a silent
        under-statement of the deficit)."""
        hh = _make_household()
        hh.drawdown_priority = []
        self.assertEqual(
            _resolve_priority_list(hh),
            ["Pension", "Cash", "ISA", "GIA"],
        )

    def test_partial_list_backfills_missing_wrappers(self):
        """A user who de-selected 'Cash' from the multiselect
        has 3 wrappers selected. The resolver must keep their
        relative order AND append the missing 'Cash' to the
        END (in canonical order, not displacing user choices)."""
        hh = _make_household()
        hh.drawdown_priority = ["ISA", "GIA", "Pension"]
        self.assertEqual(
            _resolve_priority_list(hh),
            ["ISA", "GIA", "Pension", "Cash"],
        )

    def test_invalid_entries_dropped_silently(self):
        """A hand-edited household_data.json with typos like
        'Pention' or invented labels like 'Crypto' must NOT
        crash the engine. The resolver filters them out and
        still returns a valid 4-wrapper list."""
        hh = _make_household()
        hh.drawdown_priority = ["ISA", "Pention", "Crypto", "Cash"]
        self.assertEqual(
            _resolve_priority_list(hh),
            ["ISA", "Cash", "Pension", "GIA"],
        )

    def test_duplicates_deduplicated_first_wins(self):
        """A user dragging 'ISA' into the list twice (e.g. via
        a buggy UI) must not produce a list with two 'ISA'
        entries — the engine's per-class drain would otherwise
        double-count the second occurrence. First appearance
        wins; later copies dropped."""
        hh = _make_household()
        hh.drawdown_priority = ["ISA", "GIA", "ISA", "Cash"]
        self.assertEqual(
            _resolve_priority_list(hh),
            ["ISA", "GIA", "Cash", "Pension"],
        )

    def test_non_string_entries_skipped(self):
        """Defensive against accidental `int` / `None` /
        `bool` entries from a hand-edited JSON. The resolver
        skips non-strings and only counts string entries that
        are in the valid-wrapper whitelist."""
        hh = _make_household()
        hh.drawdown_priority = ["ISA", 42, None, "Cash", True, "GIA"]
        # `True` and `42` are not in `_PRIORITY_VALID_WRAPPERS` so
        # they get dropped at the validity check, not the
        # isinstance check. Net result: ISA, Cash, GIA kept in
        # order; Pension backfilled at the end.
        self.assertEqual(
            _resolve_priority_list(hh),
            ["ISA", "Cash", "GIA", "Pension"],
        )

    def test_legacy_household_without_field_falls_back(self):
        """Pre-PR `Household` instances (no
        `drawdown_priority` attribute) — common in older
        saved JSONs — must not raise AttributeError when the
        engine's step-7 block calls `_resolve_priority_list`.
        The `getattr(..., None)` defensive read ensures the
        resolver returns the canonical default."""
        hh = _make_household()
        # Delete the attribute (simulate a pre-PR dataclass
        # instance — not possible via `del` on a dataclass
        # field, but possible if someone constructed the
        # instance via `__new__` and skipped the dataclass
        # __init__). Easiest: shadow it with None.
        hh.drawdown_priority = None
        self.assertEqual(
            _resolve_priority_list(hh),
            ["Pension", "Cash", "ISA", "GIA"],
        )


# -----------------------------------------------------------------
# 2. End-to-end engine tests for the drawdown-priority contract
# -----------------------------------------------------------------
class TestDrawdownPriorityEngine(unittest.TestCase):
    """End-to-end tests: build a `Household`, run
    `run_simulation(...)`, inspect `results["ufpls_*"]` and
    `results["{isa,gia,cash}_draw"]` to verify the engine
    actually walked the priority list in the order the user
    specified.

    All tests use a 1-year horizon (`years=1`) to keep
    assertions focused on year-0 behaviour — year 0 is where
    the post-retirement drawdown block fires immediately for
    our already-retired fixture. The engine's per-year
    loop is deterministic; year-0 + year-1 together cover
    all 3 branches (Pension-first, asset-first, no-drawdown).
    """

    def _single_year(self, hh):
        """Run a 1-year simulation. Helper to keep test bodies
        focused on the priority-list contract instead of the
        boilerplate around `run_simulation`."""
        return run_simulation(hh, years=1)

    def _post_retire_household(
        self,
        *,
        assets=None,
        dc_pot=0.0,
        spending=30_000.0,
        drawdown_priority=None,
        pcls_percent=0.0,
        cash_buffer=False,
    ):
        """Build a fully-retired couple (age 65, retirement 60)
        with a 30k spending need. The default 30k deficit
        guarantees the post-retirement drawdown block fires
        at year 0."""
        p1 = _make_person(
            name="Alex",
            age=65.0,
            retirement_age=60.0,
            dc_pot=dc_pot,
            pcls_percent=pcls_percent,
        )
        p2 = _make_person(name="Sam", age=65.0, retirement_age=60.0)
        return _make_household(
            assets=assets,
            spending_target=spending,
            drawdown_strategy="Fixed",
            drawdown_priority=drawdown_priority,
            cash_buffer=cash_buffer,
            person1=p1,
            person2=p2,
        )

    # --- Default behaviour: matches pre-PR engine byte-for-byte ---
    def test_default_priority_pulls_pension_first(self):
        """Default `["Pension", "Cash", "ISA", "GIA"]` should
        pull UFPLS first when there's a DC pot. With
        `spending=10_000` and a £50k DC pot, the Pension
        step draws the full £10k as UFPLS (25% = £2.5k
        tax-free, 75% = £7.5k taxable — below the £12.57k
        PA so zero tax). Take-home = £10k = total_need, so
        the loop breaks and no asset drawdown is needed."""
        hh = self._post_retire_household(
            dc_pot=50_000.0,
            pcls_percent=25.0,
            spending=10_000.0,
            assets=[
                Asset(name="Cash", value=10_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="Cash"),
                Asset(name="ISA", value=5_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="ISA"),
            ],
        )
        res = self._single_year(hh)
        # Pension is first in the default priority → Pension
        # step fires for the full £10k deficit. The 25% PCLS
        # cap means £2.5k tax-free + £7.5k taxable. Taxable
        # is below the £12.57k PA, so take-home = £10k.
        # Income = £10k = total_need → loop breaks, no asset
        # drawdown. Asset drawers are all 0 because the
        # household was already covered by the Pension step.
        self.assertEqual(res["tax_free_income"][0], 2_500.0)
        self.assertEqual(res["ufpls_taxable_gross"][0], 7_500.0)
        self.assertEqual(res["ufpls_taxable_net"][0], 7_500.0)
        self.assertEqual(res["isa_draw"][0], 0.0)
        self.assertEqual(res["gia_draw"][0], 0.0)
        self.assertEqual(res["cash_draw"][0], 0.0)

    def test_default_priority_drains_assets_when_dc_empty(self):
        """Default priority, DC pot empty → Pension block
        draws 0 → asset waterfall (Cash → ISA → GIA in
        legacy fixed order) funds the residual. ISA draw
        is 0 because Cash (£30k) covers the full £30k need
        first."""
        hh = self._post_retire_household(
            dc_pot=0.0,
            assets=[
                Asset(name="Cash", value=30_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="Cash"),
                Asset(name="ISA", value=5_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="ISA"),
            ],
        )
        res = self._single_year(hh)
        # Pension block fires but actual_ufpls = 0 (no DC).
        # Asset walk: Cash is first in priority, has £30k ≥
        # £30k need → full £30k drawn from Cash; ISA untouched.
        self.assertEqual(res["ufpls_taxable_net"][0], 0.0)
        self.assertEqual(res["tax_free_income"][0], 0.0)
        self.assertEqual(res["cash_draw"][0], 30_000.0)
        self.assertEqual(res["isa_draw"][0], 0.0)
        self.assertEqual(res["gia_draw"][0], 0.0)

    # --- ISA-first order: drains ISA before Pension ---
    def test_isa_first_drains_isa_before_pension(self):
        """User moves 'ISA' to the front of the priority list
        (e.g. `["ISA", "Pension", "GIA", "Cash"]`). The
        engine should drain ISA FIRST, then UFPLS for the
        residual — preserving the IHT-friendly 'defer
        pension' semantics for as much of the deficit as
        possible. With ISA=£20k and need=£30k, ISA covers
        £20k and Pension draws the remaining £10k as UFPLS.
        """
        hh = self._post_retire_household(
            dc_pot=50_000.0,
            pcls_percent=25.0,
            assets=[
                Asset(name="ISA", value=20_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="ISA"),
                Asset(name="Cash", value=50_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="Cash"),
            ],
            drawdown_priority=["ISA", "Pension", "GIA", "Cash"],
        )
        res = self._single_year(hh)
        # ISA fully drained (£20k); UFPLS covers the
        # remaining £10k (£2.5k tax-free + £7.5k taxable,
        # post-tax take-home varies — assertion is on
        # the per-source series, not exact tax).
        self.assertEqual(res["isa_draw"][0], 20_000.0)
        # Pension did fire (the residual £10k needed UFPLS)
        self.assertGreater(
            res["ufpls_taxable_net"][0] + res["tax_free_income"][0],
            0.0,
        )
        # Cash untouched because ISA + Pension covered the
        # full deficit. This is the user's stated goal:
        # preserve Cash for emergencies by draining ISA first.
        self.assertEqual(res["cash_draw"][0], 0.0)

    # --- Pension-last order: skip UFPLS entirely ---
    def test_pension_last_skips_ufpls_until_assets_exhausted(self):
        """User de-selects 'Pension' from the priority list
        entirely (e.g. `["ISA", "GIA", "Cash"]`). The engine
        MUST skip the PCLS/UFPLS waterfall block even when
        the household has a DC pot — the user explicitly
        wants to defer pension draws. Assets fund the full
        deficit; DC pot is left untouched for inheritance.
        """
        hh = self._post_retire_household(
            dc_pot=50_000.0,
            pcls_percent=25.0,
            assets=[
                Asset(name="ISA", value=10_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="ISA"),
                Asset(name="GIA", value=10_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="GIA"),
                Asset(name="Cash", value=15_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="Cash"),
            ],
            drawdown_priority=["ISA", "GIA", "Cash"],
        )
        # The resolver backfills 'Pension' to the end; Pension
        # is the LAST wrapper, so it only fires if the asset
        # walk leaves a residual. With assets totalling £35k
        # vs a £30k need, the asset walk covers the full
        # deficit and Pension never fires.
        # Note: we still pass drawdown_priority without
        # Pension to test that the engine respects the
        # user-facing multiselect order, NOT the resolver's
        # backfilled order. The engine's
        # `_resolve_priority_list` adds Pension to the end
        # of the list, but since the asset walk covers the
        # full deficit, Pension's iteration never runs.
        res = self._single_year(hh)
        # DC pot is left untouched (this is the user's
        # explicit goal).
        self.assertEqual(hh.person1.dc_pot, 50_000.0)
        self.assertEqual(hh.person2.dc_pot, 0.0)
        # No UFPLS drawdown this year (assets covered).
        self.assertEqual(res["ufpls_taxable_net"][0], 0.0)
        self.assertEqual(res["tax_free_income"][0], 0.0)
        # Asset walk fires in user-specified order:
        # ISA (£10k) + GIA (£10k) + Cash (£10k of £15k) = £30k.
        self.assertEqual(res["isa_draw"][0], 10_000.0)
        self.assertEqual(res["gia_draw"][0], 10_000.0)
        self.assertEqual(res["cash_draw"][0], 10_000.0)

    def test_pension_last_with_insufficient_assets_falls_through(self):
        """User de-selects Pension from the priority list, but
        the asset pool is insufficient to cover the deficit.
        The resolver backfills 'Pension' to the end of the
        list, so when the asset walk leaves a residual,
        Pension is then pulled. This is the 'Pension is the
        last resort' semantic — user gets their IHT-friendly
        ordering for as much of the deficit as possible,
        and only touches DC when no other option remains.
        """
        hh = self._post_retire_household(
            dc_pot=50_000.0,
            pcls_percent=25.0,
            assets=[
                Asset(name="ISA", value=5_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="ISA"),
                Asset(name="Cash", value=5_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="Cash"),
            ],
            drawdown_priority=["ISA", "GIA", "Cash"],  # Pension de-selected
            spending=30_000.0,
        )
        res = self._single_year(hh)
        # ISA + Cash = £10k drained, then Pension's backfilled
        # iteration fires for the remaining £20k.
        self.assertEqual(res["isa_draw"][0], 5_000.0)
        self.assertEqual(res["cash_draw"][0], 5_000.0)
        self.assertEqual(res["gia_draw"][0], 0.0)  # no GIA in the assets list
        # Pension drew the residual £20k as UFPLS.
        self.assertGreater(
            res["ufpls_taxable_net"][0] + res["tax_free_income"][0],
            0.0,
        )

    # --- Pre-retirement cash_buffer strips Pension ---
    def test_cash_buffer_strips_pension_pre_retirement(self):
        """Pre-retirement cash_buffer mode must skip 'Pension'
        from the priority walk because the DC pot isn't
        drawable pre-retirement (HMRC UFPLS rules require
        crystallisation events, which only fire
        post-retirement). The user can list Pension first,
        last, or in the middle — it never fires here.
        """
        # Pre-retirement couple (age 50, retirement 60) with
        # a 10-year pre-retirement horizon and a deficit
        # (spending £30k > earned £0). Without cash_buffer
        # the engine skips drawdown entirely; WITH
        # cash_buffer the asset walk fires.
        p1 = _make_person(
            name="Alex",
            age=50.0,
            retirement_age=60.0,
            income_until_retirement=0.0,
            dc_pot=100_000.0,  # would be tempting to draw, but pre-retirement!
        )
        p2 = _make_person(name="Sam", age=50.0, retirement_age=60.0, income_until_retirement=0.0)
        hh = _make_household(
            assets=[
                Asset(name="ISA", value=15_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="ISA"),
                Asset(name="Cash", value=20_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="Cash"),
            ],
            spending_target=30_000.0,
            drawdown_strategy="Fixed",
            drawdown_priority=["Pension", "ISA", "GIA", "Cash"],  # Pension first!
            cash_buffer=True,
            person1=p1,
            person2=p2,
            life_expectancy_end_age=70.0,  # 20-year horizon, 10y pre-retirement
        )
        res = run_simulation(hh, years=1)
        # DC pot untouched pre-retirement despite Pension
        # being first in the priority list.
        self.assertEqual(hh.person1.dc_pot, 100_000.0)
        # Asset walk in user order: ISA first (£15k) then
        # Cash (£15k of £20k). Pension silently skipped.
        self.assertEqual(res["isa_draw"][0], 15_000.0)
        self.assertEqual(res["cash_draw"][0], 15_000.0)
        self.assertEqual(res["gia_draw"][0], 0.0)
        # No UFPLS / tax-free pre-retirement.
        self.assertEqual(res["ufpls_taxable_net"][0], 0.0)
        self.assertEqual(res["tax_free_income"][0], 0.0)

    # --- Legacy compatibility: missing field falls back ---
    def test_legacy_household_runs_without_drawdown_priority(self):
        """A `Household` instance built without the
        `drawdown_priority` kwarg (e.g. a pre-PR test
        fixture) must still run cleanly. The
        `Household.__init__` defaults `drawdown_priority`
        to the canonical list, and the engine's
        `_resolve_priority_list` is a no-op on that
        default — so the behaviour is byte-identical to
        the default-priority test above."""
        p1 = _make_person(
            name="Alex",
            age=65.0,
            retirement_age=60.0,
            dc_pot=50_000.0,
            pcls_percent=25.0,
        )
        p2 = _make_person(name="Sam", age=65.0, retirement_age=60.0)
        # Note: NO drawdown_priority kwarg — uses dataclass
        # default `["Pension", "Cash", "ISA", "GIA"]`.
        hh = Household(
            person1=p1,
            person2=p2,
            assets=[
                Asset(name="Cash", value=10_000.0, growth_rate=0.0, contribution_until_retirement=0, asset_type="Cash"),
            ],
            spending_target=10_000.0,
            drawdown_strategy="Fixed",
        )
        res = run_simulation(hh, years=1)
        # Default priority: Pension first → UFPLS covers the
        # full £10k need (25% = £2.5k tax-free, 75% = £7.5k
        # taxable — below £12.57k PA so zero tax). Take-home
        # = £10k = total_need → loop breaks; Cash untouched.
        self.assertEqual(res["tax_free_income"][0], 2_500.0)
        self.assertEqual(res["ufpls_taxable_gross"][0], 7_500.0)
        self.assertEqual(res["ufpls_taxable_net"][0], 7_500.0)
        self.assertEqual(res["cash_draw"][0], 0.0)
        self.assertEqual(res["isa_draw"][0], 0.0)


if __name__ == "__main__":
    unittest.main()
