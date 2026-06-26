import streamlit as st
from explain.llm import explain_results

st.title("🤖 AI Analysis")

if "simulation_results" not in st.session_state or st.session_state.simulation_results is None:
    st.warning("Please run a simulation on the Home page first.")
    st.stop()

results = st.session_state.simulation_results
household = st.session_state.household_data

if st.button("Generate AI Explanation"):
    explanation = explain_results(results, household)
    st.subheader("AI Explanation")
    st.write(explanation)
