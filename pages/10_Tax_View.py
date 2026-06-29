import streamlit as st
import pandas as pd

from simulation.charts import to_int_pounds

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

# Same `p1_current_age` exception pattern as pages/11_Timeline.py — the
# Home-page bare `int(...)` would KeyError here because Timeline has no
# upstream `required_keys` guard. Fall back to 55 so the Age axis still
# renders a sensible range.
try:
    p1_current_age = int(
        st.session_state.household_data["person1"]["age"]
    )
except (KeyError, TypeError, ValueError):
    p1_current_age = 55

sim_horizon = len(results["years"])
last_age = p1_current_age + sim_horizon - 1
age_range = f"Age {p1_current_age} → {last_age}"

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

st.subheader(f"📊 Net vs Gross Income ({age_range})")
st.line_chart(df, x="Age", y=["Gross Income", "Net Income"])

st.subheader(f"💸 Tax Paid Each Year ({age_range})")
st.bar_chart(df, x="Age", y="Tax")

st.subheader(f"📈 Effective Tax Rate ({age_range})")
st.line_chart(df, x="Age", y="Effective Tax Rate")

st.subheader("📄 Data Table")
# Drop Year from display — Age is the natural axis now and the table
# is wide enough that Year adds noise.
st.dataframe(df.drop(columns=["Year"]))
