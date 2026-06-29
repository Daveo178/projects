import streamlit as st
import pandas as pd
import numpy as np

from models.person import Person
from models.asset import Asset
from models.mortgage import Mortgage
from models.household import Household
from models.events import LifeEvent

from simulation.monte_carlo import monte_carlo_simulation
from simulation.charts import to_int_pounds
from storage import init_household

st.title("🎲 Monte Carlo Simulation")

st.write("""
This page runs a full Monte Carlo simulation of your retirement plan.

It uses:
- Randomised investment returns  
- Randomised inflation  
- Randomised spending shocks  
- Sequence‑of‑returns risk  
- 1000 independent simulation runs  

The result is a **probability of success** and a **fan chart** showing the range of possible outcomes.
""")

# -------------------------
# Ensure data exists — seeded from disk if present
# -------------------------
init_household(st.session_state)

if not st.session_state.household_data:
    st.warning("Please enter your pension, assets, spending and events first.")
    st.stop()

data = st.session_state.household_data

required_keys = ["person1", "person2", "assets", "spending"]
missing = [k for k in required_keys if k not in data]

if missing:
    st.warning(f"Missing required data: {', '.join(missing)}. Please complete the input pages.")
    st.stop()

# -------------------------
# Build household object
# -------------------------
def build_household(data):
    p1 = Person(**data["person1"])
    p2 = Person(**data["person2"])

    assets = [Asset(**a) for a in data["assets"]]

    mortgage = None
    if "mortgage" in data and data["mortgage"]:
        mortgage = Mortgage(**data["mortgage"])

    events = []
    if "events" in data:
        events = [LifeEvent(**e) for e in data["events"]]

    return Household(
        person1=p1,
        person2=p2,
        assets=assets,
        mortgage=mortgage,
        spending_target=data["spending"],
        drawdown_strategy=data.get("drawdown_strategy", "Fixed"),
        events=events
    )

household = build_household(data)

# -------------------------
# Age axis (consistent with pages 10/11/12): `Year` is a year-offset
# from simulation start; `Age = Year + p1_current_age`. Same fallback
# pattern — default 55 if `data["person1"]["age"]` is missing.
# -------------------------
try:
    p1_current_age = int(data["person1"]["age"])
except (KeyError, TypeError, ValueError):
    p1_current_age = 55

# -------------------------
# Run Monte Carlo
# -------------------------
runs = st.number_input("Number of Monte Carlo runs", 100, 5000, 1000, key="mc_runs")

if st.button("Run Monte Carlo Simulation", key="run_mc"):
    with st.spinner("Running Monte Carlo simulation..."):
        mc = monte_carlo_simulation(household, runs=runs)

    st.success("Monte Carlo simulation complete!")

    # -------------------------
    # Probability of success
    # -------------------------
    st.subheader("📊 Probability of Success")
    st.write(f"**{mc['success_rate'] * 100:.1f}%** of simulations did not run out of money.")

    # -------------------------
    # Percentile fan chart
    # -------------------------
    st.subheader("📈 Net Worth Percentile Bands")

    years = list(range(len(mc["percentiles"]["p50"])))

    df = pd.DataFrame({
        "Age": [y + p1_current_age for y in years],
        "10th Percentile": to_int_pounds(mc["percentiles"]["p10"]),
        "25th Percentile": to_int_pounds(mc["percentiles"]["p25"]),
        "Median (50th)": to_int_pounds(mc["percentiles"]["p50"]),
        "75th Percentile": to_int_pounds(mc["percentiles"]["p75"]),
        "90th Percentile": to_int_pounds(mc["percentiles"]["p90"]),
    })

    st.line_chart(
        df,
        x="Age",
        y=[
            "10th Percentile",
            "25th Percentile",
            "Median (50th)",
            "75th Percentile",
            "90th Percentile"
        ]
    )

    # -------------------------
    # Failure year histogram
    # -------------------------
    st.subheader("💥 Failure Age Distribution")

    # `failure_years` is a list of year-OFFSETS (per `monte_carlo.py`: the
    # `enumerate(results["net_worth"])` index, not an absolute year).
    # Convert absolutes for chart consistency with the rest of the app.
    failure_ages = [fy + p1_current_age for fy in mc["failure_years"] if fy is not None]

    if len(failure_ages) == 0:
        st.success("No failures in any simulation run.")
    else:
        hist_df = pd.DataFrame({"Failure Age": failure_ages})
        st.bar_chart(hist_df["Failure Age"].value_counts().sort_index())

    # -------------------------
    # Worst-case and best-case paths
    # -------------------------
    st.subheader("📉 Worst-Case & 📈 Best-Case Net Worth Paths")

    all_paths = np.array(mc["all_paths"])
    worst_path = all_paths.min(axis=0)
    best_path = all_paths.max(axis=0)

    df_paths = pd.DataFrame({
        "Age": [y + p1_current_age for y in years],
        "Worst Case": to_int_pounds(worst_path),
        "Best Case": to_int_pounds(best_path),
        "Median": to_int_pounds(mc["percentiles"]["p50"]),
    })

    st.line_chart(
        df_paths,
        x="Age",
        y=["Worst Case", "Median", "Best Case"]
    )
