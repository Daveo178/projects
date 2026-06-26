import streamlit as st

st.title("💼 Pensions")

# ----------------------------------------
# 1. Initialise session_state only once
# ----------------------------------------
if "household_data" not in st.session_state:
    st.session_state.household_data = {}

# Convenience shortcuts
p1 = st.session_state.household_data.get("person1", {})
p2 = st.session_state.household_data.get("person2", {})

# ----------------------------------------
# 2. Dave
# ----------------------------------------
st.header("Dave")

d_age = st.number_input("Age", 18, 100, p1.get("age", 55), key="d_age")
d_ret = st.number_input("Retirement age", 50, 80, p1.get("retirement_age", 60), key="d_ret")
d_sp = st.number_input("State Pension age", 60, 80, p1.get("state_pension_age", 67), key="d_sp")
d_dc = st.number_input("DC pot (£)", 0, 5_000_000, p1.get("dc_pot", 0), key="d_dc")
d_contrib = st.number_input("Monthly contribution (£)", 0, 5000, p1.get("monthly_contrib", 0), key="d_contrib")
d_income = st.number_input("Annual income until retirement (£)", 0, 500_000, p1.get("income_until_retirement", 0), key="d_income")
d_db = st.number_input("DB annual income (£)", 0, 200_000, p1.get("db_income", 0), key="d_db")
# PCLS slider for Dave
d_pcls_percent = st.slider(
    "Tax‑free lump sum percentage (PCLS)",
    0, 25,
    p1.get("pcls_percent", 0),
    key="d_pcls_percent"
)



# ----------------------------------------
# 3. Shaz
# ----------------------------------------
st.header("Shaz")

s_age = st.number_input("Age ", 18, 100, p2.get("age", 55), key="s_age")
s_ret = st.number_input("Retirement age ", 50, 80, p2.get("retirement_age", 60), key="s_ret")
s_sp = st.number_input("State Pension age ", 60, 80, p2.get("state_pension_age", 67), key="s_sp")
s_dc = st.number_input("DC pot (£) ", 0, 5_000_000, p2.get("dc_pot", 0), key="s_dc")
s_contrib = st.number_input("Monthly contribution (£) ", 0, 5000, p2.get("monthly_contrib", 0), key="s_contrib")
s_income = st.number_input("Annual income until retirement (£) ", 0, 500_000, p2.get("income_until_retirement", 0), key="s_income")
s_db = st.number_input("DB annual income (£)", 0, 200_000, p2.get("db_income", 0), key="s_db")
# PCLS slider for Shaz
s_pcls_percent = st.slider(
    "Tax‑free lump sum percentage (PCLS)",
    0, 25,
    p2.get("pcls_percent", 0),
    key="s_pcls_percent"
)



# ----------------------------------------
# 4. Save button
# ----------------------------------------
if st.button("Save Pension Data"):
    st.session_state.household_data["person1"] = {
        "name": "Dave",
        "age": d_age,
        "retirement_age": d_ret,
        "state_pension_age": d_sp,
        "dc_pot": d_dc,
        "monthly_contrib": d_contrib,
        "income_until_retirement": d_income,
        "db_income": d_db,
        "pcls_percent": d_pcls_percent
    }

    st.session_state.household_data["person2"] = {
        "name": "Shaz",
        "age": s_age,
        "retirement_age": s_ret,
        "state_pension_age": s_sp,
        "dc_pot": s_dc,
        "monthly_contrib": s_contrib,
        "income_until_retirement": s_income,
        "db_income": s_db,
        "pcls_percent": s_pcls_percent
    }

    st.success("Pension data saved!")
