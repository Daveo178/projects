"""Regression tests for the `Household.cash_buffer` simulation mode.

Cash-buffer mode is an opt-in planning flag that fixes the engine's
pre-existing mortgage "phantom-cash" effect: pre-retirement deficit
years used to show `net_worth` going UP by `mortgage_paid` because
step 4 reduced `mortgage.outstanding` without tracking any cash
leaving the household. When `cash_buffer=True`, step 7 lifts the
pre-retirement asset-drawdown gate so Cash → ISA → GIA dip to cover
both the mortgage shortfall AND any lifestyle shortfall before
retirement — restoring correct net-worth accounting (the Cash drain
exactly offsets the mortgage balance reduction).

PCLS / UFPLS / DB drawdown stay strictly retired-gated under the
existing `if any_retired` waterfall block. `cash_buffer` only enables
ASSET drawdown (Cash → ISA → GIA via `drawdown_from_assets`).

Locked-down contracts:

    * `cash_buffer=False` (default, dataclass field) — PRESERVES the
      legacy behaviour tested by `TestDrawdownSuppressedPreRetirement`
      in `tests/test_drawdown.py`. Older saved household_data.json
      without the field construct cleanly and behave identically.
    * `cash_buffer=True` — pre-retirement years where
      `income < (spending + mortgage_paid)` route the shortfall
      through `drawdown_from_assets` in priority order (Cash → ISA
      → GIA). `cash_draw` / `isa_draw` / `gia_draw` reflect the
      dip on the funding-sources chart.
    * Pension waterfall (PCLS / UFPLS / DB) stays retired-gated —
      even with `cash_buffer=True`, pre-retirement years emit
      zero `ufpls_taxable_gross` / `ufpls_taxable_net` /
      `tax_free_income`.
    * Post-retirement drawdown flows unchanged through the existing
      `if any_retired` block — the cash_buffer flag does NOT alter
      the post-retirement waterfall.
    * The mortgage balance trajectory (`mortgage_balance` series)
      is identical regardless of `cash_buffer`; step 4 amortises
      the same way every year. The flag affects ONLY the per-year
      `cash_draw` / `isa_draw` / `gia_draw` and `net_worth` deltas.
    * `net_worth` for the cash_buffer=True plan is STRICTLY LESS
      than for the cash_buffer=False plan on pre-retirement deficit
      years (since the False plan was artificially inflated by the
      phantom uplift).
"""

import unittest

from models.asset import Asset
from models.household import Household
from models.mortgage import Mortgage
from models.person import Person

from simulation.engine import run_simulation


# Test helpers — mirror `tests/test_drawdown.py`'s pattern so the
# fixtures here compose with that file's helpers without surprising
# coupling. Field defaults keep the dataclass back-compat paths
# (`Household(**legacy_data)` for saved JSON without `cash_buffer`)
# exercised without extra setup.

def _person(
    *,
    age=55,
    retirement_age=99,
    state_pension_age=99,
    dc_pot=0.0,
    draw_age=99,
    income=0.0,
    db_income=0.0,
    dc_growth=0.0,
    db_growth=0.0,
    sp_growth=0.025,
    pcls_percent=0,
    income_growth=0.0,
):
    return Person(
        name="P",
        age=age,
        retirement_age=retirement_age,
        state_pension_age=state_pension_age,
        dc_pot=dc_pot,
        db_income=db_income,
        monthly_contrib=0.0,
        income_until_retirement=income,
        draw_age=draw_age,
        pcls_percent=pcls_percent,
        income_growth_rate=income_growth,
        monthly_contrib_pct=0.0,
        dc_growth_rate=dc_growth,
        db_growth_rate=db_growth,
        state_pension_growth_rate=sp_growth,
    )


class TestCashBufferFalsePreservesLegacy(unittest.TestCase):
    """`cash_buffer=False` (default) — the existing pre-retirement
    drawdown-suppression contract from
    `TestDrawdownSuppressedPreRetirement` is preserved. No asset
    drawdown, no pension drawdown, pre-retirement years report
    `Income < Spending` as a planning signal only."""

    def test_zero_pre_retirement_asset_draw_with_income_zero_and_mortgage(self):
        p1 = _person(age=55, retirement_age=65, income=0.0)
        p2 = _person(age=55, retirement_age=65, income=0.0)
        mortgage = Mortgage(
            outstanding=100_000,
            rate=0.04,
            end_year=10.0,
            annual_payment=10_000,
            annual_overpayment=0,
        )
        cash = Asset(
            name="Cash", value=30_000, growth_rate=0.0,
            asset_type="Cash",
        )
        isa = Asset(
            name="ISA", value=20_000, growth_rate=0.05,
            asset_type="ISA",
        )
        h = Household(
            person1=p1, person2=p2, assets=[isa, cash],
            mortgage=mortgage, spending_target=30_000, events=[],
            cash_buffer=False,  # explicit
        )
        r = run_simulation(h, years=12)
        # Pre-retirement years 0..9 (both age 55..64, retire at 65).
        for y in range(10):
            with self.subTest(year=y, age=55 + y):
                self.assertEqual(r["isa_draw"][y], 0.0)
                self.assertEqual(r["gia_draw"][y], 0.0)
                self.assertEqual(r["cash_draw"][y], 0.0)
                self.assertEqual(r["ufpls_taxable_net"][y], 0.0)
                self.assertEqual(r["ufpls_taxable_gross"][y], 0.0)
                self.assertEqual(r["tax_free_income"][y], 0)


class TestCashBufferTrueDrainsAssets(unittest.TestCase):
    """`cash_buffer=True` — pre-retirement deficit years dip the
    household's liquid savings (Cash → ISA → GIA) to cover the
    shortfall. Lock in the priority ordering and the partial-cover
    edge case."""

    def test_cash_drawn_before_isa_before_gia_in_priority_order(self):
        # Tight funding: Cash=£5k, ISA=£80k, GIA=£50k.
        # Shortfall=£55k expected for year 0 (40k spend + 15k mortgage).
        # Priority: Cash first (£5k), then ISA (£50k to fill), GIA untouched.
        p1 = _person(age=55, retirement_age=65, income=0.0)
        p2 = _person(age=55, retirement_age=65, income=0.0)
        mortgage = Mortgage(
            outstanding=300_000,
            rate=0.04,
            end_year=10.0,
            annual_payment=15_000,
            annual_overpayment=0,
        )
        cash = Asset(
            name="Cash", value=5_000, growth_rate=0.0,
            asset_type="Cash",
        )
        isa = Asset(
            name="ISA", value=80_000, growth_rate=0.05,
            asset_type="ISA",
        )
        gia = Asset(
            name="GIA", value=50_000, growth_rate=0.05,
            asset_type="GIA",
        )
        h = Household(
            person1=p1, person2=p2, assets=[isa, cash, gia],
            mortgage=mortgage, spending_target=40_000, events=[],
            cash_buffer=True,
        )
        r = run_simulation(h, years=12)
        with self.subTest(year=0, age=55):
            # £5k Cash drained first, then £50k ISA, GIA untouched.
            self.assertAlmostEqual(r["cash_draw"][0], 5_000.0, places=2)
            self.assertAlmostEqual(r["isa_draw"][0], 50_000.0, places=2)
            self.assertAlmostEqual(r["gia_draw"][0], 0.0, places=2)
            # Pension waterfall never fires pre-retirement.
            self.assertEqual(r["ufpls_taxable_gross"][0], 0.0)
            self.assertEqual(r["ufpls_taxable_net"][0], 0.0)

    def test_lifestyle_shortfall_pre_retirement_drains_assets(self):
        # No mortgage but pre-retirement lifestyle deficit. Cash_buffer
        # mode should still drain Cash → ISA → GIA because the cash-
        # flow shortfall is real — same code path handles both mortgage
        # and lifestyle gaps.
        p1 = _person(age=55, retirement_age=65, income=0.0)
        p2 = _person(age=55, retirement_age=65, income=0.0)
        cash = Asset(
            name="Cash", value=20_000, growth_rate=0.0,
            asset_type="Cash",
        )
        h = Household(
            person1=p1, person2=p2, assets=[cash],
            mortgage=None, spending_target=30_000, events=[],
            cash_buffer=True,
        )
        r = run_simulation(h, years=12)
        # Year 0: spend £30k, income £0, no mortgage. shortfall=£30k.
        # Cash had £20k; cash_draw=£20k. Residual £10k stays
        # uncovered (Income < Spending on chart).
        with self.subTest(year=0):
            self.assertAlmostEqual(r["cash_draw"][0], 20_000.0, places=2)


class TestCashBufferPhantomUpliftFixed(unittest.TestCase):
    """The headline benefit of cash_buffer mode: pre-retirement
    net_worth trajectories match reality (Cash drain offsets debt
    reduction) instead of phantom-uplifting by `mortgage_paid`."""

    def test_net_worth_strictly_less_than_legacy_phantom_path(self):
        # Same plan, two runs — cash_buffer=False (legacy phantom) vs
        # cash_buffer=True (correct). With fresh fixtures per run,
        # the only difference is the flag, so:
        #   * cash_buffer=False run: step 4 amortises the mortgage
        #     each year without any matching Cash drain → mortgage
        #     balance reduces but cash never leaves → net_worth
        #     ARTIFICIALLY RISES by `mortgage_paid` each pre-retirement
        #     year (the headline "phantom uplift" bug).
        #   * cash_buffer=True run: step 4 amortises the mortgage;
        #     step 7's `elif cash_buffer_enabled` branch drains
        #     `mortgage_paid - income` from Cash → ISA → GIA — so
        #     net_worth correctly stays flat on the mortgage portion
        #     (asset drain exactly offsets debt reduction) and only
        #     drops by the lifestyle spend (real outflow).
        # Locked invariant: `r_on` is STRICTLY LESS than `r_off` at
        # every pre-retirement year — including year 0, since the
        # cash_buffer drain fires in step 7 of year 0 itself.
        # (An earlier `assertAlmostEqual` at year 0 was logically
        # wrong because cash_buffer mode diverges at year 0 too —
        # reverted to `assertLess`. Fresh-fixture pattern is
        # retained so the comparison is fair.)
        def _fresh_kwargs():
            return dict(
                person1=_person(age=55, retirement_age=65, income=0.0),
                person2=_person(age=55, retirement_age=65, income=0.0),
                mortgage=Mortgage(
                    outstanding=100_000, rate=0.04, end_year=10.0,
                    annual_payment=10_000, annual_overpayment=0,
                ),
                assets=[
                    Asset(
                        name="Cash", value=50_000, growth_rate=0.0,
                        asset_type="Cash",
                    ),
                    Asset(
                        name="ISA", value=80_000, growth_rate=0.05,
                        asset_type="ISA",
                    ),
                ],
                spending_target=30_000, events=[],
            )
        r_off = run_simulation(
            Household(**_fresh_kwargs(), cash_buffer=False), years=10
        )
        r_on = run_simulation(
            Household(**_fresh_kwargs(), cash_buffer=True), years=10
        )
        # Phantom-uplift manifests at year 0 (cash_buffer drain fires
        # immediately in the elif branch of step 7's first iteration)
        # and continues throughout the pre-retirement horizon. Sweep
        # ALL pre-retirement years (0..9) rather than spot-checking
        # three so a year-specific regression can't slip through. The
        # `range(10)` boundary is intentionally tight to the 10-year
        # horizon: year 10 IS the retirement-year itself (`age 55 + 10 =
        # 65 = retirement_age`), so it's outside the pre-retirement
        # phantom-uplift contract — post-retirement flows are tested
        # in TestCashBufferPostRetirementUnchanged instead.
        for y in range(10):
            with self.subTest(year=y, age=55 + y):
                self.assertLess(
                    r_on["net_worth"][y], r_off["net_worth"][y],
                    msg=(
                        f"cash_buffer=True year={y}: net_worth "
                        f"{r_on['net_worth'][y]} should be strictly "
                        f"less than legacy phantom-uplift path "
                        f"{r_off['net_worth'][y]}"
                    ),
                )
        # And cash_draw at year 0 should drain EXACTLY the year's £40k
        # shortfall (£30k spending + £10k mortgage against £0 wages);
        # locks the magnitude, not just the sign, so a future
        # regression that half-drains or double-drains is caught.
        self.assertAlmostEqual(
            r_on["cash_draw"][0], 40_000.0, delta=1.0
        )


class TestCashBufferPensionGateUntouched(unittest.TestCase):
    """cash_buffer=True must NOT lift the pension drawdown gate.
    PCLS / UFPLS / DB stay strictly retired-gated. Only ASSETS
    (Cash → ISA → GIA) dip pre-retirement."""

    def test_ufpls_does_not_fire_pre_retirement_under_cash_buffer(self):
        # Pre-retirement, big DC pot (would normally feed UFPLS),
        # big deficit, cash_buffer=True. With the gate intact,
        # UFPLS should NEVER fire pre-retirement even though DC
        # has plenty of money to drawdown.
        p1 = _person(
            age=55, retirement_age=65,
            dc_pot=200_000, dc_growth=0.05, income=0.0,
            pcls_percent=25,
        )
        p2 = _person(age=55, retirement_age=65, income=0.0)
        cash = Asset(
            name="Cash", value=20_000, growth_rate=0.0,
            asset_type="Cash",
        )
        h = Household(
            person1=p1, person2=p2, assets=[cash],
            mortgage=None, spending_target=30_000, events=[],
            cash_buffer=True,
        )
        r = run_simulation(h, years=12)
        for y in range(10):
            with self.subTest(year=y, age=55 + y):
                self.assertEqual(r["ufpls_taxable_gross"][y], 0.0)
                self.assertEqual(r["ufpls_taxable_net"][y], 0.0)
                self.assertEqual(r["tax_free_income"][y], 0)


class TestCashBufferPostRetirementUnchanged(unittest.TestCase):
    """Post-retirement, the original `if any_retired` block handles
    the full waterfall. cash_buffer does NOT alter that path."""

    def test_post_retirement_waterfall_same_with_or_without_flag(self):
        # Both retired at year 0, big DC, big deficit. The full
        # waterfall should fire identically regardless of cash_buffer
        # because post-retirement routes through `if any_retired`.
        # Fresh fixtures per run are MANDATORY: the engine mutates
        # person.dc_pot (UFPLS drawdown drains it ~50k) and
        # person.pcls_taken (advances by 25% slice) in place, so
        # sharing `kwargs` between two runs would have run 2 see
        # half-depleted DC and PCLS states.
        def _fresh_kwargs():
            return dict(
                person1=_person(
                    age=66, retirement_age=66, state_pension_age=99,
                    dc_pot=200_000, draw_age=99,
                    dc_growth=0.05, income=0.0, pcls_percent=25,
                ),
                person2=_person(age=66, retirement_age=99, income=0.0),
                assets=[
                    Asset(
                        name="Cash", value=30_000, growth_rate=0.0,
                        asset_type="Cash",
                    ),
                ],
                mortgage=None, spending_target=50_000, events=[],
            )
        r_off = run_simulation(
            Household(**_fresh_kwargs(), cash_buffer=False), years=5
        )
        r_on = run_simulation(
            Household(**_fresh_kwargs(), cash_buffer=True), years=5
        )
        # Result series are byte-equivalent for every per-source key
        # at year 0 (the first post-retirement year).
        for key in (
            "ufpls_taxable_gross", "ufpls_taxable_net",
            "isa_draw", "gia_draw", "cash_draw", "tax_free_income",
        ):
            with self.subTest(key=key):
                self.assertAlmostEqual(
                    r_off[key][0], r_on[key][0], places=2
                )


class TestCashBufferMortgageStillAmortises(unittest.TestCase):
    """cash_buffer is about ASSET DRAWDOWN. The mortgage balance
    trajectory and `mortgage_payment` series are unchanged."""

    def test_mortgage_balance_zero_at_end_year_with_cash_buffer(self):
        p1 = _person(age=55, retirement_age=65, income=0.0)
        p2 = _person(age=55, retirement_age=65, income=0.0)
        mortgage = Mortgage(
            outstanding=100_000,
            rate=0.04,
            end_year=10.0,
            annual_payment=15_000,
            annual_overpayment=0,
        )
        cash = Asset(
            name="Cash", value=80_000, growth_rate=0.0,
            asset_type="Cash",
        )
        h = Household(
            person1=p1, person2=p2, assets=[cash],
            mortgage=mortgage, spending_target=30_000, events=[],
            cash_buffer=True,
        )
        r = run_simulation(h, years=12)
        self.assertAlmostEqual(r["mortgage_balance"][-1], 0.0, places=2)

    def test_mortgage_payment_schedule_byte_equivalent_with_or_without(self):
        # The flag should NOT change `mortgage_payment[y]` for any
        # year — only the asset drain (and therefore net_worth) is
        # different. Lock this down so a future refactor can't
        # accidentally start diverting mortgage payments into the
        # asset drawdown path. Fresh fixtures per run — the engine
        # mutates `mortgage.outstanding` in place so a shared
        # `kwargs` would have run 2 see years of step-4 amortisation
        # already applied.
        def _fresh_kwargs():
            return dict(
                person1=_person(age=55, retirement_age=65, income=0.0),
                person2=_person(age=55, retirement_age=65, income=0.0),
                mortgage=Mortgage(
                    outstanding=100_000, rate=0.04, end_year=10.0,
                    annual_payment=10_000, annual_overpayment=0,
                ),
                assets=[
                    Asset(
                        name="Cash", value=50_000, growth_rate=0.0,
                        asset_type="Cash",
                    ),
                ],
                spending_target=30_000, events=[],
            )
        r_off = run_simulation(
            Household(**_fresh_kwargs(), cash_buffer=False), years=8
        )
        r_on = run_simulation(
            Household(**_fresh_kwargs(), cash_buffer=True), years=8
        )
        for y in range(8):
            with self.subTest(year=y):
                self.assertAlmostEqual(
                    r_off["mortgage_payment"][y],
                    r_on["mortgage_payment"][y],
                    places=4,
                )
                self.assertAlmostEqual(
                    r_off["mortgage_balance"][y],
                    r_on["mortgage_balance"][y],
                    places=4,
                )
        # Caveat note: `cash_draw` series IS supposed to differ
        # across the two plans (cash_buffer=True dives into Cash
        # pre-retirement, False doesn't). Locking the OPPOSITE
        # invariant so a future reader sees both halves:
        # `mortgage_payment` / `mortgage_balance` are stable across
        # the flag (step 4 is unaffected by the household-level
        # cash_buffer flag), while `cash_draw` / `isa_draw` /
        # `gia_draw` are NOT (step 7's `elif cash_buffer_enabled`
        # branch differs). At year 0 the cash_buffer=False run
        # reports zero drawdown (else branch); the cash_buffer=True
        # run drains the full £40k shortfall (Cash is empty by
        # year ~2 in this £50k Cash scenario, so checking year=0
        # captures the maximum deliverable drain).
        self.assertEqual(r_off["cash_draw"][0], 0.0)
        self.assertAlmostEqual(
            r_on["cash_draw"][0], 40_000.0, delta=1.0
        )


class TestCashBufferLegacyDataLoad(unittest.TestCase):
    """Older / hand-edited household_data.json files lack the
    `cash_buffer` key. The dataclass default + engine's
    `getattr(..., False)` defensive read means they construct
    cleanly and behave in the legacy way."""

    def test_legacy_dict_without_cash_buffer_defaults_false(self):
        legacy_data = {
            "person1": {
                "age": 55, "retirement_age": 65, "state_pension_age": 67,
                "dc_pot": 100_000, "income_until_retirement": 0.0,
                "income_growth_rate": 0.025, "draw_age": 99,
                "db_income": 0.0, "dc_growth_rate": 0.05,
                "db_growth_rate": 0.025, "state_pension_growth_rate": 0.025,
            },
            "person2": {
                "age": 55, "retirement_age": 65, "state_pension_age": 67,
                "dc_pot": 0.0, "income_until_retirement": 0.0,
                "income_growth_rate": 0.025, "draw_age": 99,
                "db_income": 0.0, "dc_growth_rate": 0.05,
                "db_growth_rate": 0.025, "state_pension_growth_rate": 0.025,
            },
            "assets": [],
            "mortgage": {
                "outstanding": 0, "rate": 0.0, "end_year": 0.0,
                "annual_payment": 0, "annual_overpayment": 0,
                "include_in_spending": False,
            },
            "spending_target": 30_000,
            "drawdown_strategy": "Fixed",
            "events": [],
            # NOTE: deliberately no `cash_buffer` key.
        }
        # No TypeError despite the missing kwarg — dataclass default.
        h = Household(**legacy_data)
        self.assertFalse(h.cash_buffer)

    def test_engine_treats_legacy_loaded_plan_as_cash_buffer_false(self):
        # Build Household via legacy method (no cash_buffer key, rely
        # on dataclass default). Run engine. Verify pre-retirement
        # defefit years don't drain assets — same contract as
        # TestCashBufferFalsePreservesLegacy.
        kwargs = dict(
            person1=_person(age=55, retirement_age=65, income=0.0),
            person2=_person(age=55, retirement_age=65, income=0.0),
            assets=[
                Asset(
                    name="Cash", value=50_000, growth_rate=0.0,
                    asset_type="Cash",
                ),
            ],
            mortgage=None, spending_target=30_000, events=[],
        )
        h = Household(**kwargs)  # no cash_buffer kwarg
        self.assertFalse(h.cash_buffer)
        r = run_simulation(h, years=12)
        for y in range(10):
            with self.subTest(year=y):
                self.assertEqual(r["cash_draw"][y], 0.0)
                self.assertEqual(r["isa_draw"][y], 0.0)
                self.assertEqual(r["gia_draw"][y], 0.0)


if __name__ == "__main__":
    unittest.main()
