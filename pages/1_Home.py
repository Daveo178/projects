import streamlit as st
import pandas as pd
import altair as alt

from models.person import Person
from models.asset import Asset
from models.mortgage import Mortgage
from models.household import Household
from models.events import LifeEvent
from simulation.engine import run_simulation
from simulation.charts import (
    net_worth_chart,
    net_worth_composition_chart,
    pension_breakdown_chart,
    income_vs_spending_chart,
    to_int_pounds,
)
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

    # ---------------------------------------------------------
    # Asset-class composition over time (replaces the old single
    # Net Worth line). The engine already exposes per-class series
    # (ISA / GIA / Cash / Property / DC Pension) so we just melt them
    # into an Altair stacked-area chart. The peak-gross-wealth total
    # across the horizon pins the y-axis at `peak_total * 1.01` so
    # slices are visually 1-for-1 comparable across ages (same
    # convention as pages/12_Asset_Allocation.py).
    # ---------------------------------------------------------
    st.subheader(f"🥧 Asset Composition Over Time ({age_range})")
    composition_df = _attach_age_column(net_worth_composition_chart(results))
    ASSET_CLASS_COLUMNS = ["ISA", "GIA", "Cash", "Property", "DC Pension"]
    composition_melt = composition_df.melt(
        id_vars=["Age"],
        value_vars=ASSET_CLASS_COLUMNS,
        var_name="Asset Class",
        value_name="Value",
    )
    peak_total = composition_melt.groupby("Age")["Value"].sum().max()
    y_axis_max = max(peak_total * 1.01, 1.0)
    composition_chart = (
        alt.Chart(composition_melt)
        .mark_area(opacity=0.75)
        .encode(
            x=alt.X("Age:Q", title="Age"),
            y=alt.Y(
                "Value:Q",
                stack="zero",
                title="£ (gross wealth)",
                scale=alt.Scale(domain=[0, y_axis_max], nice=False),
            ),
            color=alt.Color(
                "Asset Class:N",
                scale=alt.Scale(scheme="category10"),
                title="Asset class",
            ),
            order=alt.Order(field="Asset Class:N", sort="ascending"),
            tooltip=[
                alt.Tooltip("Age:Q", title="Age"),
                "Asset Class:N",
                alt.Tooltip("Value:Q", title="£", format=",.0f"),
            ],
        )
        .properties(height=440)
    )
    st.altair_chart(composition_chart, use_container_width=True)
    st.caption(
        "Stacked composition shows your gross household wealth by asset "
        "class at every age. Mortgage is debt, not an asset, so it is "
        "shown separately as the red dashed line below — "
        "Gross assets − Mortgage balance = True net worth."
    )

    # Mortgage balance trend on its own scale so the stacked-area
    # chart above is allowed to be purely positive (zero to peak_gross)
    # without the dashed line dipping below the x-axis. After repayment
    # the line just renders flat at £0.
    st.subheader(f"🏠 Mortgage Balance Over Time ({age_range})")
    mortgage_df = pd.DataFrame({
        "Year": results["years"],
        "Mortgage Balance": to_int_pounds(
            results.get("mortgage_balance", [0.0] * len(results["years"]))
        ),
    })
    st.line_chart(_attach_age_column(mortgage_df), x="Age", y="Mortgage Balance")
    st.caption("Outstanding mortgage balance at each year-end. Drops to £0 when the mortgage is fully repaid.")

    # Honour the "Include mortgage payment in displayed spending" toggle
    # from the Assets page. When True the chart helper folds
    # `mortgage_payment` into the Spending series so the viewer sees one
    # combined line ("total household outgoings") instead of two. When
    # False today's three-line view (Income / Spending / Mortgage
    # Payment) is preserved. Engine drawdown math is unchanged either
    # way, so flipping the toggle does not alter simulation results.
    include_mortgage_in_spending = (
        st.session_state.household_data
        .get("mortgage", {})
        .get("include_in_spending", False)
    )
    st.subheader("💰 Income, Spending & Mortgage Payment")
    st.line_chart(
        _attach_age_column(
            income_vs_spending_chart(results, include_mortgage_in_spending)
        ),
        x="Age",
        y=(
            ["Income", "Spending"]
            if include_mortgage_in_spending
            else ["Income", "Spending", "Mortgage Payment"]
        ),
    )
    if include_mortgage_in_spending:
        st.caption(
            "Spending is lifestyle + mortgage combined (toggle from "
            "the Assets page is ON)."
        )
    else:
        st.caption(
            "Spending is lifestyle only; mortgage payment is shown as "
            "its own line. Toggle 'Include mortgage payment in "
            "displayed spending' on the Assets page to combine them."
        )

    # ---------------------------------------------------------
    # Indexed Pension Income — split into DB Pension vs State Pension
    # so the user can see WHICH pension source each £ comes from
    # (the previous single-line "Indexed Pension Over Time" sub-chart
    # was confusing — it summed DB + State Pension into one line,
    # so viewers mistook the combined total for the State Pension
    # alone). The two series are pre-tax, pre-NI. `db_payout` and
    # `state_payout` may be absent in older saved payloads — the
    # `pension_breakdown_chart` helper falls back to all-zeros
    # rather than crashing on KeyError, so legacy sessions still
    # render cleanly (with the missing series flat at £0).
    # ---------------------------------------------------------
    st.subheader(f"💷 Indexed Pension Income — DB + State Pension ({age_range})")
    st.caption(
        "Pre-tax income the household receives from each pension source. "
        "DB Pension activates at draw_age and indexes by db_growth_rate. "
        "State Pension activates at state_pension_age and indexes by "
        "state_pension_growth_rate. Both are pre-tax and pre-NI."
    )
    st.line_chart(
        _attach_age_column(pension_breakdown_chart(results)),
        x="Age",
        y=["DB Pension", "State Pension"],
    )

    # Sustainability warning
    if results["net_worth"][-1] < 0:
        st.error("⚠️ Warning: Your plan is not sustainable. Assets run out before the end of the simulation.")
    else:
        st.success("✅ Your plan appears sustainable within the simulation horizon.")
