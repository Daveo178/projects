import streamlit as st

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
mort_end_default = mort_saved.get("end_year", 10)
mort_payment_default = mort_saved.get("annual_payment", 0)
mort_overpayment_default = mort_saved.get("annual_overpayment", 0)

mort_balance = st.number_input("Outstanding mortgage (£)", 0, 5_000_000, mort_balance_default)
mort_rate = st.number_input("Interest rate (%)", 0.0, 10.0, mort_rate_default * 100) / 100
mort_end = st.number_input("Years until mortgage ends", 0, 50, mort_end_default)
mort_payment = st.number_input(
    "Annual mortgage payment (£)",
    0, 1_000_000, mort_payment_default,
    help="Your regular annual mortgage payment. Interest accrues on the outstanding balance first (at the rate above), then this payment reduces the capital.",
)
mort_overpayment = st.number_input(
    "Annual overpayment (£)",
    0, 1_000_000, mort_overpayment_default,
    help="Optional annual overpayment on top of the regular payment. Reduces the balance faster and shortens the term. Combined payment cannot exceed the outstanding balance — any excess is not refunded, matching standard UK repayment-mortgage behaviour.",
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
        "end_year": mort_end,
        "annual_payment": mort_payment,
        "annual_overpayment": mort_overpayment,
    }

    save_household(st.session_state.household_data)
    st.success("Assets & mortgage saved!")
