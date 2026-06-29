import streamlit as st
from explain.llm import explain_results
from storage import init_household

st.title("🤖 AI Analysis")

# Seed household_data from disk so this page can be opened directly.
init_household(st.session_state)

if "simulation_results" not in st.session_state or st.session_state.simulation_results is None:
    st.warning("Please run a simulation on the Home page first.")
    st.stop()

results = st.session_state.simulation_results
household = st.session_state.household_data

if st.button("Generate AI Explanation"):
    explanation = explain_results(results, household)
    st.subheader("AI Explanation")
    st.write(explanation)
