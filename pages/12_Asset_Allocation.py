import streamlit as st
import pandas as pd
import altair as alt

from simulation.charts import to_int_pounds

st.title("📊 Asset Allocation Over Time")

st.write("""
This page shows how your asset mix evolves throughout retirement:
- ISA
- GIA
- Cash
- Property
- DC pension
""")

# -------------------------
# Ensure simulation exists
# -------------------------
# Guard against the "Reset Plan" path on the Home page, which explicitly
# sets `simulation_results = None` (the key still exists, so a key-only
# check passes and we crash on `results["years"]`). Pattern follows
# pages/7_AI_Analysis.py and pages/11_Timeline.py.
if "simulation_results" not in st.session_state or st.session_state.simulation_results is None:
    st.warning("Please run a simulation first.")
    st.stop()

results = st.session_state.simulation_results

# -------------------------
# Derive current age for the age-axis treatment. Same
# `try/except` fallback as pages/10_Tax_View.py and
# pages/11_Timeline.py: bare `int(...)` would KeyError on the
# "Reset Plan" path that wipes `household_data` mid-session.
# -------------------------
try:
    p1_current_age = int(
        st.session_state.household_data["person1"]["age"]
    )
except (KeyError, TypeError, ValueError):
    p1_current_age = 55

sim_horizon = len(results["years"])
last_age = p1_current_age + sim_horizon - 1
age_range = f"Age {p1_current_age} → {last_age}"

# -------------------------
# Build DataFrame
# -------------------------
df = pd.DataFrame({
    "Year": results["years"],
    "Age": [y + p1_current_age for y in results["years"]],
    "ISA": to_int_pounds(results["isa_value"]),
    "GIA": to_int_pounds(results["gia_value"]),
    "Cash": to_int_pounds(results["cash_value"]),
    "Property": to_int_pounds(results["property_value"]),
    "DC Pension": to_int_pounds(results["dc_pot"]),
})

ASSET_COLUMNS = ["ISA", "GIA", "Cash", "Property", "DC Pension"]

# -------------------------
# Stacked Area Chart — fixed y-axis at the per-year peak total so
# a £70k ISA bar at age 60 is directly comparable to a £120k ISA bar
# at age 80 (same y-axis). Without the explicit `domain` bound, the
# native Streamlit / Altair default rescaled for year-by-year peaks —
# meaning a tall ISA slice in year 3 would visually dwarf an
# objectively larger ISA slice in year 30 whose row-total happened
# to be lower that year.
#
# Use `df[ASSET_COLUMNS].sum(axis=1).max()` (peak total) plus a
# small headroom cap so the top of the stack does not crowd the
# legend. Floored at 1.0 to keep the chart renderable when someone
# has zero assets across the whole horizon.
# -------------------------
peak_total = float(df[ASSET_COLUMNS].sum(axis=1).max())
# Use 1% (NOT 0% / 5%) headroom: tight enough that per-year asset
# values are visually 1-for-1 comparable across the horizon (a £500k
# slice and a £400k slice differ by exactly the 25% on-screen height
# ratio that the data implies), with enough clearance that the
# topmost area segment doesn't crash into Altair's topmost y-axis
# tick / legend. The 1.0 floor below ensures the chart is still
# renderable when the household has zero assets across the horizon.
y_axis_max = max(peak_total * 1.01, 1.0)

st.subheader(f"📈 Asset Allocation Over Time ({age_range})")
st.caption(
    "Stacked area chart with a fixed y-axis at the per-year PEAK "
    f"total (£{peak_total:,.0f}) so a £-amount in any year can be "
    "compared 1-for-1 with the same £-amount in any other year. "
    "Without this fixed axis, the chart would auto-rescale per frame."
)

melt_stack = df.melt(
    id_vars=["Age"],
    value_vars=ASSET_COLUMNS,
    var_name="Asset",
    value_name="Value",
)

stack_chart = (
    alt.Chart(melt_stack)
    .mark_area(opacity=0.75)
    .encode(
        x=alt.X("Age:O", title="Age", sort="ascending"),
        y=alt.Y(
            "Value:Q",
            title="Asset value (£)",
            stack="zero",
            scale=alt.Scale(domain=[0, y_axis_max], nice=False),
            axis=alt.Axis(format=",.0f"),
        ),
        color=alt.Color(
            "Asset:N",
            sort=ASSET_COLUMNS,
            scale=alt.Scale(scheme="tableau10"),
            legend=alt.Legend(orient="right", title="Asset"),
        ),
        order=alt.Order("color_N_order:Q", sort="ascending"),
        tooltip=[
            "Age",
            "Asset",
            alt.Tooltip("Value:Q", format=",.0f", title="Value £"),
        ],
    )
    .properties(height=440)
)
st.altair_chart(stack_chart, use_container_width=True)

# -------------------------
# Asset mix in a selected year — slider labelled in AGE but kept
# indexed internally as the year-offset so `df.iloc[year]` still
# gives the right row.
# -------------------------
st.subheader(f"🥧 Asset Mix in a Specific Year ({age_range})")

selected_age = st.slider(
    "Select Age",
    min_value=p1_current_age,
    max_value=last_age,
    value=p1_current_age,
    step=1,
)

row = df.iloc[selected_age - p1_current_age]

asset_mix_df = pd.DataFrame({
    "Asset": ASSET_COLUMNS,
    "Value": [
        int(row["ISA"]),
        int(row["GIA"]),
        int(row["Cash"]),
        int(row["Property"]),
        int(row["DC Pension"]),
    ],
})

# Compute the per-row total so the bar chart's y-axis can be fixed
# at the same `y_axis_max` from above, keeping per-year magnitudes
# directly comparable across the slider range.
selected_total = float(asset_mix_df["Value"].sum())

st.write(f"### Age {selected_age}  (total £{selected_total:,.0f})")

mix_chart = (
    alt.Chart(asset_mix_df)
    .mark_bar(size=42)
    .encode(
        x=alt.X("Asset:N", sort=ASSET_COLUMNS, title="Asset class"),
        y=alt.Y(
            "Value:Q",
            title="Value (£)",
            scale=alt.Scale(domain=[0, y_axis_max], nice=False),
            axis=alt.Axis(format=",.0f"),
        ),
        color=alt.Color(
            "Asset:N",
            sort=ASSET_COLUMNS,
            scale=alt.Scale(scheme="tableau10"),
            legend=None,
        ),
        tooltip=[
            "Asset",
            alt.Tooltip("Value:Q", format=",.0f", title="Value £"),
        ],
    )
    .properties(height=320)
)
st.altair_chart(mix_chart, use_container_width=True)

st.caption(
    "Single-year bar chart (a Streamlit-native pie-chart "
    "alternative). The y-axis is fixed at the same peak total as "
    "the stacked area chart above, so the absolute height of any "
    "bar at any selected age is directly comparable to any other "
    "age."
)
