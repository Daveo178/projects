import streamlit as st
import pandas as pd

st.title("💷 Tax View (Non‑Advice)")

st.write("""
This page shows a simple UK tax view of your retirement income.
It is **not financial advice** — it is an explanatory model only.
""")

if "simulation_results" not in st.session_state:
    st.warning("Run a simulation first.")
    st.stop()

results = st.session_state.simulation_results

df = pd.DataFrame({
    "Year": results["years"],
    "Gross Income": results["gross_income"],
    "Tax": results["tax"],
    "Net Income": results["net_income"],
    "Effective Tax Rate": results["effective_tax_rate"],
})

st.subheader("📊 Net vs Gross Income")
st.line_chart(df, x="Year", y=["Gross Income", "Net Income"])

st.subheader("💸 Tax Paid Each Year")
st.bar_chart(df, x="Year", y="Tax")

st.subheader("📈 Effective Tax Rate")
st.line_chart(df, x="Year", y="Effective Tax Rate")

st.subheader("📄 Data Table")
st.dataframe(df)
