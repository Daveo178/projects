import streamlit as st
from brand_chrome import apply_chrome
import pandas as pd
import altair as alt

# Altair theme is GLOBAL state on the `alt` module — `enable()`
# mutates the module's default-theme registry, so it's set on every
# render (light mode is now permanent, so `default` is the only
# theme; the prior dark/light conditional was dropped with the
# Theme radio).
alt.themes.enable("default")

from simulation.charts import to_int_pounds
from simulation.years_and_months import (
    add_age_label_column,
    format_age_label,
    get_p1_current_age,
)
from pages_helpers.global_controls import render_global_controls_sidebar


apply_chrome()
render_global_controls_sidebar()

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
# Derive current age for the age-axis treatment. Centralised helper
# — replaces the duplicated `try: float(...); except: 55` block that
# used to live inline on this page (and pages 1/6/8/10/11/13).
# -------------------------
p1_current_age = get_p1_current_age(st.session_state.household_data)

sim_horizon = len(results["years"])
last_age = p1_current_age + sim_horizon - 1
# `format_age_label` returns compact "Xy Ym" labels (e.g. "55y" /
# "55y 10m"). Replaces the legacy `:g` formatter which truncated
# 5-6 sig figs and rendered fractional ages as decimal noise
# ("Age 55.8333 → 99.8333"). Whole-year ages render as "60y" so
# an integer-saved legacy plan looks unchanged vs the pre-feature
# behaviour.
age_range = f"Age {format_age_label(p1_current_age)} → {format_age_label(last_age)}"

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
# Stacked vertical bars (one per year, split into ISA / GIA / Cash /
# Property / DC Pension). Replaces the previous stacked-area chart —
# bars make per-year magnitudes and per-asset shares easier to read
# at-a-glance than stacked areas (the area chart's smooth fills made
# it hard to tell whether a slice "grew" or "just wasn't obscured by
# other slices in that year"). The y-axis is pinned at the per-year
# peak total plus 1% headroom so a £-amount in any year is directly
# comparable 1-for-1 with the same £-amount in any other year. Bar
# size is fixed at 18px so ~30 yearly bars fit side-by-side on
# standard Streamlit widths without merging. The 1.0 floor below
# ensures the chart is still renderable when the household has zero
# assets across the whole horizon.
# -------------------------
peak_total = float(df[ASSET_COLUMNS].sum(axis=1).max())
# Use 1% (NOT 0% / 5%) headroom: tight enough that per-year asset
# values are visually 1-for-1 comparable across the horizon (a £500k
# slice and a £400k slice differ by exactly the 25% on-screen height
# ratio that the data implies), with enough clearance that the
# topmost segment doesn't crash into Altair's topmost y-axis tick /
# legend. The 1.0 floor below ensures the chart is still renderable
# when the household has zero assets across the horizon.
y_axis_max = max(peak_total * 1.01, 1.0)

st.subheader(f"📈 Asset Allocation Over Time ({age_range})")
st.caption(
    "Stacked vertical bars — one bar per year, split into "
    "ISA / GIA / Cash / Property / DC Pension. Total bar height = "
    "gross household wealth at that age; each color-segment = one "
    f"asset's share. Y-axis is fixed at the per-year PEAK total "
    f"(£{peak_total:,.0f}) so a £-amount in any year is directly "
    "comparable 1-for-1 with the same £-amount in any other year."
)

# Add the `AgeLabel` column so the Altair x-axis renders compact
# "Xy Ym" tick text instead of legacy "55.8333…" fractional values.
# `Age` (the float) is preserved so the tooltip still shows the
# numeric age. `id_vars=["Age", "AgeLabel"]` keeps BOTH columns
# through the melt below.
df = add_age_label_column(df)

melt_stack = df.melt(
    id_vars=["Age", "AgeLabel"],
    value_vars=ASSET_COLUMNS,
    var_name="Asset Class",
    value_name="Value",
)

stack_chart = (
    alt.Chart(melt_stack)
    .mark_bar(size=18)
    .encode(
        x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
        y=alt.Y(
            "Value:Q",
            title="£ (gross wealth)",
            stack="zero",
            scale=alt.Scale(domain=[0, y_axis_max], nice=False),
            axis=alt.Axis(format=",.0f"),
        ),
        color=alt.Color(
            "Asset Class:N",
            sort=ASSET_COLUMNS,
            scale=alt.Scale(scheme="category10"),
            title="Asset class",
            legend=alt.Legend(orient="right"),
        ),
        order=alt.Order("color_N_order:Q", sort="ascending"),
        tooltip=[
            "Age",
            "Asset Class",
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
    # `step=1.0` (float) — NOT `step=1` (int). `p1_current_age` /
    # `last_age` are now floats (Person.age was retyped to `float` so
    # the years+months widget can persist months-precision), and
    # Streamlit requires ALL of `min_value`, `max_value`, `value`,
    # and `step` to share the same type. Passing `step=1` triggers:
    #   StreamlitAPIException: Slider value arguments must be of
    #   matching types. (`min_value` has float type, `max_value` has
    #   float type, `step` has int type.)
    # `1.0` keeps the snap-to-integer-year behaviour intact (any
    # slider value `v` satisfies `v == min_value + k*1.0` for integer
    # `k`, so the user still lands on whole-year boundaries).
    step=1.0,
    # NOTE — Streamlit `st.slider` does NOT accept a `format_func`
    # kwarg. That parameter belongs to `st.selectbox` / `st.radio`
    # only; passing it to a slider raises
    #   TypeError: SliderMixin.slider() got an unexpected keyword
    #   argument 'format_func'.
    # The slider's own `format="%.1f"` accepts a printf-style STRING
    # (not a callable), so it can't render the "55y 10m"
    # frac-of-year tick labels we use elsewhere on the page. We
    # deliberately drop the formatter here and rely on the
    # `st.write(f"### Age {format_age_label(selected_age)} ...")`
    # heading immediately below the slider to surface the rich
    # label. The slider tick text falls back to numeric floats
    # (e.g. "55.0", "56.0", "57.0") — readable and consistent with
    # the float `age_column` already on every chart in the app.
    # The slider VALUE (the float) is unchanged, so the downstream
    # `int(round(selected_age - p1_current_age))` row-index
    # expression still gets the same float input.
)

row = df.iloc[int(round(selected_age - p1_current_age))]

# Why `int(round(...))` and not just `int(...)`?
# `p1_current_age` is now a `float` so the slider's `step=1` arithmetic
# can produce a non-integer delta if the user lands on a fractional
# current_age (`age=55.5` ⇒ `selected_age=56.5`, delta `= 1.0` ✓ but
# `age=55.5` ⇒ `selected_age=57.5`, delta `= 2.0` ✓ — fine in theory,
# FP edge cases at half-year boundaries can also yield `0.9999...`).
# Pandas `iloc` strictly requires an integer scalar; a float scalar
# raises `IndexError: .iloc requires numeric index or integer array`.
# `round` halves FP noise (banker's rounding for `.5` half-cases is
# acceptable here — a half-year boundary already represents “equal
# distance between two integer year rows,” so `round` to either side
# is a defensible rounding direction). The result is an `int` so
# future pandas versions that drop float-tolerance emit no
# `DeprecationWarning`.
# `selected_age == p1_current_age` at the slider's default value →
# delta == 0, and `int(round(0))` is 0, so the start-of-simulation
# row still indexes cleanly.

asset_mix_df = pd.DataFrame({
    "Asset Class": ASSET_COLUMNS,
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

st.write(f"### Age {format_age_label(selected_age)}  (total £{selected_total:,.0f})")

mix_chart = (
    alt.Chart(asset_mix_df)
    .mark_bar(size=42)
    .encode(
        x=alt.X("Asset Class:N", sort=ASSET_COLUMNS, title="Asset class"),
        y=alt.Y(
            "Value:Q",
            title="Value (£)",
            scale=alt.Scale(domain=[0, y_axis_max], nice=False),
            axis=alt.Axis(format=",.0f"),
        ),
        color=alt.Color(
            "Asset Class:N",
            sort=ASSET_COLUMNS,
            scale=alt.Scale(scheme="category10"),
            legend=None,
        ),
        tooltip=[
            "Asset Class",
            alt.Tooltip("Value:Q", format=",.0f", title="Value £"),
        ],
    )
    .properties(height=320)
)
st.altair_chart(mix_chart, use_container_width=True)

st.caption(
    "Single-year bar chart (a Streamlit-native pie-chart "
    "alternative). The y-axis is fixed at the same peak total as "
    "the stacked vertical bars chart above, so the absolute height of any "
    "bar at any selected age is directly comparable to any other "
    "age."
)
