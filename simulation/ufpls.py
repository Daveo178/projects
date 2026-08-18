"""UFPLS / PCLS pension drawdown waterfall + drawdown priority resolution.

Extracted from `simulation/engine.py` so the engine file stays under
~1,000 lines. The `_draw_pension_for_amount` function runs the
25%-tax-free PCLS-then-UFPLS waterfall, mutating the household's DC
pots and PCLS allowances in place. `_resolve_priority_list` builds a
deterministic, defensive wrapper order for the engine's multi-pass
drawdown loop.
"""

from .tax import uk_income_tax


# Order in which the engine walks the wrappers when the household
# needs cash. Used by `_resolve_priority_list` below to backfill
# any de-selected / missing wrappers in a deterministic tail order.
# "Pension" is special — when present in the priority list it
# triggers the engine's PCLS/UFPLS waterfall block (with its
# 25%-tax-free preference and per-spouse tax recompute). The other
# three route through `drain_single_asset_class` (single-class
# drainage in the user's relative order) so e.g. an ISA-first user
# can drain ISA before pension/GIA/Cash to manage the basic-rate
# band. Locked down by `tests/test_drawdown_priority.py`.
_PRIORITY_VALID_WRAPPERS = ("Pension", "Cash", "ISA", "GIA")


def _resolve_priority_list(household) -> list:
    """Return a defensive, canonical priority list for the engine's
    step-7 drawdown waterfall. Mirrors the page-4 multiselect's
    `default=` so a partial user selection (e.g. de-selecting
    "Cash" in the UI) never crashes the engine on a missing
    wrapper.

    Resolution rules (deterministic; tested explicitly in
    `tests/test_drawdown_priority.py::TestResolvePriorityList`):

    1. `getattr(household, "drawdown_priority", None)` — defensive
       read so a legacy `Household(...)` instance without the
       dataclass field (pre-PR saved JSON) does NOT raise
       `AttributeError`. Falls back to `None`.
    2. `None` or empty list → returns the full default
       `["Pension", "Cash", "ISA", "GIA"]` (matches the
       `Household` dataclass default and preserves the prior
       engine's byte-for-byte behaviour).
    3. Items in the user's list are kept in their relative order
       (first appearance wins; duplicates are removed — protects
       against a user dragging "ISA" into the list twice).
    4. Items NOT in `_PRIORITY_VALID_WRAPPERS` (typos like
       "Pention" or invented labels like "Crypto") are silently
       dropped — the page-4 widget's whitelist is the only
       intended entry point, but a hand-edited
       `household_data.json` shouldn't crash the engine.
    5. Wrappers in `_PRIORITY_VALID_WRAPPERS` that the user
       did NOT select are appended to the END in canonical
       order (Pension → Cash → ISA → GIA). They never displace
       user-chosen entries — a user who wants "Pension last"
       gets exactly that; the engine just guarantees all four
       wrappers are reachable so a residual shortfall can
       always be funded from somewhere.

    The returned list is a NEW list (engine never mutates
    `household.drawdown_priority` in-place, so the dataclass
    field stays a stable input across the simulation loop).
    """
    raw = getattr(household, "drawdown_priority", None)
    if not raw:
        return list(_PRIORITY_VALID_WRAPPERS)
    seen = []
    for w in raw:
        if not isinstance(w, str):
            continue
        if w not in _PRIORITY_VALID_WRAPPERS:
            continue
        if w in seen:
            continue
        seen.append(w)
    for w in _PRIORITY_VALID_WRAPPERS:
        if w not in seen:
            seen.append(w)
    return seen


def _draw_pension_for_amount(
    household,
    amount,
    p1_gross,
    p2_gross,
    p1_tax_result_top,
    p2_tax_result_top,
):
    """Run the Pension waterfall (PCLS / UFPLS) for `amount` from
    the household's DC pot. Returns a 5-tuple
    `(tax_free_draw, taxable_draw, ufpls_take_home, p1_tax_result,
    p2_tax_result)`. Mutates `household.person1.dc_pot`,
    `household.person2.dc_pot`, `household.person1.pcls_taken`,
    `household.person2.pcls_taken`.

    Factored out of `run_simulation` so the outer step-7 loop can
    walk the user's `drawdown_priority` list IN ORDER — i.e.
    Pension only fires for the residual after the asset walk when
    it's not first in the list. The `amount` parameter is the
    residual shortfall at the time of the Pension iteration (NOT
    the full year-0 deficit as the pre-PR engine used), so the
    25%-PCLS preference is applied to the actual pension
    withdrawal, not the gross deficit.

    Preserved invariants from the pre-PR Pension block:
      * `actual_ufpls = min(ufpls_requested, total_dc_at_start)` —
        cap at ACTUAL DC pot (the core phantom-UFPLS fix).
      * Pro-rate PCLS / taxable onto the cap so the 25%-PCLS
        preference is preserved on a partial draw.
      * Per-spouse share of the ACTUAL draw (HMRC's rule: tax
        follows the pension that crystallised the UFPLS).
      * Per-spouse tax recompute uses `*_top` baseline so
        `tax_free_income` and `ufpls_taxable_net` correctly
        reflect the additional tax vs. the no-UFPLS top-of-year
        figure.

    Returns a 7-tuple:
      `(tax_free_draw, taxable_draw, ufpls_take_home,
        p1_taxable_taken, p2_taxable_taken,
        p1_tax_result, p2_tax_result)`

    `p1_taxable_taken` / `p2_taxable_taken` let the engine's
    multi-pass waterfall accumulate cumulative per-spouse
    taxable drawdown across multiple Pension calls, then do
    ONE correct tax recompute at the end (prevents later-pass
    incremental-amount tax results from overwriting earlier-pass
    correct tax).
    """
    p1_remaining = (
        household.person1.pcls_available
        - household.person1.pcls_taken
    )
    single_retiree = bool(getattr(household, "single_retiree", False))
    p2_remaining = 0.0 if single_retiree else (
        household.person2.pcls_available
        - household.person2.pcls_taken
    )
    max_tax_free_this_year = amount * 0.25
    tax_free_draw_requested = min(
        max_tax_free_this_year,
        max(0, p1_remaining + p2_remaining),
    )
    taxable_draw_requested = max(
        0, amount - tax_free_draw_requested
    )
    ufpls_requested = (
        tax_free_draw_requested + taxable_draw_requested
    )

    # ----- Cap UFPLS at ACTUAL DC pot — the core fix ---------
    # Without this, the engine charged UFPLS income tax on
    # `taxable_draw_requested` £ even when DC was empty, which
    #   (a) reduced the post-tax income line on phantom draws,
    #   (b) created the double-PA illusion biasing the line UP
    #       once total_dc hit zero.
    total_dc_at_start = household.person1.dc_pot
    if not single_retiree:
        total_dc_at_start += household.person2.dc_pot
    actual_ufpls = min(ufpls_requested, total_dc_at_start)

    # Pro-rate PCLS / taxable onto the cap so the 25%-PCLS
    # preference is preserved as much as possible on a partial
    # draw. When nothing was capped (full draw possible), the
    # scaling factor is 1 and the requested values pass through
    # unchanged.
    if ufpls_requested > 0 and actual_ufpls < ufpls_requested:
        scaling = actual_ufpls / ufpls_requested
        tax_free_draw = tax_free_draw_requested * scaling
        taxable_draw = taxable_draw_requested * scaling
    else:
        tax_free_draw = tax_free_draw_requested
        taxable_draw = taxable_draw_requested

    # ----- Per-spouse share of the ACTUAL draw ----------------
    # Each partner pays tax on their own UFPLS drawdown and the
    # engine reduces their pot in the same proportion — HMRC's
    # rule is the tax follows the pension that crystallised the
    # UFPLS. Zero shares when there is nothing to draw from.
    if total_dc_at_start > 0 and actual_ufpls > 0:
        p1_share = household.person1.dc_pot / total_dc_at_start
        p2_share = (
            0.0
            if single_retiree
            else household.person2.dc_pot / total_dc_at_start
        )
        household.person1.dc_pot -= actual_ufpls * p1_share
        if not single_retiree:
            household.person2.dc_pot -= actual_ufpls * p2_share
        p1_taxable_taken = taxable_draw * p1_share
        p2_taxable_taken = taxable_draw * p2_share
    else:
        p1_taxable_taken = 0.0
        p2_taxable_taken = 0.0

    # ----- PCLS consumption bookkeeping -----------------------
    # `pcls_taken` advances by the (pro-rated) tax-free amount;
    # P1's allowance is used first, then P2's. `pcls_available`
    # is fixed at retirement (see step 1b above).
    if tax_free_draw > 0:
        if p1_remaining >= tax_free_draw:
            household.person1.pcls_taken += tax_free_draw
        else:
            household.person1.pcls_taken += max(0, p1_remaining)
            if not single_retiree:
                household.person2.pcls_taken += max(
                    0, tax_free_draw - p1_remaining
                )

    # ----- Tax recompute with ACTUAL UFPLS draw ---------------
    new_p1_tax = uk_income_tax(
        p1_gross, taxable_drawdown=p1_taxable_taken
    )
    new_p2_tax = uk_income_tax(
        p2_gross, taxable_drawdown=p2_taxable_taken
    )

    # Take-home contribution from UFPLS taxable portion = gross
    # draw minus the additional income tax it triggered vs the
    # top-of-year no-UFPLS baseline captured as `*_top`. This is
    # what populates the queued UFPLS segment of the stacked bar.
    p1_tax_on_ufpls = max(
        0.0, new_p1_tax["tax"] - p1_tax_result_top["tax"]
    )
    p2_tax_on_ufpls = max(
        0.0, new_p2_tax["tax"] - p2_tax_result_top["tax"]
    )
    ufpls_take_home = (
        p1_taxable_taken + p2_taxable_taken
        - p1_tax_on_ufpls - p2_tax_on_ufpls
    )

    return (
        tax_free_draw,
        taxable_draw,
        ufpls_take_home,
        p1_taxable_taken,
        p2_taxable_taken,
        new_p1_tax,
        new_p2_tax,
    )
