import streamlit as st

st.title("💷 Spending & Drawdown")

# ----------------------------------------
# 1. Initialise session_state only once
# ----------------------------------------
if "household_data" not in st.session_state:
    st.session_state.household_data = {}

# Convenience shortcuts
saved_spending = st.session_state.household_data.get("spending", 30_000)
saved_strategy = st.session_state.household_data.get("drawdown_strategy", "Fixed")

# ----------------------------------------
# 2. Inputs (pre-filled with saved values)
# ----------------------------------------
spending = st.number_input(
    "Annual household spending (£)",
    0,
    200_000,
    saved_spending
)

strategy = st.selectbox(
    "Drawdown strategy",
    ["Fixed", "Inflation-adjusted", "Safe Withdrawal (4%)"],
    index=["Fixed", "Inflation-adjusted", "Safe Withdrawal (4%)"].index(saved_strategy)
)

# ----------------------------------------
# 3. Save Button
# ----------------------------------------
if st.button("Save Spending"):
    st.session_state.household_data["spending"] = spending
    st.session_state.household_data["drawdown_strategy"] = strategy

    st.success("Spending & drawdown strategy saved!")
