import streamlit as st
import pandas as pd

from models.person import Person
from models.asset import Asset
from models.mortgage import Mortgage
from models.household import Household
from models.events import LifeEvent
from simulation.engine import run_simulation
from simulation.charts import net_worth_chart, income_vs_spending_chart, to_int_pounds
from storage import (
    init_household,
    save_household,
    delete_household,
    has_saved_plan,
)

st.title("🏠 Home — Overview Dashboard")

st.write("This page shows your retirement simulation results based on the data entered on the other pages.")

# Seed from disk on first script run.
init_household(st.session_state)

# -------------------------
# Persistence toolbar
# -------------------------
col_status, col_save, col_reset = st.columns([2, 1, 1])

with col_status:
    if has_saved_plan():
        st.caption("💾 Plan is persisted to disk — a refresh will keep your inputs.")
    else:
        st.caption("⚠️ Plan is not yet saved to disk.")

with col_save:
    if st.button("💾 Save Plan", key="save_plan"):
        ok = save_household(st.session_state.get("household_data", {}))
        if ok:
            st.success("Plan saved.")
        else:
            st.error("Could not write to disk. Check folder permissions.")

with col_reset:
    if st.button("🗑️ Reset Plan", key="reset_plan"):
        st.session_state.household_data = {}
        st.session_state.simulation_results = None
        # Wipes both the live file and its `.bak` rotation. copy the .bak back
        # to the live file by hand if you need to undo a Reset.
        delete_household()
        st.warning("Plan reset — both in memory and on disk.")

# -------------------------
# Validate required data
# -------------------------
data = st.session_state.household_data

required_keys = ["person1", "person2", "assets", "spending"]
missing = [k for k in required_keys if k not in data]

if missing:
    st.warning(f"Please enter your pension, assets, spending and events first (missing: {', '.join(missing)}).")
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
    # Note: the engine mutates `household` in place (`asset.grow()`,
    # `person.dc_pot += ...`) but NOT `st.session_state.household_data`,
    # because Person/Asset objects are constructed fresh from the dict above.
    # We deliberately do NOT save after the run — persisting here would be
    # a footgun if anyone ever reuses the session_state-backed models.
    results = run_simulation(household)
    st.session_state.simulation_results = results

    st.success("Simulation complete!")

# -------------------------
# DISPLAY RESULTS
# -------------------------
if "simulation_results" in st.session_state and st.session_state.simulation_results:
    results = st.session_state.simulation_results

    # Home-page x-axis is AGE from current age (Person 1's age) rather than a
    # raw year count from 0 upwards. Other pages still use `Year`. We pull the
    # current age from session_state (not from results) so the chart stays in
    # sync with the value shown on the Pensions page even before a re-run.
    # Page 2 constrains `age` to a numeric `number_input`, and we reach this
    # block only after the earlier required_keys check, so a plain cast is safe.
    p1_current_age = int(data["person1"]["age"])

    def _attach_age_column(df):
        df = df.copy()
        df["Age"] = df["Year"] + p1_current_age
        return df

    age_range = f"Age {p1_current_age} → {p1_current_age + len(results['years']) - 1}"

    st.subheader(f"📈 Net Worth Over Time ({age_range})")
    st.line_chart(_attach_age_column(net_worth_chart(results)), x="Age", y="Net Worth")

    st.subheader("💰 Income, Spending & Mortgage Payment")
    st.line_chart(
        _attach_age_column(income_vs_spending_chart(results)),
        x="Age",
        y=["Income", "Spending", "Mortgage Payment"],
    )

    # Indexed Pension sub-chart — DB + State Pension income, on its own y-axis
    # so the slow upward indexation creep isn't flattened against the much
    # larger Income series above. `pension_income` may be absent in older
    # `simulation_results` payloads (from before the engine field was added) —
    # fall back to all zeros so the line just renders flat at £0.
    st.subheader(f"📈 Indexed Pension Over Time ({age_range})")
    pension_df = pd.DataFrame({
        "Year": results["years"],
        "Pension": to_int_pounds(results.get(
            "pension_income",
            [0.0] * len(results["years"]),
        )),
    })
    st.line_chart(_attach_age_column(pension_df), x="Age", y="Pension")

    # Sustainability warning
    if results["net_worth"][-1] < 0:
        st.error("⚠️ Warning: Your plan is not sustainable. Assets run out before the end of the simulation.")
    else:
        st.success("✅ Your plan appears sustainable within the simulation horizon.")
