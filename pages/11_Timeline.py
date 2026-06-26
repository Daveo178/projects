import streamlit as st
import pandas as pd

st.title("📅 Retirement Timeline")

st.write("""
This page shows a full timeline of your retirement plan:
- Income  
- Spending  
- Net worth  
- Mortgage  
- Life events  
""")

# -------------------------
# Ensure simulation exists
# -------------------------
if "simulation_results" not in st.session_state:
    st.warning("Please run a simulation first.")
    st.stop()

results = st.session_state.simulation_results

# -------------------------
# Build DataFrame
# -------------------------
df = pd.DataFrame({
    "Year": results["years"],
    "Income": results["income"],
    "Spending": results["spending"],
    "Net Worth": results["net_worth"],
    "Mortgage Balance": results["mortgage_balance"],
})

# -------------------------
# Income vs Spending
# -------------------------
st.subheader("💰 Income vs Spending Over Time")
st.line_chart(df, x="Year", y=["Income", "Spending"])

# -------------------------
# Net Worth
# -------------------------
st.subheader("📈 Net Worth Over Time")
st.line_chart(df, x="Year", y="Net Worth")

# -------------------------
# Mortgage
# -------------------------
st.subheader("🏠 Mortgage Balance Over Time")
st.line_chart(df, x="Year", y="Mortgage Balance")

# -------------------------
# Life Events Timeline
# -------------------------
st.subheader("🎉 Life Events Timeline")

events = results["events_triggered"]

event_rows = []
for year, ev_list in enumerate(events):
    for ev in ev_list:
        event_rows.append({"Year": year, "Event": ev})

if len(event_rows) == 0:
    st.info("No life events in this plan.")
else:
    event_df = pd.DataFrame(event_rows)
    st.dataframe(event_df)

    # Optional: event count chart
    event_count = event_df.groupby("Year").count()
    st.bar_chart(event_count)
