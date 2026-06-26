import streamlit as st

st.set_page_config(
    page_title="Shaz and Dave's Road to Retirement",
    layout="wide"
)

# Initialise session state
if "household_data" not in st.session_state:
    st.session_state.household_data = {}

if "simulation_results" not in st.session_state:
    st.session_state.simulation_results = None

st.title("Shaz and Dave's Road to Retirement")
st.write("Use the sidebar to navigate through your retirement planning dashboard.")
