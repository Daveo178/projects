import streamlit as st
import pandas as pd

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
if "simulation_results" not in st.session_state:
    st.warning("Please run a simulation first.")
    st.stop()

results = st.session_state.simulation_results

# -------------------------
# Build DataFrame
# -------------------------
df = pd.DataFrame({
    "Year": results["years"],
    "ISA": results["isa_value"],
    "GIA": results["gia_value"],
    "Cash": results["cash_value"],
    "Property": results["property_value"],
    "DC Pension": results["dc_pot"],
})

# -------------------------
# Stacked Area Chart
# -------------------------
st.subheader("📈 Asset Allocation Over Time (Stacked Area)")

st.area_chart(
    df,
    x="Year",
    y=["ISA", "GIA", "Cash", "Property", "DC Pension"]
)

# -------------------------
# Pie Chart for a Selected Year
# -------------------------
st.subheader("🥧 Asset Mix in a Specific Year")

year = st.slider("Select Year", 0, len(df) - 1, 0)

row = df.iloc[year]

pie_df = pd.DataFrame({
    "Asset": ["ISA", "GIA", "Cash", "Property", "DC Pension"],
    "Value": [row["ISA"], row["GIA"], row["Cash"], row["Property"], row["DC Pension"]],
})

st.write(f"### Year {year}")

st.bar_chart(pie_df, x="Asset", y="Value")

st.write("This bar chart acts as a pie‑chart alternative (Streamlit native).")
