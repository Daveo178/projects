"""`pages/3_Assets.py` — Assets page (detail-only).

The asset VALUES (ISA / GIA / Cash / Property balances) and the
headline mortgage figures (outstanding balance, years remaining,
monthly payment) are entered on the **Quick Estimate** page
(`pages/0_Quick_Estimate.py`), which is the single basis for the
calculation. This page holds ONLY the advanced asset detail:
per-asset growth rates, ongoing contributions until retirement,
mortgage overpayments / fractional term, the chart-display flag,
and the cash-buffer planning mode.
"""
import streamlit as st
from brand_chrome import apply_chrome

from simulation.years_and_months import (
    _split_years_into_years_and_months,
    _format_years_months_caption,
)
from storage import init_household, save_household
from pages_helpers.global_controls import render_global_controls_sidebar

st.title("📊 Assets — Growth & detail")

apply_chrome()
render_global_controls_sidebar()

st.caption(
    "Asset and mortgage VALUES are entered on the **Quick Estimate** "
    "page — this page refines the **growth rates**, ongoing "
    "contributions, and mortgage overpayments."
)

# ----------------------------------------
# 1. Initialise session_state — seed from disk on first visit
# ----------------------------------------
init_household(st.session_state)

data = st.session_state.household_data
assets_saved = data.get("assets", [])
mort_saved = data.get("mortgage", {}) or {}


def get_asset_field(asset_type, field, default=0.0):
    for a in assets_saved:
        if isinstance(a, dict) and a.get("asset_type") == asset_type:
            return float(a.get(field, default))
    return float(default)


isa_growth_default_pct = round(
    get_asset_field("ISA", "growth_rate", 0.05) * 100, 2
)
gia_growth_default_pct = round(
    get_asset_field("GIA", "growth_rate", 0.05) * 100, 2
)
cash_growth_default_pct = round(
    get_asset_field("Cash", "growth_rate", 0.00) * 100, 2
)
property_growth_default_pct = round(
    get_asset_field("Property", "growth_rate", 0.02) * 100, 2
)

isa_contrib_default = get_asset_field("ISA", "contribution_until_retirement", 0)
gia_contrib_default = get_asset_field("GIA", "contribution_until_retirement", 0)
cash_contrib_default = get_asset_field("Cash", "contribution_until_retirement", 0)

# ----------------------------------------
# 2. Growth rates + ongoing contributions
# ----------------------------------------
st.subheader("📈 Growth rates & ongoing contributions")

isa_growth_pct = st.slider(
    "ISA annual growth (%)",
    0.0, 15.0,
    isa_growth_default_pct,
    step=0.1,
    key="isa_growth_pct",
    help=(
        "Average annual investment growth applied to the ISA balance "
        "every year of the simulation. Default 5% reflects a long-run "
        "balanced portfolio."
    ),
) / 100
isa_contrib = st.number_input(
    "Annual ISA contribution until retirement (£)",
    0.0, 200_000.0, isa_contrib_default,
    help=(
        "Added every year while at least one partner is still working. "
        "Stops once both have retired."
    ),
)

gia_growth_pct = st.slider(
    "GIA annual growth (%)",
    0.0, 15.0,
    gia_growth_default_pct,
    step=0.1,
    key="gia_growth_pct",
    help=(
        "Average annual investment growth applied to the GIA balance "
        "every year of the simulation."
    ),
) / 100
gia_contrib = st.number_input(
    "Annual GIA contribution until retirement (£)",
    0.0, 200_000.0, gia_contrib_default,
    help=(
        "Added every year while at least one partner is still working. "
        "Stops once both have retired."
    ),
)

cash_growth_pct = st.slider(
    "Cash savings annual growth (%)",
    0.0, 15.0,
    cash_growth_default_pct,
    step=0.1,
    key="cash_growth_pct",
    help=(
        "Interest rate applied to the cash balance every year of the "
        "simulation. Default 0%."
    ),
) / 100
cash_contrib = st.number_input(
    "Annual Cash contribution until retirement (£)",
    0.0, 200_000.0, cash_contrib_default,
    help=(
        "Added every year while at least one partner is still working. "
        "Stops once both have retired."
    ),
)

property_growth_pct = st.number_input(
    "Annual property % increase",
    0.0, 20.0, property_growth_default_pct,
    step=0.1,
    help=(
        "Annual % growth applied to the property value every year of "
        "the simulation."
    ),
) / 100

# ----------------------------------------
# 3. Mortgage detail — the headline figures (outstanding, term,
# monthly payment) live on Quick Estimate; this page refines the
# rate, fractional term, overpayments and the chart-display flag.
# ----------------------------------------
st.subheader("🏠 Mortgage detail")

mort_rate_default = float(mort_saved.get("rate", 0.03))
# Backwards compat: older saved plans stored `end_year` as int years
# only. Split the saved value into whole-years + leftover months so the
# two-field form renders the user's plan rather than discarding the
# fractional round-off.
mort_end_default_years, mort_end_default_months = _split_years_into_years_and_months(
    mort_saved.get("end_year", 10)
)
mort_payment_default_monthly = round(
    mort_saved.get("annual_payment", 0) / 12, 2
)
mort_overpayment_default_monthly = round(
    mort_saved.get("annual_overpayment", 0) / 12, 2
)
mort_include_default = mort_saved.get("include_in_spending", False)

mort_rate = st.number_input(
    "Interest rate (%)", 0.0, 10.0, mort_rate_default * 100
) / 100

# Two-field term input with a friendly English caption. Internally
# stored as a float (`years + months / 12.0`) — the engine handles
# partial-year amortisation in the closing year.
col_years, col_months = st.columns(2)
with col_years:
    mort_end_years = st.number_input(
        "Years",
        min_value=0,
        max_value=50,
        value=mort_end_default_years,
        key="mort_end_years",
    )
with col_months:
    mort_end_months = st.number_input(
        "Months",
        min_value=0,
        max_value=11,
        value=mort_end_default_months,
        key="mort_end_months",
        help=(
            "Additional months on top of the years. For example '9' "
            "here with '6' in the Years box ⇒ mortgage ends at year 9.5 "
            "in simulation time. The engine amortises a quarter/half/"
            "etc.-year slice in the closing year."
        ),
    )
st.caption(
    _format_years_months_caption(
        verb="ends",
        noun="Mortgage",
        years=mort_end_years, months=mort_end_months,
        empty_message="Mortgage ends immediately (no remaining term).",
    )
)

# Monthly-cadence inputs. The app multiplies by 12 on save so the
# `annual_payment` / `annual_overpayment` storage keys + the engine
# stay in annual cadence.
mort_payment_monthly = st.number_input(
    "Monthly mortgage payment (£)",
    min_value=0.0,
    max_value=100_000.0,
    value=mort_payment_default_monthly,
    step=10.0,
    help=(
        "Your regular monthly mortgage payment. The app multiplies "
        "this by 12 to get the annual figure the simulation uses."
    ),
)
mort_overpayment_monthly = st.number_input(
    "Monthly overpayment (£)",
    min_value=0.0,
    max_value=100_000.0,
    value=mort_overpayment_default_monthly,
    step=10.0,
    help=(
        "Optional monthly overpayment on top of the regular payment. "
        "The app multiplies this by 12 to get the annual figure."
    ),
)

# Spending-figure toggle — drives BOTH the engine's `total_need` AND
# the chart display (see `simulation/engine.py` step 7). When ON the
# user's annual-spending figure is treated as TOTAL household outgoings
# (mortgage included), so the plan funds exactly that figure and the
# Spending line shows one combined line. When OFF spending is
# lifestyle-only and the mortgage payment is funded on top.
mort_include_in_spending = st.checkbox(
    "Include mortgage payment in spending figure",
    value=mort_include_default,
    help=(
        "When ON, your annual spending figure already includes the "
        "mortgage payment — the plan funds your spending target "
        "exactly and the mortgage is paid out of it (one Spending "
        "line on the charts). When OFF, spending is lifestyle-only "
        "and the mortgage payment is funded on top of it."
    ),
)

# ----------------------------------------
# 4. Cash-Buffer Mode (pre-retirement coverage)
# ----------------------------------------
# Opt-in planning flag that fixes the engine's pre-existing
# "phantom-cash" effect on the mortgage. When ON, the engine lifts the
# pre-retirement asset-drawdown gate so Cash → ISA → GIA dip to cover
# both the mortgage shortfall AND any lifestyle shortfall before
# retirement. Pension drawdown (PCLS / UFPLS / DB) stays strictly
# retired-gated regardless.
cash_buffer_enabled = st.checkbox(
    "Cash-buffer mode (cover pre-retirement deficits from savings)",
    value=bool(data.get("cash_buffer", False)),
    help=(
        "When ON, pre-retirement years where earned income can't "
        "cover spending + mortgage will see Cash → ISA → GIA dip "
        "to close the gap. Net worth drops accurately (no phantom "
        "uplift from mortgage balance reduction). Default OFF — "
        "preserves legacy behaviour where pre-retirement deficit "
        "years surface as 'Income < Spending' on the chart."
    ),
)

# ----------------------------------------
# 5. Save Button — asset VALUES are owned by Quick Estimate, so the
# save preserves them from the saved data and only writes the detail
# fields edited on this page.
# ----------------------------------------
if st.button("Save Assets"):
    saved_values = {
        a.get("asset_type"): a.get("value", 0.0)
        for a in assets_saved if isinstance(a, dict)
    }
    data["assets"] = [
        {"name": "ISA", "value": float(saved_values.get("ISA", 0.0)),
         "growth_rate": isa_growth_pct,
         "contribution_until_retirement": isa_contrib, "asset_type": "ISA"},
        {"name": "GIA", "value": float(saved_values.get("GIA", 0.0)),
         "growth_rate": gia_growth_pct,
         "contribution_until_retirement": gia_contrib, "asset_type": "GIA"},
        {"name": "Cash", "value": float(saved_values.get("Cash", 0.0)),
         "growth_rate": cash_growth_pct,
         "contribution_until_retirement": cash_contrib, "asset_type": "Cash"},
        {"name": "Property",
         "value": float(saved_values.get("Property", 0.0)),
         "growth_rate": property_growth_pct,
         "asset_type": "Property"},
    ]

    data["mortgage"] = {
        # Outstanding balance is preserved from saved data (owned by
        # Quick Estimate); only the detail fields below are edited here.
        "outstanding": float(mort_saved.get("outstanding", 0.0)),
        "rate": mort_rate,
        # Persist as a single float so the engine sees one canonical
        # `end_year` value.
        "end_year": float(mort_end_years) + mort_end_months / 12.0,
        "annual_payment": mort_payment_monthly * 12,
        "annual_overpayment": mort_overpayment_monthly * 12,
        "include_in_spending": mort_include_in_spending,
    }

    # Persist the cash_buffer household-level planning flag.
    data["cash_buffer"] = cash_buffer_enabled

    save_household(data)
    st.success("Assets & mortgage detail saved!")
