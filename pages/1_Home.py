import streamlit as st
from models.person import Person
from models.asset import Asset
from models.mortgage import Mortgage
from models.household import Household
from models.events import LifeEvent
from simulation.engine import run_simulation
from simulation.charts import net_worth_chart, income_vs_spending_chart

st.title("🏠 Home — Overview Dashboard")

st.write("This page shows your retirement simulation results based on the data entered on the other pages.")

# Ensure data exists
if "household_data" not in st.session_state:
    st.warning("Please enter your pension, assets, spending and events first.")
    st.stop()

data = st.session_state.household_data

required_keys = ["person1", "person2", "assets", "spending"]
missing = [k for k in required_keys if k not in data]

if missing:
    st.warning(f"Missing required data: {', '.join(missing)}. Please complete the input pages.")
    st.stop()

# -------------------------
# RUN SIMULATION BUTTON
# -------------------------
if st.button("Run Simulation"):
    # --- Build Person objects ---
    p1 = Person(**data["person1"])
    p2 = Person(**data["person2"])

    # --- Build Asset objects ---
    assets = [Asset(**a) for a in data["assets"]]

    # --- Build Mortgage object ---
    mortgage = None
    if "mortgage" in data and data["mortgage"]:
        mortgage = Mortgage(**data["mortgage"])

    # --- Build Life Events list ---
    events = []
    if "events" in data:
        events = [LifeEvent(**e) for e in data["events"]]

    # --- Build Household object ---
    household = Household(
        person1=p1,
        person2=p2,
        assets=assets,
        mortgage=mortgage,
        spending_target=data["spending"],
        drawdown_strategy=data.get("drawdown_strategy", "Fixed"),
        events=events
    )

    # --- Run Simulation ---
    results = run_simulation(household)
    st.session_state.simulation_results = results

    st.success("Simulation complete!")

# -------------------------
# DISPLAY RESULTS
# -------------------------
if "simulation_results" in st.session_state and st.session_state.simulation_results:
    results = st.session_state.simulation_results

    st.subheader("📈 Net Worth Over Time")
    st.line_chart(net_worth_chart(results), x="Year", y="Net Worth")

    st.subheader("💰 Income vs Spending")
    st.line_chart(income_vs_spending_chart(results), x="Year", y=["Income", "Spending"])

    # Sustainability warning
    if results["net_worth"][-1] < 0:
        st.error("⚠️ Warning: Your plan is not sustainable. Assets run out before the end of the simulation.")
    else:
        st.success("✅ Your plan appears sustainable within the simulation horizon.")
