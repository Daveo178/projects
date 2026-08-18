"""`pages/0_Quick_Estimate.py` — Aviva-style landing for Simple mode.

WHY THIS PAGE EXISTS
====================
The user observed that
https://www.direct.aviva.co.uk/myfuture/RetirementPlanner/YourSavings is a
clean, narrow pension-trajectory tool — single user, today's money, one
bar chart — and noted that ours had grown to 13 pages with 60+ inputs.
They asked: instead of adding yet another toggle, **ship a distinct
landing page** that gives the Aviva-style simplicity, while the existing
13-page planner stays as the detailed alternative.

Result: this file. It's the default landing for new users in Simple
mode. Supports either one retiree or a couple, today's-money only by design,
single bar chart output, with a single primary CTA:

    Run Quick Estimate

which saves the form values + runs the simulation + renders the
result. The household-data dict it writes to is the EXACT SAME dict
that the detailed planner reads on /pages/1_Home.py — so the user's
quick-estimate guesses flow into the detailed app the moment they
flip into Detailed mode via the sidebar radio.

DESIGN DECISIONS
================

1. **Today's-money only**: the engine's `show_in_todays_value` flag
   is forced to True at run time (via the `show_in_todays_value=True`
   kwarg to `build_household_from_session_state`). The Detailed
   planner keeps the toggle for back-compat, but this page is
   unambiguous: every £ is today's purchasing power.

2. **Compact input form**: only the fields a casual user can
   reasonably estimate. Each partner gets date-of-birth / retirement
   date / State Pension age / DC pot / DB income. One row for assets.
   One row for mortgage. One row for spending + end age. The detailed
   toggle on the Pensions / Assets pages still exposes every advanced
   slider — they're just hidden behind a mode flip.

3. **One chart only**: a stacked-bar chart of household asset
   composition at milestone ages (today, Person 1 retires, Person 1    State Pension age, optional Person 2 State Pension age, plan-end age). The
   `simulation/charts.py::net_worth_composition_chart` helper gives
   us per-class series, so we just melt them and stack them on
   milestone ages. Mortgage balance overlaid as a separate line.

4. **Single primary CTA**: a green "💰 Run Quick Estimate" button
   that DOES TWO THINGS — saves the household_data dict AND runs
   `run_simulation(...)`. No separate Save click; matches the
   Aviva one-button flow.

5. **Bottom hint to the detailed pages**: at the very bottom of
   the page, a one-line pointer tells the user to open the other
   sidebar pages for the deeper views (tax, Monte Carlo, etc.).

USAGE
=====
Streamlit auto-discovers `pages/0_*.py` and puts them at the TOP of
the sidebar nav (because `0` sorts before `1` — `pages/1_Home.py`
currently sits at position 0 of the user's sidebar). The user opens
the app → "Quick Estimate" is the first sidebar link. They enter
basics → "Run Quick Estimate" → see one chart. They click "Switch
to Detailed →" if they want the 13-page deep planner.
"""
from __future__ import annotations

import streamlit as st
from datetime import date, timedelta
from brand_chrome import apply_chrome

import hashlib
from dataclasses import dataclass

import pandas as pd
import altair as alt

from simulation.engine import run_simulation
from simulation.years_and_months import (
    format_age_label,
    get_p1_current_age,
    _compute_age_from_dob,
    _years_from_dates,
)
from storage import init_household, save_household, has_saved_plan
from pages_helpers.household_builder import build_household_from_session_state
from pages_helpers.global_controls import render_global_controls_sidebar
from model_defaults import (
    default_partner_dict,
    default_asset_dict,
    default_mortgage_dict,
)
from pages_helpers.personal_employer_contrib import (
    render_personal_employer_contrib_block,
    resolve_legacy_after_save,
)

# -----------------------------------------------------------
# Page-level setup — chrome + state seed + sidebar widget
# -----------------------------------------------------------
# `st.set_page_config` is hoisted to the very top so the browser tab
# title reflects the Quick Estimate branding without flashing. Same
# `apply_chrome()` injection every other page uses so brand styles
# propagate uniformly.
st.set_page_config(
    page_title="Quick Estimate — Couples' Retirement Planner",
    layout="wide",
)
apply_chrome()

# Seed household_data from disk on first visit, mirroring `main.py`.
init_household(st.session_state)

render_global_controls_sidebar()

# -----------------------------------------------------------
# Page header — keep compact; this page should feel Aviva-light.
# -----------------------------------------------------------
st.title("🟢 Quick Estimate")

# Compact intro paragraph (2 short lines max). No `st.write(...)`
# boilerplate; users have asked for "simpler content display" and
# wordy intros are exactly what triggered that feedback.
st.write(
    "**A simple at-a-glance view of where you'll stand financially at "
    "retirement.** Enter the basics below, then hit **Run Quick "
    "Estimate** for one bar chart of your household wealth at every "
    "key age. All figures are in **today's money**."
)

# ----------------------------------------------------------------------------
# Soft seed: if the user hasn't visited the detailed planner yet, populate
# household_data with the model defaults so the widgets below have sensible
# slider values instead of zeros. Mirrors the "TestDcCompound / TestMonteCarlo"
# pattern of building a Household from defaults when no saved plan exists.
# ----------------------------------------------------------------------------
data = st.session_state.household_data
if "person1" not in data:
    data["person1"] = default_partner_dict("Person 1", p1=True)
if "person2" not in data:
    data["person2"] = default_partner_dict("Person 2", p1=False)

# Assets — start with one of each ISA / GIA / Cash / Property so the
# Quick Estimate form lands with the same per-wrapper row structure
# the Detailed Assets page uses. Value defaults are 0 so a brand-new
# user doesn't see scary placeholder numbers.
if "assets" not in data or not isinstance(data["assets"], list):
    data["assets"] = [
        default_asset_dict("ISA", "ISA"),
        default_asset_dict("Cash", "Cash"),
        default_asset_dict("GIA", "GIA"),
        default_asset_dict("Property", "Property"),
    ]

# Mortgage — `include_in_spending` defaults to False so the
# `Home` chart doesn't combine mortgage + lifestyle by surprise.
if "mortgage" not in data or not isinstance(data["mortgage"], dict):
    data["mortgage"] = default_mortgage_dict()

# Spending has no decimal default; 0 is the dataclass default and
# is honest ("you haven't entered any spending yet" rather than a
# fabricated annual figure that the user might mistake for their
# own number).
data.setdefault("spending", 0)
data.setdefault("end_age", 95.0)
data.setdefault("drawdown_strategy", "Fixed")
data.setdefault("cash_buffer", False)
data.setdefault("single_retiree", False)
data.setdefault("life_expectancy_end_age", 95.0)
data.setdefault("inflation_rate", 0.025)

# A single-retiree plan keeps any Person 2 inputs in the saved plan so
# switching back to a couple is lossless, but the simulation layer treats
# Person 2 as inactive while this toggle is on. This is deliberately set
# before the partner widgets so the user's choice is part of the same
# household state written by Run Quick Estimate.
single_retiree = st.toggle(
    "Plan for one retiree (ignore Person 2)",
    value=bool(data.get("single_retiree", False)),
    key="qe_single_retiree",
    help=(
        "When enabled, Person 2's entered wages, contributions, DC pot, "
        "DB pension, and State Pension are all excluded from the "
        "projection. Person 2's saved inputs are retained so you can "
        "switch back to a couple later."
    ),
)
data["single_retiree"] = bool(single_retiree)
if single_retiree:
    st.info(
        "Single-retiree mode is on. Person 2's saved inputs are retained "
        "but ignored, including any State Pension that would otherwise "
        "start at Person 2's State Pension age."
    )


# ----------------------------------------------------------------------------
# Per-partner contribution widgets are now in
# `pages_helpers/personal_employer_contrib.py::render_personal_employer_contrib_block`
# so both this page and the detailed Pensions page stay in sync.
# ----------------------------------------------------------------------------


# -----------------------------------------------------------
# Section 1 — Person 1 and optional Person 2. ONE row per partner.
# -----------------------------------------------------------
# Two columns side-by-side, each a partner card. Compact: 5 base
# fields per partner (age, retirement age, state pension age, DC
# pot, DB income) + the DC contribution block. Numbers only —
# every advanced field (growth rates, AA taper, drawdown
# priority) is hidden behind the Detailed mode flip.
#
# Per-page field parity with Pensions (Page 2)
# ─────────────────────────────────────────────
# The Pensions page exposes additional fields the Quick Estimate
# also covers as compact widgets so users see what's been
# configured without flipping modes:
#
#   * `pcls_percent`        — tax-free % of DC at first draw
#                             (Aviva-style simplicity kept by
#                             using a slider with 5% steps).
#   * `draw_age`            — DB pension start age (independent
#                             from retirement_age; defaults to 60
#                             to match the UK scheme minimum).
#   * `income_until_retirement` — annual wages while working;
#                             drives the Spending-page pre-
#                             retirement cash-flow deficit
#                             banner.
#
# These three are SHARED with Pensions page via
# `data["person1"]` / `data["person2"]` — edits on either page
# are persisted to disk and re-loaded by the next visit. Streamlit
# widget session_state is per-key and sticky after first render,
# so the cross-page edit auto-shows here only AFTER a hard reload
# or after clicking the "↻ Refresh from saved" button below
# (which pulls the latest values into every qe_* key in one go).
# -----------------------------------------------------------
st.subheader("👫 Person 1 and Person 2")

# Map (widget session_state key) -> (partner_num, source field on
# `data["person{N}"]`, transform). Used by the Refresh button below
# to copy fresh values from data into qe_* session_state keys
# without iterating every widget manually. Three transform types:
#
#   * `"int"` / `"float"`  — direct read of `data[person][field]`,
#                            cast to the matching Python type.
#                            PCLS is `int` because the slider reads
#                            whole-percent values; everything else
#                            is `float` to match the number_inputs.
#   * `"pct_x100"`        — slider reads percent (0-50%); data
#                            stores a fraction (0-0.5). Multiply
#                            by 100 to land on the right slider
#                            position.
#   * `"flat"`            — number_input reads £/month, same units
#                            as data — no scaling, just float-cast.
#   * `"mode_radio"`      — derived from BOTH the `personal_contrib_pct`
#                            and `personal_contrib_flat_monthly`
#                            fields. Sets the slider/flat-£ radio
#                            to whichever mode is currently active.
#                            The value written is the radio's OPTION
#                            LABEL — "% of income" if personal_pct is
#                            non-zero, "Flat £ per month" if
#                            personal_flat is non-zero, else
#                            "% of income" (consistent with the
#                            helper's `default_mode_index` = 0).
#                            Labels, NOT indices: `st.radio` without
#                            `format_func` stores the option string
#                            in session_state, so a raw int 0/1 would
#                            crash `_apply_widget_sync`'s float()
#                            clobber check and land outside the
#                            radio's option domain.
_QE_FIELD_TO_DATA = {
    # ── Per-partner numeric pension widgets (direct field read) ──
    # age + retirement_age are now computed from DOB / retirement_date
    # date pickers — auto-sync reads dob/retirement_date strings instead.
    "qe_p1_dob":              ("person1", "dob",                     "date_str"),
    "qe_p1_ret_date":         ("person1", "retirement_date",         "date_str"),
    "qe_p1_sp_age":           ("person1", "state_pension_age",      "float"),
    "qe_p1_dc_pot":           ("person1", "dc_pot",                 "float"),
    "qe_p1_db":               ("person1", "db_income",              "float"),
    "qe_p1_pcls":             ("person1", "pcls_percent",           "int"),
    "qe_p1_draw_age":         ("person1", "draw_age",               "float"),
    "qe_p1_income":           ("person1", "income_until_retirement", "float"),
    "qe_p2_dob":              ("person2", "dob",                     "date_str"),
    "qe_p2_ret_date":         ("person2", "retirement_date",         "date_str"),
    "qe_p2_sp_age":           ("person2", "state_pension_age",      "float"),
    "qe_p2_dc_pot":           ("person2", "dc_pot",                 "float"),
    "qe_p2_db":               ("person2", "db_income",              "float"),
    "qe_p2_pcls":             ("person2", "pcls_percent",           "int"),
    "qe_p2_draw_age":         ("person2", "draw_age",               "float"),
    "qe_p2_income":           ("person2", "income_until_retirement", "float"),
    # ── Contribution block (transform per helper-owned widget key) ──
    "qe_p1_personal_pct":     ("person1", "personal_contrib_pct",          "pct_x100"),
    "qe_p1_personal_flat":    ("person1", "personal_contrib_flat_monthly", "flat"),
    "qe_p1_employer_pct":     ("person1", "employer_contrib_pct",          "pct_x100"),
    "qe_p1_contrib_mode":     ("person1", None,                            "mode_radio"),
    "qe_p2_personal_pct":     ("person2", "personal_contrib_pct",          "pct_x100"),
    "qe_p2_personal_flat":    ("person2", "personal_contrib_flat_monthly", "flat"),
    "qe_p2_employer_pct":     ("person2", "employer_contrib_pct",          "pct_x100"),
    "qe_p2_contrib_mode":     ("person2", None,                            "mode_radio"),
}

# -----------------------------------------------------------
# Cross-page auto-sync (replaces the previous "↻ Refresh values
# from saved plan" button).
# -----------------------------------------------------------
# Fires transparently on every render at the TOP of Section 1
# (BEFORE any `key=` widget renders — see the spending widget's
# key-safety comment for the constraint). No user click required:
# the moment `data["person*"]` is updated by Pensions page save,
# the home-page Run button, the Apply-as-spending button, or
# any other save path, the next Quick Estimate render pulls the
# new values into each per-partner widget session_state.
#
# Behaviour
# ──────────
# 1. Compute a fingerprint of the TRACKED subset of each partner
#    dict (the 11 fields that have matching qe_* widgets).
# 2. Compare the fingerprint to `_qe_data_fp` in session_state.
#    If the fingerprint is unchanged since last render, the
#    auto-sync is a no-op (no widget_key writes at all).
# 3. If the fingerprint has changed (data was updated externally),
#    walk each tracked widget:
#
#      a. Compute the value we want to write from
#         `data[person_key][field]` via the same transform map
#         as the previous Refresh button (`int` / `float` /
#         `pct_x100` / `flat` / `mode_radio`).
#      b. Compare the widget's CURRENT value to
#         `_qe_seen_<wkey>`, the value we last synced into that
#         widget. If they differ by more than floating-point
#         noise, the user has typed something on Quick Estimate
#         that hasn't been saved yet — their typing wins
#         (clobber protection). When they match, the widget is
#         untouched since the last sync, so an external data
#         change propagates through safely.
#      c. Otherwise, write the new value into BOTH
#         `st.session_state[wkey]` AND `_qe_seen_<wkey>` so the
#         next render's fingerprint-check has an up-to-date
#         baseline.
#
# 4. After the loop, stamp `_qe_data_fp` with the current
#    fingerprint so the next render's check is stable.
#
# The "user hasn't typed since last sync" guard
# ────────────────────────────────────────────
# Without the `_qe_seen_<wkey>` baseline, every data change would
# clobber the user's typed-but-unsaved values — a regression.
# The fingerprint+seen-baseline combination delivers the original
# "auto-update on cross-page change" UX WITHOUT that risk.
#
# Streamlit key-safety
# ────────────────────
# Widget keys (`qe_p1_*` etc.) can ONLY be written to BEFORE the
# corresponding widget has rendered (Streamlit raises
# `StreamlitAPIException: ... cannot be modified after ...
# instantiated` otherwise). This block sits BEFORE all
# `st.number_input(..., key="qe_p1_*")` calls in Section 1.
# -----------------------------------------------------------

def _hash_subset(d, subset_keys, prefix=""):
    """Stable md5 hash of (prefix, sorted-keys, d[k] for k in subset).

    Pure-stdlib: avoids importing json to hash dict-shaped state.
    `repr()` is used for deterministic nested-object representation
    (None / int / float / str / bool); lists/tuples would also work
    but the engine only stores numbers and strings in
    `data["person*"]`, so this codepath is plenty.
    """
    if not isinstance(d, dict):
        return ""
    h = hashlib.md5(prefix.encode())
    for k in sorted(subset_keys):
        h.update(repr(k).encode())
        h.update(
            repr(d.get(k) if isinstance(d, dict) else None).encode()
        )
    return h.hexdigest()


def _hash_assets_list(assets_list, prefix="assets"):
    """Stable md5 hash of an assets-list-of-dicts shape.

    The engine stores `data["assets"]` as a LIST (not a dict),
    indexed positionally — but each list entry is a self-
    contained asset dict with an `asset_type` discriminator
    ("ISA" / "GIA" / "Cash" / "Property"). To fingerprint
    this shape deterministically, we:

      1. Filter to dict-typed entries (skip list-level noise
         from a bad migration).
      2. Sort by `asset_type` so dict-insertion order is
         stable across re-orderings — `repr()` of a dict
         reflects insertion order, so without the sort two
         semantically equal lists in different orders would
         hash differently.
      3. Re-nest as `{asset_type: asset_dict}` and delegate
         to `_hash_subset` so the same per-field hashing
         logic applies (we get `repr()` determinism for
         free).

    Returns "" for a non-list input (matches `_hash_subset`'s
    ""-on-non-dict contract — both 4 fingerprints end up empty
    strings for malformed state, so equality still holds).
    """
    if not isinstance(assets_list, list):
        return ""
    subset = {}
    for a in sorted(
        (x for x in assets_list if isinstance(x, dict)),
        key=lambda x: x.get("asset_type", ""),
    ):
        atype = a.get("asset_type", "")
        if atype:
            subset[atype] = a
    return _hash_subset(subset, _QE_TRACKED_KEYS_PER_ASSET, prefix)


def _build_assets_by_type_index(data):
    """Return `{asset_type: asset_dict}` from `data["assets"]`.

    Used by both the auto-sync asset loop below AND by
    `_qe_sync_data._build_asset_dict_from` later in the
    file so the index-shape lives in one place. Filters
    non-dict list entries (e.g. a malformed migration entry
    that's a bare string for some reason) so the index is
    always dict-shaped. Empty-list / no-assets users get an
    empty dict, which makes the asset-loop fall back to the
    per-row default `value=0`.
    """
    return {
        a.get("asset_type"): a
        for a in (data.get("assets") or [])
        if isinstance(a, dict)
    }


def _qe_values_differ(cur_widget, prev_value):
    """Type-agnostic clobber-protection comparison between the
    widget's CURRENT value and the value we LAST SYNCED into it
    (`_qe_seen_<wkey>`).

    Returns True when the two differ — meaning the user has
    interacted with the widget since the last sync, so their
    typing wins over the auto-sync write.

    Numeric widgets (number_input / slider) compare with a
    1e-6 float tolerance. Label-valued widgets — the
    contrib-mode radio, whose session_state holds the option
    STRING (e.g. "% of income" / "Flat £ per month") because
    `st.radio` without `format_func` returns the label —
    compare for exact string equality instead. This is what
    crash-proofs the sync loop against the mode radio:
    float("Flat £ per month") raises ValueError.

    A str-vs-numeric type mismatch between the current value
    and the baseline can only be a STALE baseline written by
    the pre-fix code (it stored an int 0/1 index for the
    contrib-mode radio while the radio's real value is the
    label string). A number_input can't hold a string and a
    radio can't hold a number, so a type mismatch never means
    genuine user typing — treated as "no difference" so the
    sync repairs the baseline on the next write instead of
    blocking the propagation forever.
    """
    if isinstance(cur_widget, str) != isinstance(prev_value, str):
        return False
    if isinstance(cur_widget, str):
        return cur_widget != prev_value
    return abs(float(cur_widget) - float(prev_value)) > 1e-6


def _apply_widget_sync(wkey, new_value):
    """Write `new_value` to `session_state[wkey]` (and remember
    it as `session_state[f"_qe_seen_{wkey}"]`) subject to
    clobber-protection.

    Skips the write if the widget's CURRENT value differs from
    the value we LAST SYNCED into it (`_qe_seen_<wkey>`; within
    1e-6 float tolerance for numeric widgets, exact string
    equality for label-valued widgets like the contrib-mode
    radio) — the user has typed-but-not-saved a value on Quick
    Estimate, so their typing wins. When the widget still holds
    the last-synced value, an external data change propagates
    through (this is what makes the Pensions-page → Quick
    Estimate auto-sync actually work). Returns True if the
    write happened, False if clobber-protection skipped it.

    Used by all three auto-sync loops (partner / asset /
    mortgage) so the clobber check + write pair lives in one
    place. Streamlit-key-safety invariant: must run BEFORE
    the corresponding widget has rendered on this script
    run.
    """
    seen_key = f"_qe_seen_{wkey}"
    prev_seen = st.session_state.get(seen_key)
    cur_widget = st.session_state.get(wkey)
    if (
        prev_seen is not None
        and cur_widget is not None
        and _qe_values_differ(cur_widget, prev_seen)
    ):
        return False
    st.session_state[wkey] = new_value
    st.session_state[seen_key] = new_value
    return True


_QE_TRACKED_KEYS_PER_PARTNER = (
    "dob",
    "retirement_date",
    "age",
    "retirement_age",
    "state_pension_age",
    "dc_pot",
    "db_income",
    "pcls_percent",
    "draw_age",
    "income_until_retirement",
    "personal_contrib_pct",
    "personal_contrib_flat_monthly",
    "employer_contrib_pct",
)


# -----------------------------------------------------------
# Per-asset-type widget sync map (extends the partner sync).
# -----------------------------------------------------------
# Each widget key maps to its `(asset_type, transform)` — the
# helper looks up the saved record in `data["assets"]` filtered
# by `asset_type` and reads the `value` field back through the
# transform. Only `"int"` is in play here — the asset widgets
# take whole-pound values and the new-value sync direction
# (data → widget) is unitless.
#
# Why we still track `growth_rate` + `contribution_until_retirement`
# in the asset fingerprint below even though they're NOT
# mirrored on Quick Estimate: the fingerprint compares the FULL
# asset dict shape, so any detailed-page edit (Assets page 3
# bumps ISA growth from 0.05 to 0.07) triggers the auto-sync
# loop. The per-asset loop only updates `value`-typed widgets
# here (the growth_rate field isn't a qe_* widget), so the loop
# itself is a no-op for non-value edits — but the fingerprint
# STAMP at the end of the loop re-baselines `_seen_fp` to the
# new asset state, so the NEXT post-edit render is stable and
# doesn't re-trigger the loop unnecessarily.
_QE_ASSET_FIELD_TO_DATA = {
    "qe_isa":      ("ISA",      "int"),
    "qe_gia":      ("GIA",      "int"),
    "qe_cash":     ("Cash",     "int"),
    "qe_property": ("Property", "int"),
}


# -----------------------------------------------------------
# Per-mortgage-field widget sync map.
# -----------------------------------------------------------
# Each widget key maps to `(field, transform)`. Transform notes:
#
#   * `qe_mort_outstanding`     — `"int"` (no scale change).
#   * `qe_mort_rate`            — `"pct_x100"` (data stores
#                                 decimal e.g. 0.0458; widget
#                                 stores percent e.g. 4.58 —
#                                 multiply by 100; same
#                                 transform that drives the
#                                 contrib-pct slider).
#   * `qe_mort_end_year`        — `"int"` (whole years; the
#                                 QE form uses years-only by
#                                 design even though the engine
#                                 supports fractional via the
#                                 Detailed Assets page).
#   * `qe_mort_payment_monthly` — `"per_month"` (data stores
#                                 ANNUAL £ via `annual_payment`
#                                 — widget stores MONTHLY £;
#                                 divide by 12, INVERSE of the
#                                 data→widget direction that
#                                 `_build_mortgage_dict_from`
#                                 uses internally with `* 12.0`).
_QE_MORTGAGE_FIELD_TO_DATA = {
    "qe_mort_outstanding":     ("outstanding",    "int"),
    "qe_mort_rate":            ("rate",           "pct_x100"),
    "qe_mort_end_year":        ("end_year",       "int"),
    "qe_mort_payment_monthly": ("annual_payment", "per_month"),
}


# Asset dict tracked keys — the FULL asset dict shape
# (every key on `models/asset.py::Asset`). The asset widgets
# only expose `value` on Quick Estimate, but the fingerprint
# hashes all 5 fields so any detailed-page edit triggers the
# auto-sync re-evaluation. Repeated sync of the unchanged
# `value` is a no-op (clobber-protected) but the fingerprint
# stamp now matches the new asset state, so the NEXT
# post-edit render is stable.
_QE_TRACKED_KEYS_PER_ASSET = (
    "name",
    "value",
    "growth_rate",
    "contribution_until_retirement",
    "asset_type",
)


# Mortgage dict tracked keys — the FULL
# `models/mortgage.py::Mortgage` dataclass (6 fields). Same
# rationale as the asset tracked keys above: track all 6 so
# any Detailed-page mortgage edit (e.g. toggling
# `include_in_spending` or bumping `annual_overpayment` on
# the Assets page 3 mortgage expander) triggers the
# auto-sync re-evaluation.
_QE_TRACKED_KEYS_PER_MORTGAGE = (
    "outstanding",
    "rate",
    "end_year",
    "annual_payment",
    "annual_overpayment",
    "include_in_spending",
)

_current_fp = (
    _hash_subset(data.get("person1") or {}, _QE_TRACKED_KEYS_PER_PARTNER, "p1"),
    _hash_subset(data.get("person2") or {}, _QE_TRACKED_KEYS_PER_PARTNER, "p2"),
    # Assets — list-of-dicts shape, NOT a dict. Delegate to the
    # dedicated helper which filters + sorts by asset_type so
    # the hash is stable across re-orderings (a bad migration
    # that re-orders the list should not trigger a spurious
    # full-asset fingerprint mismatch).
    _hash_assets_list(data.get("assets") or [], "assets"),
    # Mortgage — single dict shape, parallel to the partner
    # hashes above. Tracks all 6 Mortgage dataclass fields so
    # any detailed-page mortgage edit triggers auto-sync.
    _hash_subset(
        data.get("mortgage") or {},
        _QE_TRACKED_KEYS_PER_MORTGAGE,
        "mortgage",
    ),
)
_seen_fp = st.session_state.get("_qe_data_fp")

if _seen_fp != _current_fp:
    # Three nested sync loops — partners, then assets, then
    # mortgage. Each loop reads from a different DATA shape
    # (partner dict, asset list, mortgage dict) so they can't
    # share a loop body, but the per-widget transform dispatch
    # is identical — modulo the special `mode_radio` case
    # that's only relevant for the partner contrib block.

    # ───────────────────────── Partner loop ─────────────────────────
    # Drives the 24 `qe_p{1,2}*` pension widgets from
    # `data["person{1,2}"]` via the 5 transforms (int / float /
    # pct_x100 / flat / mode_radio). Unchanged from the prior
    # turn; see the per-transform comments below.
    for wkey, (partner_key, field, transform) in _QE_FIELD_TO_DATA.items():
        src = data.get(partner_key, {}) or {}
        # Compute the value we want to write (in WIDGET units, NOT
        # data units). Mirrors the transforms in the previous
        # Refresh button exactly.
        if transform == "int":
            new_value = int(src.get(field, 0))
        elif transform == "float":
            new_value = float(src.get(field, 0))
        elif transform == "date_str":
            # DOB / retirement_date are immutable — no clobber-protection
            # needed (no _apply_widget_sync call). Write the ISO string
            # directly. `st.date_input` accepts strings via session_state.
            raw = src.get(field, "")
            new_value = str(raw) if raw else ""
            seen_key = f"_qe_seen_{wkey}"
            st.session_state[wkey] = new_value
            st.session_state[seen_key] = new_value
            continue  # skip _apply_widget_sync (no clobber check for
                      # immutable dates — raw write mirrors the string
                      # the date picker would return anyway)
        elif transform == "pct_x100":
            # Slider reads percent (0-50%); data stores a fraction
            # (0-0.5). Multiply before assigning to session_state.
            new_value = float(src.get(field, 0.0)) * 100.0
        elif transform == "flat":
            # Number_input reads £/month, same units as data — no
            # scaling, just float-cast.
            new_value = float(src.get(field, 0.0))
        elif transform == "mode_radio":
            # "% of income" mode if personal_pct is non-zero,
            # "Flat £ per month" mode if personal_flat is
            # non-zero, else "% of income" (matches the helper's
            # `default_mode_index` fallthrough — index 0 is the
            # %-of-income option). The value written is the
            # radio's OPTION LABEL, not an index: `st.radio`
            # without `format_func` stores the option string in
            # session_state, so a raw int 0/1 would both crash
            # `_apply_widget_sync`'s float() clobber check AND
            # land outside the radio's option domain.
            pct = round(float(src.get("personal_contrib_pct", 0.0)), 6)
            flat = round(
                float(src.get("personal_contrib_flat_monthly", 0.0)), 6
            )
            new_value = (
                "% of income"
                if pct > 0
                else ("Flat £ per month" if flat > 0 else "% of income")
            )
        else:
            continue

        _apply_widget_sync(wkey, new_value)

    # ───────────────────────── Asset loop ─────────────────────────
    # Drives the 4 asset widgets (`qe_isa` / `qe_gia` /
    # `qe_cash` / `qe_property`) from the corresponding
    # asset_type row in `data["assets"]` — uses the same
    # `_saved_assets_by_type` index built in `_qe_sync_data`
    # (`{asset_type: asset_dict}`), so the iteration cost is
    # constant per asset. `transform` is only `"int"` here
    # (whole-pound values, no scaling). A brand-new user with
    # no `data["assets"]` row for some asset_type falls back
    # to an empty-dict default (`value` defaults to 0), which
    # the asset widget accepts fine.
    _saved_assets_by_type = _build_assets_by_type_index(data)
    for wkey, (asset_type, transform) in _QE_ASSET_FIELD_TO_DATA.items():
        src = _saved_assets_by_type.get(asset_type) or {}
        if not isinstance(src, dict):
            # Defensive — `_saved_assets_by_type` filtering
            # normally produces dicts only. A non-dict value
            # would mean a malformed migration; skip the sync
            # rather than crash so the partner+mortgage loops
            # still run.
            continue
        if transform == "int":
            new_value = int(src.get("value", 0))
        elif transform == "float":
            new_value = float(src.get("value", 0.0))
        else:
            continue

        _apply_widget_sync(wkey, new_value)

    # ───────────────────────── Mortgage loop ─────────────────────────
    # Drives the 4 mortgage widgets (`qe_mort_outstanding` /
    # `qe_mort_rate` / `qe_mort_end_year` /
    # `qe_mort_payment_monthly`) from `data["mortgage"]`. Uses
    # 4 transforms including the new `"per_month"` (inverse of
    # the data→widget direction used in
    # `_build_mortgage_dict_from`'s `* 12.0` line — widget reads
    # £/month, data stores annual £, so divide by 12 + round
    # to land on the widget's integer-pound scale).
    mort_src = data.get("mortgage", {}) or {}
    if isinstance(mort_src, dict):
        for wkey, (field, transform) in _QE_MORTGAGE_FIELD_TO_DATA.items():
            if transform == "int":
                new_value = int(mort_src.get(field, 0))
            elif transform == "float":
                new_value = float(mort_src.get(field, 0.0))
            elif transform == "pct_x100":
                # Rate widget reads percent (e.g. 4.58); data
                # stores decimal (e.g. 0.0458). multiply by 100.
                new_value = float(mort_src.get(field, 0.0)) * 100.0
            elif transform == "per_month":
                # Payment widget reads £/month; data stores
                # annual £ via `annual_payment`. Divide by 12 +
                # round to the integer-pound widget scale
                # (matches the `value=int(round(...))` argument
                # the `st.number_input` widget uses at
                # construction time).
                raw = float(mort_src.get(field, 0.0))
                new_value = float(round(raw / 12.0))
            elif transform == "flat":
                new_value = float(mort_src.get(field, 0.0))
            else:
                continue

            _apply_widget_sync(wkey, new_value)

    # Stamp the fingerprint ONCE at the END of all three
    # loops so a mid-loop widget-skip (user-typed) doesn't
    # accidentally re-fingerprint with partial state. The next
    # render sees a stable 4-tuple fingerprint either way.
    st.session_state["_qe_data_fp"] = _current_fp

p1_saved = data["person1"]
p2_saved = data["person2"]

col_p1, col_p2 = st.columns(2)

with col_p1:
    st.markdown("**Person 1**")
    # Date of birth — replaces old integer age input. Pre-fills from saved
    # `dob` ISO string; falls back to approximated DOB from legacy `age`.
    _d_dob_default = p1_saved.get("dob") or None
    if _d_dob_default is None and p1_saved.get("age") is not None:
        _d_dob_default = date.today() - timedelta(
            days=int(float(p1_saved["age"]) * 365.25)
        )
    d_qe_dob = st.date_input(
        "Date of birth",
        value=_d_dob_default,
        min_value=date(1930, 1, 1),
        max_value=date.today(),
        key="qe_p1_dob",
        help="Your date of birth. The app computes your current age from this automatically.",
    )
    p1_age = _compute_age_from_dob(d_qe_dob.isoformat())
    st.caption(f"Current age: **{format_age_label(p1_age)}**")
    # Retirement date — replaces old integer retirement-age input.
    _d_ret_default = p1_saved.get("retirement_date") or None
    if _d_ret_default is None and p1_saved.get("retirement_age") is not None:
        _yrs = max(0.0, float(p1_saved["retirement_age"]) - p1_age)
        _d_ret_default = date.today() + timedelta(days=int(_yrs * 365.25))
    d_qe_ret_date = st.date_input(
        "Retirement date",
        value=_d_ret_default,
        min_value=date.today(),
        max_value=date(2100, 1, 1),
        key="qe_p1_ret_date",
        help="The date you plan to stop working. The engine computes your exact retirement age.",
    )
    p1_ret_age = p1_age + _years_from_dates(
        date.today().isoformat(), d_qe_ret_date.isoformat()
    )
    p1_sp_age = st.number_input(
        "State Pension age",
        min_value=60,
        max_value=80,
        value=int(p1_saved.get("state_pension_age", 67)),
        step=1,
        key="qe_p1_sp_age",
    )
    p1_dc_pot = st.number_input(
        "DC pot (£)",
        min_value=0,
        max_value=5_000_000,
        value=int(p1_saved.get("dc_pot", 0)),
        step=1000,
        key="qe_p1_dc_pot",
    )
    p1_db = st.number_input(
        "DB pension (£ / yr)",
        min_value=0,
        max_value=200_000,
        value=int(p1_saved.get("db_income", 0)),
        step=500,
        key="qe_p1_db",
    )
    # PCLS / draw_age / income_until_retirement — the three pension
    # fields previously Quick-Estimate-only-missing. Now mirrored
    # from the Pensions page so users see a consistent picture
    # without flipping modes. PCLS is a 1%-step slider (matches
    # Pensions page so a value edited there — e.g. 20% — survives
    # a cross-page Refresh without snapping to 15% or 25%). Default
    # 0% matches Pensions page (and the dataclass default), so a
    # brand-new user sees the same value on both pages.
    p1_pcls = st.slider(
        "Tax-free PCLS (%)",
        min_value=0,
        max_value=25,
        value=int(p1_saved.get("pcls_percent", 0)),
        step=1,
        key="qe_p1_pcls",
        help=(
            "Tax-free Pension Commencement Lump Sum as a % of your DC pot. "
            "25% is the UK statutory max — the engine applies it as the "
            "tax-free slice of the first UFPLS draw, with the rest taxed as "
            "ordinary income. 1% steps match the Pensions page (2) so a "
            "value edited there doesn't snap on cross-page Refresh."
        ),
    )
    p1_draw_age = st.number_input(
        "DB pension draw age",
        min_value=50,
        max_value=80,
        value=int(p1_saved.get("draw_age", 60)),
        step=1,
        key="qe_p1_draw_age",
        help=(
            "Age at which the DB pension begins paying. Independent of "
            "retirement_age (which only gates DC contributions) — so a "
            "partner can stop working at 60 and start DB draw at 65 if "
            "they want. Defaults to 60 to match the UK scheme minimum."
        ),
    )
    p1_income = st.number_input(
        "Annual income until retirement (£ / yr)",
        min_value=0,
        max_value=500_000,
        value=int(p1_saved.get("income_until_retirement", 0)),
        step=500,
        key="qe_p1_income",
        help=(
            "Annual wages while still working (drops to 0 at retirement_age). "
            "Drives the pre-retirement cash-flow deficit warning on the Spending "
            "page (Page 4) — set to 0 if you're already retired or both partners "
            "have stopped earning."
        ),
    )
    p1_personal_pct, p1_personal_flat, p1_employer_pct, p1_touched = (
        render_personal_employer_contrib_block("qe_p1", p1_saved)
    )

with col_p2:
    st.markdown("**Person 2**")
    # Same DOB / retirement-date pattern as Person 1 above.
    _s_dob_default = p2_saved.get("dob") or None
    if _s_dob_default is None and p2_saved.get("age") is not None:
        _s_dob_default = date.today() - timedelta(
            days=int(float(p2_saved["age"]) * 365.25)
        )
    s_qe_dob = st.date_input(
        "Date of birth",
        value=_s_dob_default,
        min_value=date(1930, 1, 1),
        max_value=date.today(),
        key="qe_p2_dob",
        help="Your date of birth. The app computes your current age from this automatically.",
    )
    p2_age = _compute_age_from_dob(s_qe_dob.isoformat())
    st.caption(f"Current age: **{format_age_label(p2_age)}**")
    _s_ret_default = p2_saved.get("retirement_date") or None
    if _s_ret_default is None and p2_saved.get("retirement_age") is not None:
        _yrs = max(0.0, float(p2_saved["retirement_age"]) - p2_age)
        _s_ret_default = date.today() + timedelta(days=int(_yrs * 365.25))
    s_qe_ret_date = st.date_input(
        "Retirement date",
        value=_s_ret_default,
        min_value=date.today(),
        max_value=date(2100, 1, 1),
        key="qe_p2_ret_date",
        help="The date you plan to stop working. The engine computes your exact retirement age.",
    )
    p2_ret_age = p2_age + _years_from_dates(
        date.today().isoformat(), s_qe_ret_date.isoformat()
    )
    p2_sp_age = st.number_input(
        "State Pension age",
        min_value=60,
        max_value=80,
        value=int(p2_saved.get("state_pension_age", 67)),
        step=1,
        key="qe_p2_sp_age",
    )
    p2_dc_pot = st.number_input(
        "DC pot (£)",
        min_value=0,
        max_value=5_000_000,
        value=int(p2_saved.get("dc_pot", 0)),
        step=1000,
        key="qe_p2_dc_pot",
    )
    p2_db = st.number_input(
        "DB pension (£ / yr)",
        min_value=0,
        max_value=200_000,
        value=int(p2_saved.get("db_income", 0)),
        step=500,
        key="qe_p2_db",
    )
    # See Person 1's pcls/draw_age/income above for rationale on the
    # 3 pension fields shared with the Pensions page. PCLS uses
    # 1%-step granularity + 0% default to match Pensions page so
    # cross-page Refresh is lossless (no value snapping).
    p2_pcls = st.slider(
        "Tax-free PCLS (%)",
        min_value=0,
        max_value=25,
        value=int(p2_saved.get("pcls_percent", 0)),
        step=1,
        key="qe_p2_pcls",
        help=(
            "Tax-free Pension Commencement Lump Sum as a % of your DC pot. "
            "25% is the UK statutory max — the engine applies it as the "
            "tax-free slice of the first UFPLS draw, with the rest taxed as "
            "ordinary income. 1% steps match the Pensions page (2) so a "
            "value edited there doesn't snap on cross-page Refresh."
        ),
    )
    p2_draw_age = st.number_input(
        "DB pension draw age",
        min_value=50,
        max_value=80,
        value=int(p2_saved.get("draw_age", 60)),
        step=1,
        key="qe_p2_draw_age",
        help=(
            "Age at which the DB pension begins paying. Independent of "
            "retirement_age (which only gates DC contributions) — so a "
            "partner can stop working at 60 and start DB draw at 65 if "
            "they want. Defaults to 60 to match the UK scheme minimum."
        ),
    )
    p2_income = st.number_input(
        "Annual income until retirement (£ / yr)",
        min_value=0,
        max_value=500_000,
        value=int(p2_saved.get("income_until_retirement", 0)),
        step=500,
        key="qe_p2_income",
        help=(
            "Annual wages while still working (drops to 0 at retirement_age). "
            "Drives the pre-retirement cash-flow deficit warning on the Spending "
            "page (Page 4)."
        ),
    )
    p2_personal_pct, p2_personal_flat, p2_employer_pct, p2_touched = (
        render_personal_employer_contrib_block("qe_p2", p2_saved)
    )

# -----------------------------------------------------------
# Section 2 — Savings and property.
# -----------------------------------------------------------
# Four-column compact row. Each row maps onto an asset in the
# detailed Assets page; this single row hides the contribution &
# growth-rate sliders that are also on the detailed page (user can
# edit those once they flip into Detailed mode).
# -----------------------------------------------------------
st.subheader("💰 Savings and property")

col_isa, col_gia, col_cash, col_property = st.columns(4)


def _read_asset_value(asset_type: str) -> int:
    """Read the current value of one asset_type from session_state.

    Returns 0 when no asset of that type exists yet (a brand-new
    user lands with the form pre-seeded to ISA/GIA/Cash/Property
    zero defaults, so this almost-always reads `0` until the user
    types something).
    """
    for a in data.get("assets", []):
        if isinstance(a, dict) and a.get("asset_type") == asset_type:
            return int(a.get("value", 0))
    return 0


with col_isa:
    isa_value = st.number_input(
        "ISA (£)",
        min_value=0,
        max_value=5_000_000,
        value=_read_asset_value("ISA"),
        step=500,
        key="qe_isa",
    )
with col_gia:
    gia_value = st.number_input(
        "GIA (£)",
        min_value=0,
        max_value=5_000_000,
        value=_read_asset_value("GIA"),
        step=500,
        key="qe_gia",
    )
with col_cash:
    cash_value = st.number_input(
        "Cash (£)",
        min_value=0,
        max_value=5_000_000,
        value=_read_asset_value("Cash"),
        step=500,
        key="qe_cash",
    )
with col_property:
    property_value = st.number_input(
        "Property (£)",
        min_value=0,
        max_value=5_000_000,
        value=_read_asset_value("Property"),
        step=5_000,
        key="qe_property",
    )

# -----------------------------------------------------------
# Section 3 — Mortgage.
# -----------------------------------------------------------
# Compact row: outstanding balance + rate + years remaining +
# monthly payment. End_year is the only legacy-years-only field
# (years + months precision is exposed on the Detailed Assets page;
# the Quick Estimate page intentionally keeps years-only to match
# the Aviva simplicity).
# -----------------------------------------------------------
mort_saved = data.get("mortgage", {}) or {}

with st.expander("🏠 Mortgage (optional)", expanded=False):
    col_outstanding, col_rate, col_endyear, col_monthly = st.columns(4)
    with col_outstanding:
        mort_outstanding = st.number_input(
            "Outstanding (£)",
            min_value=0,
            max_value=5_000_000,
            value=int(mort_saved.get("outstanding", 0)),
            step=500,
            key="qe_mort_outstanding",
        )
    with col_rate:
        mort_rate = st.number_input(
            "Rate (%)",
            min_value=0.0,
            max_value=15.0,
            value=float(mort_saved.get("rate", 0.04)) * 100,
            step=0.1,
            key="qe_mort_rate",
            help="Annual mortgage interest rate. Used to compute balance amortisation.",
        ) / 100
    with col_endyear:
        mort_end_year = st.number_input(
            "Years remaining",
            min_value=0,
            max_value=50,
            value=int(mort_saved.get("end_year", 10)),
            step=1,
            key="qe_mort_end_year",
        )
    with col_monthly:
        mort_payment_monthly = st.number_input(
            "Monthly payment (£)",
            min_value=0,
            max_value=20_000,
            value=int(
                round(mort_saved.get("annual_payment", 0) / 12)
            ),
            step=50,
            key="qe_mort_payment_monthly",
            help="Capital + interest paid each month. The engine annualises to per-year payment.",
        )
    mort_overpayment = 0  # Quick Estimate doesn't expose overpayments (avoids clutter)
    mort_include_in_spending = bool(
        mort_saved.get("include_in_spending", False)
    )

# -----------------------------------------------------------
# Section 4 — Lifestyle & plan.
# -----------------------------------------------------------
# Annual spending is the BIG slider on Aviva's tool. Plan-end-age
# defaults to 95 (≈p10 mortality for a 55-year-old couple) but
# exposed so the user can shorten / extend it explicitly.
# -----------------------------------------------------------
st.subheader("🎯 Lifestyle & plan horizon")

# Inflation assumption is now a global sidebar slider
# (`pages_helpers/global_controls.py`) — no per-page slider needed.
# The sidebar writes to `data["inflation_rate"]` on every render;
# `_qe_sync_data` below preserves it in the save dict automatically.

col_spending, col_endage, col_growth = st.columns(3)
with col_spending:
    spending = st.number_input(
        "Annual spending in today's money (£ / yr)",
        min_value=0,
        max_value=200_000,
        value=int(data.get("spending", 35_000)),
        step=500,
        # NOTE: no `key=` here on purpose. The Spending page (4)
        # also omits the key on its matching widget — and for the
        # same reason: a widget WITH a key owns the session_state
        # slot, so any external write to `st.session_state["qe_…"]`
        # raises `StreamlitAPIException: … cannot be modified
        # after the widget … is instantiated`. Without a key the
        # widget re-reads `value=int(data.get("spending", 35_000))`
        # on every render — so when the calculator's Apply button
        # updates `data["spending"]` + calls `st.rerun()`, the
        # widget naturally picks up the new value on the next
        # render without us touching session_state.
        help="How much you plan to spend each year in retirement, in TODAY's pounds. "
             "This is the headline driver of the chart below — try changing it by "
             "£5,000 to see how your plan responds.",
    )
with col_endage:
    end_age = st.number_input(
        "Plan until age (joint life, last to die)",
        min_value=18,
        max_value=120,
        value=int(data.get("life_expectancy_end_age", 95)),
        step=1,
        key="qe_end_age",
        help="The plan funds BOTH partners until whichever one reaches this age. "
             "95 is a typical UK upper bound for a 55-year-old couple.",
    )
with col_growth:
    # Simplified investment growth rate — Aviva-style single slider
    # that applies to ALL DC pots AND ISA/GIA assets at once. The
    # Detailed Pensions/Assets pages still expose per-asset/per-partner
    # growth-rate sliders; this one overrides them on Quick Estimate
    # Run/Calculate so Simple-mode users get one knob instead of five.
    # Cash and Property growth rates are NOT affected (Cash stays at
    # 2%, Property at 0% — both mirror model_defaults).
    _saved_growth_pct = float(data.get("person1", {}).get("dc_growth_rate", 0.05)) * 100
    investment_growth_rate = st.slider(
        "Investment growth (% per year)",
        min_value=0.0,
        max_value=10.0,
        value=_saved_growth_pct,
        step=0.5,
        key="qe_investment_growth",
        help=(
            "Average annual investment growth applied to ALL DC pensions "
            "AND ISA/GIA savings. Default 5% reflects a long-run balanced "
            "portfolio. Cash savings and property growth are NOT affected — "
            "they use their own defaults (2% and 0% respectively)."
        ),
    ) / 100  # slider reads percent; data stores decimal (0.05 = 5%)

# -----------------------------------------------------------
# PartnerWidgets payload — typed wrapper for the per-partner
# widget values `_qe_sync_data._persist_partner` consumes.
# -----------------------------------------------------------
# Replaces the prior 13-positional `_persist_partner` signature
# whose parameter order was easy to misalign at future call
# sites (a silent swap of `p_db` and `p_dc_pot` would corrupt
# net-worth projections without raising). Field names drop the
# `p_` prefix because they describe the INPUT widget value the
# closure receives — the OUTPUT dict shape (DB income named
# `db_income`, PCLS named `pcls_percent`) is documented on
# `_persist_partner` itself.
#
# Field ordering convention:
#   1. `saved_data` first so it reads as a context blob (used
#      for BC legacy fields + cross-page growth-rate reads)
#      separately from the page-local widget values that follow.
#   2. Numeric pension widget fields in the same order they
#      render on Section 1 (age, retirement_age, state_pension_age,
#      dc_pot, db, pcls, draw_age, income_until_retirement).
#   3. Contribution-block floats + sticky `contrib_touched`
#      flag at the tail so the Contrib helper's 4 outputs stay
#      adjacent and easy to reason about.
# -----------------------------------------------------------
@dataclass
class PartnerWidgets:
    saved_data: dict            # `data["person1"]` / `data["person2"]` slice
    # Date strings (ISO format) from `st.date_input` — persisted alongside
    # the computed float ages so date pickers pre-fill on the next visit.
    # No defaults — both call sites always pass these explicitly.
    dob: str
    retirement_date: str
    # Numeric pension fields — `float` (NOT `int`) to hedge a possible
    # Streamlit-version drift. Computed from DOB/retirement_date.
    age: float
    retirement_age: float
    state_pension_age: float
    dc_pot: float                 # numeric_input step=1000 (renamed `body stays explicit`)
    db_income: float              # DB income £/yr (previously `db`)
    # `pcls_percent` is the ONLY int — the slider is whole-percent and
    # downstream PCLS consumers (`simulation/drawdown.py`) expect an
    # integer BPERC. If Streamlit ever returns `float` for it, round
    # here rather than relaxing the downstream contract.
    pcls_percent: int             # PCLS slider step=1 (whole-percent)
    draw_age: float
    income_until_retirement: float  # £/yr wages while still working
    personal_pct: float         # personal_contrib_pct (fraction 0-0.5)
    personal_flat: float        # personal_contrib_flat_monthly £/mth
    employer_pct: float         # employer_contrib_pct (fraction 0-0.5)
    contrib_touched: bool       # sticky flag from contrib helper


# -----------------------------------------------------------
# AssetWidgets payload — typed wrapper for the per-asset
# widget values `_qe_sync_data._build_asset_dict_from` consumes.
# -----------------------------------------------------------
# One shared dataclass across all four asset types (ISA / GIA /
# Cash / Property). Each call site passes the SPECIFIC saved
# record for its asset_type via `saved_asset` so the helper can
# read `growth_rate` / `contribution_until_retirement` from
# the user's actual saved value rather than overwriting with
# the page's hard-coded defaults (this fixes a parallel bug
# to the prior partner-growth-rate fix: Assets-page edits to
# `growth_rate` / `contribution_until_retirement` were
# silently clobbered on every Quick Estimate Run click).
#
# Field ordering convention:
#   1. `saved_asset` first — the BC blob the helper reads to
#      non-QE-exposed fields (`growth_rate`,
#      `contribution_until_retirement`).
#   2. `asset_type` second — indexes which "row" of
#      `data["assets"]` this widget represents so the helper
#      knows the right default `growth_rate` to fall back on
#      if the saved record lacks one (0.05 for ISA / GIA, 0.02
#      for Cash, 0.0 for Property — matches
#      `model_defaults.default_asset_dict`).
#   3. `value` last — the only true widget input on Quick
#      Estimate for assets (a single `st.number_input` per
#      asset_type).
# -----------------------------------------------------------
@dataclass
class AssetWidgets:
    saved_asset: dict          # `data["assets"][i]` slice for one asset_type
    asset_type: str            # "ISA" / "GIA" / "Cash" / "Property"
    value: float               # from `st.number_input` step=500 (or 5000 for Property)


# -----------------------------------------------------------
# MortgageWidgets payload — typed wrapper for the per-mortgage
# widget values `_qe_sync_data._build_mortgage_dict_from`
# consumes.
# -----------------------------------------------------------
# All five QE mortgage form fields (outstanding / rate /
# end_year / payment-monthly / include_in_spending) live on
# the dataclass. `payment_monthly` stores the RAW widget value
# in £/month — the helper multiplies by 12 internally so the
# persisted `annual_payment` stays in the same annual cadence
# the engine / Mortgage dataclass expect. `annual_overpayment`
# is intentionally NOT a widget field on Quick Estimate (no
# QE widget for it) — the helper reads it from `saved_data`
# directly so a Detailed-page edit survives a Run click just
# like the partner growth-rate fields do.
#
# Field ordering convention:
#   1. `saved_data` first — the BC blob the helper reads
#      non-QE-exposed fields from (`annual_overpayment`).
#   2. Numeric mortgage widget fields in the same order they
#      render on Section 3 (outstanding, rate, end_year,
#      payment_monthly) — all `float` to hedge a possible
#      Streamlit-version drift that re-introduces `float`
#      returns from `st.number_input(..., step=1)` (the helper
#      still coerces `float(payload.outstanding)` etc., so
#      the float-coercion remains idempotent whether the
#      widget returns `int` or `float`).
#   3. `include_in_spending` last — a `bool` from the saved
#      record, NOT a QE widget (no checkbox on Quick
#      Estimate; keep it). The Detailed Mortgage expander
#      exposes the checkbox if the user wants to flip it.
# -----------------------------------------------------------
@dataclass
class MortgageWidgets:
    saved_data: dict           # `data["mortgage"]` slice
    outstanding: float         # from `st.number_input`
    rate: float                # from `st.number_input`
    end_year: float            # from `st.number_input`
    payment_monthly: float     # raw monthly widget (helper annualises)
    include_in_spending: bool  # from saved record (no QE widget)


# -----------------------------------------------------------
# Shared helper — mirror the Quick Estimate widgets into the
# `data` dict. Defined AFTER all widgets render so the closure
# captures every page-local widget value (`p1_age`, `isa_value`,
# `spending`, etc.) without parameter-list explosion. Used by
# both the Run button (Section 5) and the maximum-sustainable
# calculator (Section 4b below).
# -----------------------------------------------------------
def _qe_sync_data(data):
    """Mutate `data` in place to mirror the current widget values.

    Closure captures: p1_saved, p1_age, p1_ret_age, p1_sp_age,
    p1_dc_pot, p1_db, p1_personal_pct, p1_personal_flat,
    p1_employer_pct, p1_touched (and the same for p2), plus
    isa/gia/cash/property_value, mort_outstanding / mort_rate /
    mort_end_year / mort_payment_monthly / mort_overpayment /
    mort_include_in_spending, spending, end_age.

    This helper MUTATES `data` only — it does NOT save to disk
    or trigger a rerun. Callers layer persistence policy on top:
    Run button additionally calls `save_household(data)` + the
    simulation; the calculator additionally calls the bisection
    solver.

    Helper is intentionally IDEMPOTENT: calling it twice on the
    same page render produces the same `data` mutations (so a
    user clicking Calculate then Run sees consistent state).
    """

    def _persist_partner(name: str, payload: PartnerWidgets) -> dict:
        """Flatten ONE partner's `PartnerWidgets` payload into the
        per-partner dict shape the engine / AA helpers expect.

        The legacy `monthly_contrib_pct` / `monthly_contrib`
        fields are kept on the output dict for BC; `resolve_legacy_after_save`
        decides whether to wipe or preserve them based on
        `payload.contrib_touched` from the contribution block
        (the explicit-zero BC fix).

        The 3 added pension fields (`pcls` / `draw_age` / `income`)
        are SHARED with the Pensions page — editing them on
        Pensions page (2) updates `data["person*"]` and the
        auto-sync at the top of Section 1 picks the new values
        up on the next render.

        `payload.contrib_touched` is **sticky within the
        session** — once the user has interacted with any
        contribution widget the flag stays True for the rest
        of the session so a sub-sequent save (after the user
        edited something else) still honours the prior
        explicit intent. Resets to False only on a fresh
        session/tab load. See
        `pages_helpers/personal_employer_contrib.py::_mark_touched`
        for the set-on-interaction wiring.

        OUTPUT dict shape (matches `models/person.py::Person`
        dataclass 1:1 — every key here is a Person field):
            name, age, retirement_age, state_pension_age,
            dc_pot, db_income, pcls_percent, draw_age,
            income_until_retirement, income_growth_rate,
            monthly_contrib, monthly_contrib_pct,
            personal_contrib_pct, personal_contrib_flat_monthly,
            employer_contrib_pct, dc_growth_rate,
            db_growth_rate, state_pension_growth_rate

        The 4 growth-rate fields are read from
        `payload.saved_data` (PartnerWidgets.saved_data) so
        Pensions-side edits to those rates survive a Quick
        Estimate Run / Apply click — they did NOT survive
        before this round (see #<issue>). All other fields
        come from page-local widget values via the dataclass.
        """
        new_legacy_pct, new_legacy_flat = resolve_legacy_after_save(
            personal_pct=payload.personal_pct,
            personal_flat=payload.personal_flat,
            employer_pct=payload.employer_pct,
            user_touched=payload.contrib_touched,
            saved_legacy_pct=payload.saved_data.get("monthly_contrib_pct", 0.0),
            saved_legacy_flat=payload.saved_data.get("monthly_contrib", 0.0),
        )
        # Simplified investment growth rate — the Section 4 slider
        # overrides dc_growth_rate for both partners. Captured from
        # the page-level slider via closure (same pattern as `spending`
        # and `end_age`). The Detailed Pensions page's per-partner
        # dc_growth_rate survives only if the user edits it there AND
        # doesn't re-run Quick Estimate (the slider always writes on
        # Run click, matching Aviva's one-knob convention).
        dc_growth_override = float(investment_growth_rate)
        return {
            "name": name,
            "dob": payload.dob,
            "age": float(payload.age),
            "retirement_date": payload.retirement_date,
            "retirement_age": float(payload.retirement_age),
            "state_pension_age": float(payload.state_pension_age),
            "dc_pot": float(payload.dc_pot),
            "db_income": float(payload.db_income),
            "pcls_percent": int(payload.pcls_percent),
            "draw_age": float(payload.draw_age),
            "income_until_retirement": float(payload.income_until_retirement),
            "income_growth_rate": float(payload.saved_data.get("income_growth_rate", 0.025)),
            "monthly_contrib": new_legacy_flat,
            "monthly_contrib_pct": new_legacy_pct,
            "personal_contrib_pct": float(payload.personal_pct),
            "personal_contrib_flat_monthly": float(payload.personal_flat),
            "employer_contrib_pct": float(payload.employer_pct),
            "dc_growth_rate": dc_growth_override,
            "db_growth_rate": float(payload.saved_data.get("db_growth_rate", 0.025)),
            "state_pension_growth_rate": float(payload.saved_data.get("state_pension_growth_rate", 0.025)),
        }

    # -----------------------------------------------------------
    # _build_asset_dict_from — flatten one AssetWidgets payload
    # into the canonical 5-key asset dict shape the engine /
    # `models/asset.py::Asset` dataclass expect.
    # -----------------------------------------------------------
    # Reads `growth_rate` and `contribution_until_retirement`
    # from `payload.saved_asset` so user edits to those fields
    # on the Detailed Assets page (3) survive a Quick Estimate
    # Run / Calculate click. Falls back to per-type defaults
    # matching `model_defaults.default_asset_dict` (0.05 for
    # ISA / GIA, 0.02 for Cash, 0.0 for Property) only when
    # the saved record lacks the field — e.g. a brand-new
    # user pre-seeded by `data["assets"]` seed in Section 2.
    # -----------------------------------------------------------
    def _build_asset_dict_from(payload: AssetWidgets) -> dict:
        # Per-asset-type fallback for `growth_rate` — mirrors
        # `model_defaults.default_asset_dict` choice. Property
        # is 0.0 not 0.05 because the asset-page default
        # deliberately sets Property to 0% (matches the
        # today's-money zeroing convention that strips
        # inflation from property capital appreciation).
        default_growth = {
            "ISA": 0.05,
            "GIA": 0.05,
            "Cash": 0.02,
            "Property": 0.0,
        }.get(payload.asset_type, 0.05)
        return {
            "name": payload.asset_type,
            "value": float(payload.value),
            # Investment growth rate from the Section 4 slider —
            # overrides saved growth_rate for ISA / GIA assets only.
            # Cash and Property keep their own defaults (2% and 0%
            # respectively) because they're not investment vehicles.
            # Captured from the page-level slider via closure.
            "growth_rate": float(
                investment_growth_rate
                if payload.asset_type in ("ISA", "GIA")
                else payload.saved_asset.get("growth_rate", default_growth)
            ),
            "contribution_until_retirement": float(
                payload.saved_asset.get(
                    "contribution_until_retirement", 0.0
                )
            ),
            "asset_type": payload.asset_type,
        }

    # -----------------------------------------------------------
    # _build_mortgage_dict_from — flatten one MortgageWidgets
    # payload into the canonical 6-key mortgage dict shape the
    # engine / `models/mortgage.py::Mortgage` dataclass expect.
    # -----------------------------------------------------------
    # Reads `annual_overpayment` from `payload.saved_data` so
    # a Detailed-page edit to it survives a Quick Estimate Run
    # click (parallels the partner / asset growth-rate fix).
    # Annualises `payment_monthly` internally so the persisted
    # `annual_payment` matches the engine's annual cadence.
    # -----------------------------------------------------------
    def _build_mortgage_dict_from(payload: MortgageWidgets) -> dict:
        return {
            "outstanding": float(payload.outstanding),
            "rate": float(payload.rate),
            "end_year": float(payload.end_year),
            "annual_payment": float(payload.payment_monthly) * 12.0,
            "annual_overpayment": float(
                payload.saved_data.get("annual_overpayment", 0.0)
            ),
            "include_in_spending": bool(payload.include_in_spending),
        }

    data["person1"] = _persist_partner(
        "Person 1",
        PartnerWidgets(
            saved_data=p1_saved,
            dob=d_qe_dob.isoformat(),
            retirement_date=d_qe_ret_date.isoformat(),
            age=p1_age,
            retirement_age=p1_ret_age,
            state_pension_age=p1_sp_age,
            dc_pot=p1_dc_pot,
            db_income=p1_db,
            pcls_percent=p1_pcls,
            draw_age=p1_draw_age,
            income_until_retirement=p1_income,
            personal_pct=p1_personal_pct,
            personal_flat=p1_personal_flat,
            employer_pct=p1_employer_pct,
            contrib_touched=p1_touched,
        ),
    )
    data["person2"] = _persist_partner(
        "Person 2",
        PartnerWidgets(
            saved_data=p2_saved,
            dob=s_qe_dob.isoformat(),
            retirement_date=s_qe_ret_date.isoformat(),
            age=p2_age,
            retirement_age=p2_ret_age,
            state_pension_age=p2_sp_age,
            dc_pot=p2_dc_pot,
            db_income=p2_db,
            pcls_percent=p2_pcls,
            draw_age=p2_draw_age,
            income_until_retirement=p2_income,
            personal_pct=p2_personal_pct,
            personal_flat=p2_personal_flat,
            employer_pct=p2_employer_pct,
            contrib_touched=p2_touched,
        ),
    )
    # Index the saved `data["assets"]` list by `asset_type` so
    # each `_build_asset_dict_from` call can look up the
    # corresponding saved record (with `growth_rate` /
    # `contribution_until_retirement` already on it) without
    # re-iterating the list. Empty / bad entries are filtered
    # out — a future migration that introduces a new
    # `asset_type` will land here as the empty-dict default,
    # which the helper falls back to the per-type default
    # `growth_rate` cleanly.
    _saved_assets_by_type = _build_assets_by_type_index(data)
    data["assets"] = [
        _build_asset_dict_from(
            AssetWidgets(
                saved_asset=_saved_assets_by_type.get("ISA", {}),
                asset_type="ISA",
                value=isa_value,
            )
        ),
        _build_asset_dict_from(
            AssetWidgets(
                saved_asset=_saved_assets_by_type.get("GIA", {}),
                asset_type="GIA",
                value=gia_value,
            )
        ),
        _build_asset_dict_from(
            AssetWidgets(
                saved_asset=_saved_assets_by_type.get("Cash", {}),
                asset_type="Cash",
                value=cash_value,
            )
        ),
        _build_asset_dict_from(
            AssetWidgets(
                saved_asset=_saved_assets_by_type.get("Property", {}),
                asset_type="Property",
                value=property_value,
            )
        ),
    ]
    data["mortgage"] = _build_mortgage_dict_from(
        MortgageWidgets(
            saved_data=mort_saved,
            outstanding=mort_outstanding,
            rate=mort_rate,
            end_year=mort_end_year,
            payment_monthly=mort_payment_monthly,
            include_in_spending=mort_include_in_spending,
        )
    )
    data["spending"] = float(spending)
    data["life_expectancy_end_age"] = float(end_age)
    data["drawdown_strategy"] = "Fixed"   # Quick Estimate always uses Fixed
    data["cash_buffer"] = bool(data.get("cash_buffer", False))
    data["inflation_rate"] = float(
        data.get("inflation_rate", 0.025)
    )


# -----------------------------------------------------------
# Section 4b — Maximum-sustainable-spending calculator.
# -----------------------------------------------------------
# Inverse of the `spending` widget above: instead of asking the
# user to TYPE a spending figure and learning afterwards whether
# the plan can sustain it (forward direction), the user picks a
# TARGET AGE and we solve for the highest annual spending that
# exactly depletes household wealth to £0 at that age (inverse).
#
# Why it lives on Quick Estimate (not just the detailed Spending
# page)
# ────────────────────────────────────────
# The user explicitly asked for a "Quick Estimate — what's the
# max I can spend?" affordance on the landing page. Most casual
# users never flip into Detailed mode; if the calculator is
# buried on Page 4 it never gets used. The Quick Estimate
# constraint set (today's-money + Fixed strategy) maps verbatim
# to the same solver the Spending page uses, so the math is
# bit-identical — just the wrapper is on the landing page.
#
# Quick-Estimate-specific constraints honoured here:
#   * Always Fixed strategy (`_qe_sync_data` hard-codes this).
#   * Always today's-money mode (the helper kwarg
#     `show_in_todays_value=True` forces this for the in-memory
#     Household dataclass — same flag the Run block uses).
#   * Persists NOTHING to disk on Calculate (matches page-4
#     explicit-save UX: casual Calculate clicks don't overwrite
#     the user's persisted spending figure).
#   * Apply CTA updates `data["spending"]` AND saves to disk
#     because it's a deliberate "I'm committing" action — the
#     user can hover on the payoff line to see what changed
#     before clicking Run to refresh the chart.
# -----------------------------------------------------------
with st.expander(
    "🎯 Find maximum sustainable spending for a target age (optional)",
    expanded=False,
):
    st.caption(
        "Pick a **target age** and click **Calculate** to find the "
        "highest annual spending (in today's pounds) that exactly "
        "depletes your household wealth at that age. Use **Apply** "
        "to set your spending target from the result."
    )
    st.caption(
        "**Always Fixed + today's money on Quick Estimate** — the "
        "Detailed Spending page (Page 4) lets you switch strategies "
        "and currency modes if you want more flexibility."
    )

    # Initialise session_state target_age once so a re-render
    # doesn't snap the widget back to the default. Default =
    # `life_expectancy_end_age` (the age the simulation currently
    # plans to) so the first click answers the "what's the max I
    # can sustainably spend to my current plan-end-age?" question
    # without forcing the user to type.
    if "qe_calc_target_age" not in st.session_state:
        st.session_state["qe_calc_target_age"] = float(
            data.get("life_expectancy_end_age", 95.0)
        )

    _calc_target_age = st.number_input(
        "Target age",
        min_value=18,
        max_value=120,
        value=int(st.session_state["qe_calc_target_age"]),
        step=1,
        key="qe_calc_target_age_widget",
        help=(
            f"Reference age at which your household's wealth should "
            f"reach £0. Default: your current plan-end-age of "
            f"{int(data.get('life_expectancy_end_age', 95))}. "
            f"Set earlier (e.g. 85) for a 'longevity cushion' — set "
            f"later (e.g. 100) to maximise spend at the cost of "
            f"leaving wealth on the table."
        ),
    )
    # Mirror the value back to the model-state key so the next
    # render reads it WITHOUT re-snapshotting from `data`.
    st.session_state["qe_calc_target_age"] = float(_calc_target_age)

    # Calculate button — does NOT save to disk; only stashes the
    # result in session_state so a subsequent re-render (user
    # changed target_age, etc.) doesn't lose it.
    if st.button(
        "Calculate maximum sustainable spending",
        type="primary",
        use_container_width=True,
        key="qe_calc_sustainable",
        help=(
            "Bisects on terminal net worth — ~1 second typical "
            "(18-25 iterations). Does NOT save to disk; click "
            "'Apply as my annual spending' below to commit."
        ),
    ):
        # Mirror the CURRENT widget values into the data dict so
        # `build_household_from_session_state` reads them. The
        # helper is idempotent: re-running it on a re-render
        # produces the same mutations.
        _qe_sync_data(data)
        # Build the in-memory Household dataclass with today's-
        # money mode forced via the helper kwarg — mirrors the
        # Run block's exact contract so the solver sees the same
        # numbers the chart would render.
        _hh_for_solver = (
            build_household_from_session_state(show_in_todays_value=True)
        )
        from simulation.sustainable_spending import (
            find_max_sustainable_spending,
        )
        with st.spinner("Solving for max-sustainable spend…"):
            _result = find_max_sustainable_spending(
                _hh_for_solver, float(_calc_target_age)
            )
        st.session_state["qe_sustainable_last_result"] = _result
        st.session_state["qe_sustainable_last_target_age"] = (
            float(_calc_target_age)
        )

    # Result panel — paints only on a fresh solve AND the persisted
    # target_age still matches the widget's current value (0.5 yr
    # tolerance for the rounded-widget vs float-session_state
    # boundary). Mismatch means the user changed target_age without
    # clicking Calculate again — we hide the result rather than
    # show stale numbers from a previous solve.
    _last_result = st.session_state.get(
        "qe_sustainable_last_result"
    )
    _last_target = st.session_state.get(
        "qe_sustainable_last_target_age", None
    )
    if (
        _last_result is not None
        and _last_target is not None
        and abs(float(_last_target) - float(_calc_target_age)) < 0.5
    ):
        if _last_result.error:
            st.error(f"❌ {_last_result.error}")
        else:
            # Big number headline — inline HTML keeps the
            # bold-green colour treatment across Streamlit themes
            # (light mode is now permanent so a fixed colour is
            # fine).
            _headline_html = (
                f"<div style='font-size:1.6rem;font-weight:700;"
                f"line-height:1.2;color:#1f7a3d;margin-bottom:0.25em'>"
                f"£{_last_result.max_spending_gbp:,.0f}/yr</div>"
            )
            st.markdown(_headline_html, unsafe_allow_html=True)
            if _last_result.converged:
                st.success(
                    f"✅ Sustainable to **age "
                    f"{int(round(float(_calc_target_age)))}** — "
                    f"{_last_result.iterations_used} solver "
                    f"iterations, ±£200 precision, Fixed strategy "
                    f"+ today's money."
                )
            else:
                st.warning(
                    f"⚠️ **£{_last_result.max_spending_gbp:,.0f}/yr** "
                    f"— best estimate after "
                    f"{_last_result.iterations_used} iterations "
                    f"(did not fully converge within ±£200 "
                    f"precision; pick a closer target age for "
                    f"tighter numbers)."
                )
            st.caption(
                f"Terminal net worth at age "
                f"{int(round(float(_calc_target_age)))} when "
                f"spending at this rate: "
                f"**£{_last_result.terminal_net_worth_gbp:,.0f}** "
                f"(target £0). Simulated "
                f"{_last_result.iterations_used} times."
            )

            # Apply CTA — primary "I'm committing" button. Saves
            # to disk AND updates data["spending"] so the spending
            # widget above re-displays the new value on the next
            # render (its `value=` default reads from `data`). The
            # chart doesn't refresh until the user clicks Run —
            # that's intentional so a casual Calculate click
            # doesn't accidentally churn the rendered chart.
            if st.button(
                "Apply as my annual spending",
                type="primary",
                use_container_width=True,
                key="qe_apply_sustainable",
                help=(
                    "Updates Annual household spending above AND "
                    "keeps it in this session. Hit Run Quick Estimate "
                    "to refresh the chart with the new spending."
                ),
            ):
                _new_spending = float(_last_result.max_spending_gbp)
                data["spending"] = _new_spending
                save_household(data)
                # The spending widget above has NO `key=` — so it
                # re-reads `value=int(data.get("spending", …))` on
                # every render, picking up the new value naturally
                # on `st.rerun()`. (An earlier version of this
                # block tried to set `st.session_state["qe_spending"]
                # = _new_spending` directly, which raised
                # `StreamlitAPIException: ... cannot be modified
                # after the widget with key qe_spending is
                # instantiated` because Streamlit widgets with a
                # key own that session-state slot once instantiated.
                # Removing `key="qe_spending"` from the widget
                # removed the ownership conflict and is the same
                # pattern the Spending page (4) uses.)
                #
                # Pop the result so the panel collapses to its
                # default state on the next render — the spending
                # widget now shows the new value, so the user can
                # either hit Calculate again to re-prove the
                # answer or just hit Run to see the chart.
                st.session_state.pop(
                    "qe_sustainable_last_result", None
                )
                st.session_state.pop(
                    "qe_sustainable_last_target_age", None
                )
                st.success(
                    f"Annual spending set to "
                    f"£{_last_result.max_spending_gbp:,.0f} "
                    f"and applied — hit **Run Quick Estimate** "
                    f"to refresh the chart."
                )
                st.rerun()


# -----------------------------------------------------------
# Save & Run — single primary CTA.
# -----------------------------------------------------------
# Aviva-style one-button flow. Writes household_data dict AND
# triggers the simulation. Persisting the data on click means the
# next time the user opens the app (in any mode) the same numbers
# are loaded from disk.
# -----------------------------------------------------------
_run_clicked = st.button(
    "💰 Run Quick Estimate",
    type="primary",
    use_container_width=True,
    key="qe_run",
    help="Runs the simulation in today's money and keeps your inputs in this session.",
)

if _run_clicked:
    # Mirror widget values into `data` (idempotent; same
    # mutations the Calculate button would produce). The shared
    # helper means Calculate-then-Run and Run-then-Calculate
    # produce the SAME household_data dict shape so the chart
    # matches the result panel.
    _qe_sync_data(data)

    # Quick Estimate is today's-money-only by design. Persist the mode so
    # the Monte Carlo and detailed pages start from the same currency basis
    # after the user runs this page.
    data["show_in_todays_value"] = True
    save_household(data)
    st.success("Plan ready — running simulation in today's money…")

    # Run the simulation in today's-value mode. The flag is
    # forced to True via the helper kwarg so any prior drift in
    # the in-memory dataclass state doesn't accidentally turn
    # the Quick Estimate into a nominal-mode run.
    household = build_household_from_session_state(show_in_todays_value=True)
    results = run_simulation(household)
    st.session_state.simulation_results = results
    st.session_state.quick_estimate_results = results
    st.rerun()


# -----------------------------------------------------------
# Results block — only paints if a simulation has been run.
# -----------------------------------------------------------
results = (
    st.session_state.get("quick_estimate_results")
    or st.session_state.get("simulation_results")
)

if results is not None:
    st.divider()

    # INFLATION STRIPPED badge — identical wording to
    # `view_badge._BadgeText` so the user sees consistent
    # messaging between Quick Estimate and Detailed pages
    # when both are in today's money.
    if results.get("view_mode") == "today":
        st.info(
            "📉 **INFLATION STRIPPED** — figures shown are in today's "
            "purchasing power. Mortgage interest still applies; "
            "property value growth is zeroed; DB pension and State "
            "Pension stay flat at their year-0 base figures; DC pot "
            "and other asset growth use real (= nominal − inflation) "
            "rates."
        )

    # Summary metric cards — three big numbers for at-a-glance
    # reading. The "today" card is gross wealth today; the
    # "joint-life" card is the gross wealth at the simulation's
    # end (the last year). A red/green sustainability chip
    # summarises whether the plan runs out before the end.
    sim_years = len(results["years"])
    p1_current_age = get_p1_current_age(data)
    last_age = p1_current_age + sim_years - 1

    # Net worth at today / retirement (Person 1) / SP-age allow
    # comparison across the milestone columns in the bar chart
    # below.
    today_nw = results["net_worth"][0] if sim_years > 0 else 0
    final_nw = results["net_worth"][-1] if sim_years > 0 else 0

    col_now, col_end, col_status = st.columns(3)
    with col_now:
        st.metric(
            f"💎 Net worth today (age {format_age_label(p1_current_age)})",
            f"£{int(round(today_nw)):,}",
        )
        # Explain the headline figure in the same place as the metric.
        # The engine's first stored point is the first projected period,
        # so it can differ from the raw values typed into the form: DC and
        # other assets have moved, and the mortgage balance has amortised.
        today_dc = results.get("dc_pot", [0.0])[0]
        today_other_assets = sum(
            results.get(key, [0.0])[0]
            for key in (
                "isa_value",
                "gia_value",
                "cash_value",
                "property_value",
            )
        )
        today_mortgage = results.get("mortgage_balance", [0.0])[0]
        st.caption(
            "**How this is calculated:** pension pots + ISA/GIA/cash/"
            "property − mortgage. This is the first projected point in "
            "today's money, so it includes the first period's growth, "
            "contributions and mortgage repayment; it is not just the raw "
            "figures entered above."
        )
        st.caption(
            f"£{today_dc:,.0f} pensions + £{today_other_assets:,.0f} "
            f"other assets − £{today_mortgage:,.0f} mortgage "
            f"= **£{today_nw:,.0f} net worth**."
        )
    with col_end:
        st.metric(
            f"💎 Net worth at age {format_age_label(last_age)}",
            f"£{int(round(final_nw)):,}",
            delta=f"{int(round(final_nw - today_nw)):,}",
            delta_color=(
                "normal" if final_nw >= today_nw else "inverse"
            ),
        )
    with col_status:
        if final_nw < 0:
            st.error("⚠️ Plan runs out before end age")
        else:
            st.success("✅ Plan sustains through end age")

    # -----------------------------------------------------------
    # ONE chart — net worth composition at milestone ages.
    # -----------------------------------------------------------
    # The engine already exposes per-class series (ISA / GIA / Cash
    # / Property / DC Pension) plus a mortgage_balance line. We
    # pick milestone ages from the simulation horizon rather
    # than plotting every year (cleaner, matches the Aviva
    # "summarised at the end" pattern). Mortgage is overlaid as
    # a separate line because it's debt, not an asset.
    # -----------------------------------------------------------
    st.subheader("📊 Your household income by source, at every age")

    # Plot EVERY simulation year individually (not a 6-step milestone
    # grid) so the user can read the year-by-year transitions
    # between Earned / DB Pension / State Pension / Asset Drawdown
    # sources — every retirement step (DB draw, retirement, state-
    # pension start, asset-drawdown onset) shows as a discrete
    # bar segment rather than being averaged into a neighbouring
    # milestone. With ~30-40 categories on the x-axis, bars are
    # sized narrow (size=8) to fit without overlap; rotated labels
    # + length limits keep long age labels readable.
    if sim_years <= 1:
        offsets = [0]
    else:
        offsets = list(range(sim_years))

    # Build the LONG-form melted-frame the bar chart needs.
    # Each segment is PRE-TAX £/yr from a single income source.
    # Replaces the earlier "wealth composition + capitalised
    # pension promises" stack — every segment is now in £/yr so
    # the viewer compares like-with-like ("where does each £ of
    # my income come from this year?"). Previously the DB /
    # State Pension promise segments mixed a £/yr stream
    # capitalised across many years (e.g. £10k/yr × 25y =
    # £250k of "promise") with actually-spendable ISA / GIA /
    # Cash / Property / DC pot, which read as indistinguishable
    # on the bar and confused the user.
    EARNED = results.get("earned_income", [0.0] * sim_years)
    DB_PAYOUT = results.get("db_payout", [0.0] * sim_years)
    STATE_PAYOUT = results.get("state_payout", [0.0] * sim_years)
    # Asset-derived PRE-TAX £/yr at each age — sum the per-source
    # draw series on a GROSS basis so the whole stack is genuinely
    # pre-tax (matching the chart title). 25% PCLS tax-free slice
    # + 75% taxable UFPLS GROSS + ISA / GIA / Cash draws (these
    # wrappers are not taxed at drawdown). Income tax is NOT
    # carved out of the segments — the caption explains that the
    # bars must clear the (net) spending line by roughly the tax
    # + NI due.
    UFPLS_FREE = results.get("tax_free_income", [0.0] * sim_years)
    UFPLS_GROSS = results.get(
        "ufpls_taxable_gross", [0.0] * sim_years
    )
    ISA_DRAW = results.get("isa_draw", [0.0] * sim_years)
    GIA_DRAW = results.get("gia_draw", [0.0] * sim_years)
    CASH_DRAW = results.get("cash_draw", [0.0] * sim_years)
    ASSET_DRAW = [
        UFPLS_FREE[i] + UFPLS_GROSS[i]
        + ISA_DRAW[i] + GIA_DRAW[i] + CASH_DRAW[i]
        for i in range(sim_years)
    ]
    INCOME_SOURCE_COLUMNS = [
        "Earned",
        "DB Pension",
        "State Pension",
        "Asset Drawdown",
    ]
    year_rows = []
    for offset in offsets:
        age_value = p1_current_age + offset
        age_label = format_age_label(age_value)
        row = {
            "Offset": offset,
            "AgeLabel": age_label,
            "Earned": float(EARNED[offset]),
            "DB Pension": float(DB_PAYOUT[offset]),
            "State Pension": float(STATE_PAYOUT[offset]),
            "Asset Drawdown": float(ASSET_DRAW[offset]),
        }
        year_rows.append(row)
    year_df = pd.DataFrame(year_rows)
    melted = year_df.melt(
        id_vars=["AgeLabel"],
        value_vars=INCOME_SOURCE_COLUMNS,
        var_name="Source",
        value_name="£/yr",
    )

    peak_total = (
        melted.groupby("AgeLabel")["£/yr"].sum().max()
    )
    spending_value = float(data.get("spending", 0))
    # Y-axis upper bound — fit both the highest stacked bar
    # AND the spending reference line so the dashed line never
    # clips off the top. With spending=0 (degenerate "you
    # haven't entered any spending yet" case) skip the
    # spending-based ceiling so a sparse default doesn't
    # inflate the y-axis.
    y_axis_max = max(
        peak_total * 1.05,
        spending_value * 1.1 if spending_value > 0 else 0,
        1.0,
    )

    bar = (
        alt.Chart(melted)
        .mark_bar(size=8)
        .encode(
            # Categorical x-axis (one discrete bar per year).
            # `labelAngle=-45` + `labelLimit=80` keeps age labels
            # readable when ~30-40 categories compete for axis
            # space; altair auto-skips overlapping labels by
            # default. Title now reads "Age (every year)" to
            # surface the granularity change from the previous
            # 6-milestone view.
            x=alt.X(
                "AgeLabel:O",
                title="Age (every year)",
                sort=None,
                axis=alt.Axis(labelAngle=-45, labelLimit=80),
            ),
            y=alt.Y(
                "£/yr:Q",
                stack="zero",
                title="Pre-tax household income (£ / year, today's money)",
                scale=alt.Scale(
                    domain=[0, y_axis_max], nice=False
                ),
                axis=alt.Axis(format=",.0f"),
            ),
        color=alt.Color(
            "Source:N",
            sort=INCOME_SOURCE_COLUMNS,
            scale=alt.Scale(scheme="category10"),
            title="Income source",
            legend=alt.Legend(orient="right"),
        ),
            order=alt.Order(
                "color_N_order:Q", sort="ascending"
            ),
        tooltip=[
            "AgeLabel",
            "Source",
            alt.Tooltip(
                "£/yr:Q", title="£/yr", format=",.0f"
            ),
        ],
        )
        .properties(height=440)
    )

    # Annual-spending reference line — a horizontal red dashed
    # line at the household's year-0 spending target so the
    # viewer can immediately see "do my income sources meet
    # the dashed line?" at each milestone age. Quick Estimate
    # always runs in Fixed strategy + today's-money mode, so
    # the £/yr figure is constant across all ages. In nominal
    # mode or with strategy ≠ Fixed this would be a per-age
    # step-line, but those modes aren't reached on this page.
    first_age = (
        year_df["AgeLabel"].iloc[0]
        if len(year_df) > 0
        else format_age_label(p1_current_age)
    )
    last_age = (
        year_df["AgeLabel"].iloc[-1]
        if len(year_df) > 0
        else first_age
    )
    spending_df = pd.DataFrame({
        "AgeLabel": [first_age, last_age],
        "Annual Spending": [
            spending_value, spending_value
        ],
    })
    spending_line = (
        alt.Chart(spending_df)
        .mark_line(
            color="#c0392b",
            strokeWidth=3,
            strokeDash=[6, 4],
        )
        .encode(
            x=alt.X("AgeLabel:O", sort=None),
            y=alt.Y("Annual Spending:Q"),
            tooltip=[
                alt.Tooltip(
                    "Annual Spending:Q",
                    title="Annual spending (£/yr)",
                    format=",.0f",
                ),
            ],
        )
    )

    combined_chart = (
        alt.layer(bar, spending_line)
        .resolve_scale(y="shared")
        .properties(height=440)
    )
    st.altair_chart(combined_chart, use_container_width=True)
    st.caption(
        "Stacked bars at every age show your household's "
        "**annual pre-tax income by source** — Earned (wages, "
        "working years), DB Pension (from your DB draw age), "
        "State Pension (from your State Pension age), and Asset "
        "Drawdown (PCLS / UFPLS from your DC pot + ISA / GIA / "
        "Cash drawn to bridge any shortfall). **All segments are "
        "pre-tax**, so the bars sit above the dashed red **net "
        "spending target** line by roughly the income tax + "
        "National Insurance due — after tax, what you keep lands "
        "on the dashed line (the engine targets your after-tax "
        "income to cover your spending exactly). If your spending "
        "figure already includes the mortgage (the \"Include "
        "mortgage in spending\" toggle on the Assets page), the "
        "bars land on the target throughout; otherwise the "
        "mortgage is funded on top of spending, so the bars sit "
        "higher while it is active. In working years wages may "
        "exceed spending. All figures in pre-tax \u00a3 per year "
        "in today's purchasing power."
    )

    # -----------------------------------------------------------
    # Bottom hint — where to go next for more depth.
    # -----------------------------------------------------------
    st.divider()
    st.markdown(
        "🔬 **Want tax view, Monte Carlo, scenarios, or \"what-if\" "
        "sensitivity?** Use the **sidebar** — every other page is "
        "a deeper view of this same plan (same saved data)."
    )
else:
    # Pre-run hint: tell the user what to do next. Single line
    # so it doesn't compete with the form above. Mirrors the
    # Aviva tool's "Click calculate" prompt.
    st.caption(
        "👆 Hit **Run Quick Estimate** above to see your wealth at "
        "every key age."
    )


# -----------------------------------------------------------
# Worst-case footer — explicit persistence hint + a tiny
# "first visit?" indicator. Mirrors `main.py`'s caption but
# tuned for the Quick Estimate page context.
# -----------------------------------------------------------
if has_saved_plan(st.session_state):
    st.caption(
        "💾 Your plan is held in this browser session (in-memory) — "
        "download it from the Home page to keep a personal copy."
    )
else:
    st.caption(
        "ℹ️ No plan yet — your inputs live in this browser session "
        "and can be downloaded from the Home page."
    )
