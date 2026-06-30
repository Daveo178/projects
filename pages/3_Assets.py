import streamlit as st

from simulation.years_and_months import (
    _split_years_into_years_and_months,
    _format_years_months_caption,
)
from storage import init_household, save_household

st.title("📊 Assets")

# ----------------------------------------
# 1. Initialise session_state — seed from disk on first visit
# ----------------------------------------
init_household(st.session_state)

# Convenience shortcuts
assets_saved = st.session_state.household_data.get("assets", [])
mort_saved = st.session_state.household_data.get("mortgage", {})

# Extract saved values (if they exist)
def get_asset_value(asset_type, default=0):
    for a in assets_saved:
        if a.get("asset_type") == asset_type:
            return a.get("value", default)
    return default

def get_asset_field(asset_type, field, default=0):
    for a in assets_saved:
        if a.get("asset_type") == asset_type:
            return a.get(field, default)
    return default


# ----------------------------------------
# 1b. Mortgage end-term helpers — imported from
# `simulation.years_and_months` so the splitting math + English caption
# live in exactly one place (also used by `pages/2_Pensions.py` with
# verb + noun parameterised). See the shared helper for documentation
# and edge-case behaviour.
# ----------------------------------------

isa_default = get_asset_value("ISA", 0)
gia_default = get_asset_value("GIA", 0)
cash_default = get_asset_value("Cash", 0)
property_default = get_asset_value("Property", 0)

isa_contrib_default = get_asset_field("ISA", "contribution_until_retirement", 0)
gia_contrib_default = get_asset_field("GIA", "contribution_until_retirement", 0)
cash_contrib_default = get_asset_field("Cash", "contribution_until_retirement", 0)
# Property growth default pulls the existing saved growth_rate (2% matches the
# historical hardcoded default). Round to 2 dp so the input shows 2.0 not 2.0001.
property_growth_default_pct = round(
    get_asset_field("Property", "growth_rate", 0.02) * 100, 2
)

# ----------------------------------------
# 2. Asset Inputs (pre-filled)
# ----------------------------------------
isa = st.number_input("ISA total (£)", 0, 5_000_000, isa_default)
isa_contrib = st.number_input(
    "Annual ISA contribution until retirement (£)",
    0, 200_000, isa_contrib_default,
    help="Added every year while at least one partner is still working. Stops once both have retired.",
)

gia = st.number_input("GIA total (£)", 0, 5_000_000, gia_default)
gia_contrib = st.number_input(
    "Annual GIA contribution until retirement (£)",
    0, 200_000, gia_contrib_default,
    help="Added every year while at least one partner is still working. Stops once both have retired.",
)

cash = st.number_input("Cash savings (£)", 0, 5_000_000, cash_default)
cash_contrib = st.number_input(
    "Annual Cash contribution until retirement (£)",
    0, 200_000, cash_contrib_default,
    help="Added every year while at least one partner is still working. Stops once both have retired.",
)

property_value = st.number_input("Property value (£)", 0, 5_000_000, property_default)
property_growth_pct = st.number_input(
    "Annual property % increase",
    0.0, 20.0, property_growth_default_pct,
    step=0.1,
    help="Annual % growth applied to the property value every year of the simulation.",
) / 100

# ----------------------------------------
# 3. Mortgage Inputs (pre-filled)
# ----------------------------------------
st.header("Mortgage")

mort_balance_default = mort_saved.get("outstanding", 0)
mort_rate_default = mort_saved.get("rate", 0.03)
# Backwards compat: older saved plans stored `end_year` as int years
# only. Split the saved value into whole-years + leftover months so the
# two-field form renders the user's plan rather than discarding the
# fractional round-off. Months is clamped to 0..11 in case a future
# save wrote a slightly-out-of-range value (e.g. 12.0 due to sloppy
# arithmetic — defensive, free).
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

mort_balance = st.number_input("Outstanding mortgage (£)", 0, 5_000_000, mort_balance_default)
mort_rate = st.number_input("Interest rate (%)", 0.0, 10.0, mort_rate_default * 100) / 100

# Two-field term input with a friendly English caption so the user sees
# "9 years 6 months" rather than the raw "9.5". Internally stored as a
# float (`years + months / 12.0`) — the engine handles partial-year
# amortisation in the closing year.
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
        help="Additional months on top of the years. For example '9' here with '6' in the Years box ⇒ mortgage ends at year 9.5 in simulation time. The engine amortises a quarter/half/etc.-year slice in the closing year.",
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
# stay in annual cadence (which is what the simulation models — a £1k
# monthly payment still arrives as twelve £1k payments over a year).
# Lower upper-bound than before (was £1M) so the field matches the
# realistic monthly-payment range.
mort_payment_monthly = st.number_input(
    "Monthly mortgage payment (£)",
    min_value=0,
    max_value=100_000,
    value=mort_payment_default_monthly,
    step=10.0,
    help="Your regular monthly mortgage payment. The app multiplies this by 12 to get the annual figure the simulation uses.",
)
mort_overpayment_monthly = st.number_input(
    "Monthly overpayment (£)",
    min_value=0,
    max_value=100_000,
    value=mort_overpayment_default_monthly,
    step=10.0,
    help="Optional monthly overpayment on top of the regular payment. The app multiplies this by 12 to get the annual figure.",
)

# Chart-display toggle (NOT an engine-setting). When ON the home-page
# Income/Spending/Mortgage chart folds mortgage_payment into the
# Spending series; when OFF today's three-line view is preserved. The
# engine's drawdown waterfall already covers BOTH lifestyle spending
# AND the mortgage payment in `total_need` regardless of this flag,
# so flipping the flag does not change the simulation results — only
# how the chart presents them.
mort_include_in_spending = st.checkbox(
    "Include mortgage payment in displayed spending",
    value=mort_include_default,
    help=(
        "When ON, the Spending line on the home-page chart shows "
        "lifestyle + mortgage combined so you see total household "
        "outgoings as one line. When OFF, today's three-line view "
        "(Income / Spending / Mortgage Payment) is preserved. "
        "Engine drawdown math is the same either way."
    ),
)

# ----------------------------------------
# 4. Save Button
# ----------------------------------------
if st.button("Save Assets"):
    st.session_state.household_data["assets"] = [
        {"name": "ISA", "value": isa, "growth_rate": 0.05,
         "contribution_until_retirement": isa_contrib, "asset_type": "ISA"},
        {"name": "GIA", "value": gia, "growth_rate": 0.05,
         "contribution_until_retirement": gia_contrib, "asset_type": "GIA"},
        {"name": "Cash", "value": cash, "growth_rate": 0.00,
         "contribution_until_retirement": cash_contrib, "asset_type": "Cash"},
        {"name": "Property", "value": property_value, "growth_rate": property_growth_pct,
         "asset_type": "Property"},
    ]

    st.session_state.household_data["mortgage"] = {
        "outstanding": mort_balance,
        "rate": mort_rate,
        # Persist as a single float so the engine sees one canonical
        # `end_year` value, regardless of whether the user entered an
        # integer years + 0 months or a partial-year combination. The
        # explicit `float(...)` cast guarantees the JSON value is
        # serialised as a number (not a string) even when years and
        # months are decimal literals.
        "end_year": float(mort_end_years) + mort_end_months / 12.0,
        # Monthly-form inputs × 12 → annual_payment / annual_overpayment
        # for the simulation. The engine + Mortgage dataclass stay in
        # annual cadence, so `model/`/`storage.py`/`engine.py` don't
        # need any per-month handling.
        "annual_payment": mort_payment_monthly * 12,
        "annual_overpayment": mort_overpayment_monthly * 12,
        "include_in_spending": mort_include_in_spending,
    }

    save_household(st.session_state.household_data)
    st.success("Assets & mortgage saved!")
