import streamlit as st
from models.events import DownsizingEvent
from storage import init_household, save_household

st.title("🏡 Downsizing")

st.write("""
Add a downsizing event where you sell your current home and move to a cheaper one.
This can release equity and improve retirement sustainability.
""")

# Seed from disk so a previously saved Downsizing event survives a refresh.
init_household(st.session_state)

year = st.number_input("Years from now", 0, 50, 10, key="down_year")
sell_value = st.number_input("Sale value of current property (£)", 0, 5_000_000, 400000, key="down_sell")
new_value = st.number_input("Value of new property (£)", 0, 5_000_000, 250000, key="down_new")

if st.button("Add Downsizing Event", key="add_downsizing"):
    if "events" not in st.session_state.household_data:
        st.session_state.household_data["events"] = []

    st.session_state.household_data["events"].append({
        "year": year,
        "sell_property_value": sell_value,
        "new_property_value": new_value,
        "description": "Downsizing"
    })

    save_household(st.session_state.household_data)
    st.success("Downsizing event added!")
