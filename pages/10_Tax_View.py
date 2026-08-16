import streamlit as st
from brand_chrome import apply_chrome
import pandas as pd
import altair as alt

from simulation.charts import to_int_pounds
from simulation.years_and_months import (
    add_age_label_column,
    format_age_label,
    get_p1_current_age,
)
from pages_helpers.view_badge import render_view_mode_badge
from pages_helpers.global_controls import render_global_controls_sidebar


apply_chrome()
render_global_controls_sidebar()

st.title("💷 Tax View (Non‑Advice)")

st.write("""
This page shows a simple UK tax view of your retirement income.
It is **not financial advice** — it is an explanatory model only.
""")

# Guard against the "Reset Plan" path on the Home page, which explicitly
# sets `simulation_results = None` (the key still exists, so a key-only
# check passes and we crash on `results["years"]`). Pattern follows
# pages/7_AI_Analysis.py and pages/11_Timeline.py.
if "simulation_results" not in st.session_state or st.session_state.simulation_results is None:
    st.warning("Run a simulation first.")
    st.stop()

results = st.session_state.simulation_results

# View-mode badge — same rationale as the Home / Timeline calls.
# Placed FIRST after the `results` binding so the badge is the
# first thing the user sees when they open this page in today's-
# value mode (no matter which Tax View subheader they were about
# to scroll to).
render_view_mode_badge(results)

# Centralised age-derivation helper — replaces the duplicated
# `try: float(...); except: 55` blocks across pages 1/6/8/10/11/12/13.
# `St.session_state.household_data` may be missing the `person1/age`
# keys after a Reset Plan or on first render before init_household
# has seeded from disk — the helper returns a 55.0 fallback in any
# of those failure modes so the Age axis still renders a sensible
# range without crashing.
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

df = pd.DataFrame({
    "Year": results["years"],
    "Age": [y + p1_current_age for y in results["years"]],
    "Gross Income": to_int_pounds(results["gross_income"]),
    "Tax": to_int_pounds(results["tax"]),
    "Net Income": to_int_pounds(results["net_income"]),
    # Effective Tax Rate stays as a float — it's a percentage (0-50%) and
    # meaningful fractional precision is preserved at the chart layer
    # (e.g. 27.3% vs 27% is observable on the y-axis here).
    "Effective Tax Rate": results["effective_tax_rate"],
})

# Add the `AgeLabel` column so the Altair x-axis renders compact
# "Xy Ym" tick text instead of legacy "55.8333…" fractional values.
# `Age` (the float) is preserved so the tooltip still shows the
# numeric age.
df = add_age_label_column(df)

# -------------------------
# Net vs Gross Income — was `st.line_chart(df, x="Age", y=["Gross
# Income", "Net Income"])`. Multi-series native line chart was
# converted to Altair for the same reason as the other charts on
# this page: native `st.line_chart` binds the float `Age` column
# directly, so fractional ages render as "55", "55.8333", "56",
# "56.6667", … on the x-axis. Altair binds the x-axis to
# `AgeLabel:O` so each tick reads "55y", "55y 10m", "56y 8m",
# matching the section title. The dataframe is melted long-form
# so two series share the same y-axis encoding.
# -------------------------
st.subheader(f"📊 Net vs Gross Income ({age_range})")
income_melt = df.melt(
    id_vars=["Age", "AgeLabel"],
    value_vars=["Gross Income", "Net Income"],
    var_name="Series",
    value_name="Income",
)
income_chart = (
    alt.Chart(income_melt)
    .mark_line()
    .encode(
        x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
        y=alt.Y(
            "Income:Q",
            title="£ per year",
            axis=alt.Axis(format=",.0f"),
        ),
        color=alt.Color(
            "Series:N",
            sort=["Gross Income", "Net Income"],
            scale=alt.Scale(scheme="tableau10"),
            legend=alt.Legend(orient="right", title="Series"),
        ),
        tooltip=[
            "Age",
            alt.Tooltip("Series:N", title="Series"),
            alt.Tooltip("Income:Q", format=",.0f", title="Income £"),
        ],
    )
    .properties(height=360)
)
st.altair_chart(income_chart, use_container_width=True)
st.caption(
    "Gross Income is total household earnings BEFORE income tax + "
    "National Insurance; Net Income is the take-home after both. "
    "Both lines clamped at £0 so a future engine refactor that "
    "loosens the pre-clamp behaviour cannot surprise the UI with "
    "negative take-home."
)

# -------------------------
# Tax Paid Each Year — was `st.bar_chart(df, x="Age", y="Tax")`.
# Same conversion rationale as above: Altair binds the x-axis to
# `AgeLabel:O` so tick labels render "55y 10m" instead of decimal
# noise. Bar size is fixed at 14px so ~30 yearly bars fit
# side-by-side on standard Streamlit widths without merging.
# -------------------------
st.subheader(f"💸 Tax Paid Each Year ({age_range})")
tax_chart = (
    alt.Chart(df)
    .mark_bar(size=14)
    .encode(
        x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
        y=alt.Y(
            "Tax:Q",
            title="Tax (£)",
            axis=alt.Axis(format=",.0f"),
        ),
        tooltip=[
            "Age",
            alt.Tooltip("Tax:Q", format=",.0f", title="Tax £"),
        ],
    )
    .properties(height=360)
)
st.altair_chart(tax_chart, use_container_width=True)
st.caption(
    "Income Tax + National Insurance for that year. The Effective "
    "Tax Rate chart below normalises this against gross income — "
    "useful for spotting years where income spikes push the "
    "marginal rate into the higher bands."
)

# -------------------------
# Effective Tax Rate — was `st.line_chart(df, x="Age", y=
# "Effective Tax Rate")`. Same conversion rationale. The values
# are 0-1 floats; the y-axis uses the `.1%` format so a 0.273
# fraction renders as "27.3%" rather than the raw number.
# -------------------------
st.subheader(f"📈 Effective Tax Rate ({age_range})")
etr_chart = (
    alt.Chart(df)
    .mark_line()
    .encode(
        x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
        y=alt.Y(
            "Effective Tax Rate:Q",
            title="Effective tax rate",
            axis=alt.Axis(format=".1%"),
        ),
        tooltip=[
            "Age",
            alt.Tooltip(
                "Effective Tax Rate:Q",
                format=".2%",
                title="Effective rate",
            ),
        ],
    )
    .properties(height=320)
)
st.altair_chart(etr_chart, use_container_width=True)
st.caption(
    "Tax ÷ total income (earned + pension + drawdown) for that "
    "year — the household-level tax-burden percentage. Reads as "
    "27.3% on the y-axis but as 27.30% in the tooltip for "
    "sub-percent precision."
)

st.subheader("📄 Data Table")
# Drop Year from display — Age is the natural axis now and the table
# is wide enough that Year adds noise.
st.dataframe(df.drop(columns=["Year"]))
