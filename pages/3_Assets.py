import streamlit as st

st.title("📊 Assets")

# ----------------------------------------
# 1. Initialise session_state only once
# ----------------------------------------
if "household_data" not in st.session_state:
    st.session_state.household_data = {}

# Convenience shortcuts
assets_saved = st.session_state.household_data.get("assets", [])
mort_saved = st.session_state.household_data.get("mortgage", {})

# Extract saved values (if they exist)
def get_asset_value(asset_type, default=0):
    for a in assets_saved:
        if a.get("asset_type") == asset_type:
            return a.get("value", default)
    return default

isa_default = get_asset_value("ISA", 0)
gia_default = get_asset_value("GIA", 0)
cash_default = get_asset_value("Cash", 0)
property_default = get_asset_value("Property", 0)

mort_balance_default = mort_saved.get("outstanding", 0)
mort_rate_default = mort_saved.get("rate", 0.03)
mort_end_default = mort_saved.get("end_year", 10)

# ----------------------------------------
# 2. Asset Inputs (pre-filled)
# ----------------------------------------
isa = st.number_input("ISA total (£)", 0, 5_000_000, isa_default)
gia = st.number_input("GIA total (£)", 0, 5_000_000, gia_default)
cash = st.number_input("Cash savings (£)", 0, 5_000_000, cash_default)
property_value = st.number_input("Property value (£)", 0, 5_000_000, property_default)

# ----------------------------------------
# 3. Mortgage Inputs (pre-filled)
# ----------------------------------------
st.header("Mortgage")

mort_balance = st.number_input("Outstanding mortgage (£)", 0, 5_000_000, mort_balance_default)
mort_rate = st.number_input("Interest rate (%)", 0.0, 10.0, mort_rate_default * 100) / 100
mort_end = st.number_input("Years until mortgage ends", 0, 50, mort_end_default)

# ----------------------------------------
# 4. Save Button
# ----------------------------------------
if st.button("Save Assets"):
    st.session_state.household_data["assets"] = [
        {"name": "ISA", "value": isa, "growth_rate": 0.05, "asset_type": "ISA"},
        {"name": "GIA", "value": gia, "growth_rate": 0.05, "asset_type": "GIA"},
        {"name": "Cash", "value": cash, "growth_rate": 0.00, "asset_type": "Cash"},
        {"name": "Property", "value": property_value, "growth_rate": 0.02, "asset_type": "Property"},
    ]

    st.session_state.household_data["mortgage"] = {
        "outstanding": mort_balance,
        "rate": mort_rate,
        "end_year": mort_end
    }

    st.success("Assets & mortgage saved!")
