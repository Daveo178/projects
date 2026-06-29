import streamlit as st

from storage import init_household, has_saved_plan

st.set_page_config(
    page_title="Shaz and Dave's Road to Retirement",
    layout="wide"
)

# Initialise session state — load from disk on first visit of a browser tab
# so any plan saved in a previous refresh is preserved.
init_household(st.session_state)

if "simulation_results" not in st.session_state:
    st.session_state.simulation_results = None

st.title("Shaz and Dave's Road to Retirement")
st.write("Use the sidebar to navigate through your retirement planning dashboard.")

# A tiny status hint so the user knows persistence is active.
if has_saved_plan():
    st.caption("💾 A saved plan is loaded from disk. Note: data is stored as plaintext `household_data.json` in this folder — keep the folder local.")
else:
    st.caption("ℹ️ No saved plan yet — your inputs are saved when you click a Save button. Tip: open in one tab at a time (last save wins).")
