import streamlit as st
import pandas as pd
import numpy as np

from models.person import Person
from models.asset import Asset
from models.mortgage import Mortgage
from models.household import Household
from models.events import LifeEvent, DownsizingEvent

from simulation.engine import run_simulation
from simulation.monte_carlo import monte_carlo_simulation
from simulation.charts import to_int_pounds
from storage import init_household

st.title("🧪 What‑If Engine")

st.write("""
Experiment with different retirement scenarios:
- Retire earlier or later  
- Change spending  
- Adjust contributions  
- Stress test investment returns  
- Explore alternative futures  
""")

# -------------------------
# Ensure data exists — seeded from disk if present
# -------------------------
init_household(st.session_state)

if not st.session_state.household_data:
    st.warning("Please enter your pension, assets, spending and events first.")
    st.stop()

data = st.session_state.household_data

# Age axis (consistent with pages 10/11/12): `Year` is a year-offset
# from simulation start; `Age = Year + p1_current_age`. Same fallback
# pattern — default 55 if `data["person1"]["age"]` is missing.
try:
    p1_current_age = int(data["person1"]["age"])
except (KeyError, TypeError, ValueError):
    p1_current_age = 55

required_keys = ["person1", "person2", "assets", "spending"]
missing = [k for k in required_keys if k not in data] 

if missing:
    st.warning(f"Missing required data: {', '.join(missing)}. Please complete the input pages.")
    st.stop()

# -------------------------
# Build household object
# -------------------------
def build_household(data, overrides):
    p1_data = data["person1"].copy()
    p2_data = data["person2"].copy()

    # Apply overrides
    p1_data["retirement_age"] = overrides["ret_age_p1"]
    p2_data["retirement_age"] = overrides["ret_age_p2"]

    p1_data["monthly_contrib"] = overrides["contrib_p1"]
    p2_data["monthly_contrib"] = overrides["contrib_p2"]

    household_spending = overrides["spending"]

    p1 = Person(**p1_data)
    p2 = Person(**p2_data)

    # Assets
    assets = []
    for a in data["assets"]:
        new_a = Asset(**a)
        new_a.growth_rate = overrides["growth_rate"]
        assets.append(new_a)

    # Mortgage
    mortgage = None
    if "mortgage" in data and data["mortgage"]:
        mortgage = Mortgage(**data["mortgage"])

    # Events
    events = []
    if "events" in data:
        for e in data["events"]:
            if "sell_property_value" in e:
                events.append(DownsizingEvent(**e))
            else:
                events.append(LifeEvent(**e))

    return Household(
        person1=p1,
        person2=p2,
        assets=assets,
        mortgage=mortgage,
        spending_target=household_spending,
        drawdown_strategy=data.get("drawdown_strategy", "Fixed"),
        events=events
    )

# -------------------------
# What‑If Controls
# -------------------------
st.subheader("Adjust Scenario")

col1, col2 = st.columns(2)

with col1:
    ret_age_p1 = st.slider("Dave retirement age", 50, 75, data["person1"]["retirement_age"])
    contrib_p1 = st.number_input("Dave monthly contribution (£)", 0, 5000, data["person1"]["monthly_contrib"])

with col2:
    ret_age_p2 = st.slider("Shaz retirement age", 50, 75, data["person2"]["retirement_age"])
    contrib_p2 = st.number_input("Shaz monthly contribution (£)", 0, 5000, data["person2"]["monthly_contrib"])

spending = st.number_input("Annual spending target (£)", 5000, 200000, data["spending"])

growth_rate = st.slider("Expected investment growth rate", 0.00, 0.10, 0.05, step=0.005)
inflation = st.slider("Inflation assumption", 0.00, 0.05, 0.025, step=0.005)

runs = st.number_input("Monte Carlo runs", 100, 5000, 1000)

# -------------------------
# Run Scenario
# -------------------------
if st.button("Run What‑If Scenario"):
    overrides = {
        "ret_age_p1": ret_age_p1,
        "ret_age_p2": ret_age_p2,
        "contrib_p1": contrib_p1,
        "contrib_p2": contrib_p2,
        "spending": spending,
        "growth_rate": growth_rate,
        "inflation": inflation,
    }

    household = build_household(data, overrides)

    with st.spinner("Running scenario..."):
        det = run_simulation(household)
        mc = monte_carlo_simulation(household, runs=runs)

    st.success("Scenario complete!")

    # -------------------------
    # Deterministic charts
    # -------------------------
    st.subheader("📈 Deterministic Net Worth")
    df_det = pd.DataFrame({
        "Age": [y + p1_current_age for y in det["years"]],
        "Net Worth": to_int_pounds(det["net_worth"]),
        "Income": to_int_pounds(det["income"]),
        "Spending": to_int_pounds(det["spending"]),
    })
    st.line_chart(df_det, x="Age", y="Net Worth")

    st.subheader("💰 Income vs Spending")
    st.line_chart(df_det, x="Age", y=["Income", "Spending"])

    # -------------------------
    # Monte Carlo
    # -------------------------
    st.subheader("🎲 Monte Carlo Success Probability")
    st.write(f"**{mc['success_rate'] * 100:.1f}%** probability of not running out of money.")

    st.subheader("📊 Monte Carlo Percentile Bands")
    df_mc = pd.DataFrame({
        "Age": [y + p1_current_age for y in range(len(mc["percentiles"]["p50"]))],
        "10th": to_int_pounds(mc["percentiles"]["p10"]),
        "25th": to_int_pounds(mc["percentiles"]["p25"]),
        "50th": to_int_pounds(mc["percentiles"]["p50"]),
        "75th": to_int_pounds(mc["percentiles"]["p75"]),
        "90th": to_int_pounds(mc["percentiles"]["p90"]),
    })
    st.line_chart(df_mc, x="Age", y=["10th", "25th", "50th", "75th", "90th"])
