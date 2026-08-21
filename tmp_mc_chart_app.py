import json
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

from pages_helpers.household_builder import build_household_from_session_state
from simulation.monte_carlo import monte_carlo_simulation

st.set_page_config(layout="wide")

with open(r"C:\Users\badad\Downloads\couples_retirement_plan.json", encoding="utf-8") as f:
    data = json.load(f)

st.session_state.household_data = data
household = build_household_from_session_state()
np.random.seed(2026)
mc = monte_carlo_simulation(household, runs=300, today_value_mode=bool(data.get("show_in_todays_value", False)))
p1_current_age = float(data["person1"]["age"])
diagnostics_df = pd.DataFrame(mc.get("run_diagnostics", []))
path_matrix = np.asarray(mc["all_paths"], dtype=float)
total_paths, path_years = path_matrix.shape
max_display_paths = 500
if total_paths > max_display_paths:
    keep_indices = np.unique(np.linspace(0, total_paths - 1, max_display_paths, dtype=int))
    path_matrix = path_matrix[keep_indices]
else:
    keep_indices = np.arange(total_paths)
displayed_paths = path_matrix.shape[0]
all_paths_df = pd.DataFrame({
    "Run": np.repeat(np.arange(1, displayed_paths + 1), path_years),
    "Age": np.tile([y + p1_current_age for y in range(path_years)], displayed_paths),
    "Net Worth": path_matrix.reshape(-1),
})
outcome_by_run = diagnostics_df["Outcome"].tolist()
all_paths_df["Outcome"] = np.repeat([outcome_by_run[i] for i in keep_indices], path_years)
if np.isfinite(path_matrix).all():
    lb = float(np.percentile(path_matrix, 5, axis=0).min())
    ub = float(np.percentile(path_matrix, 95, axis=0).max())
    if lb == ub:
        lb, ub = lb - 1.0, ub + 1.0
    pad = (ub - lb) * 0.02
    axis_domain = [lb - pad, ub + pad]
else:
    axis_domain = [-1.0, 1.0]
if not np.isfinite(all_paths_df["Net Worth"]).all():
    all_paths_df = all_paths_df[np.isfinite(all_paths_df["Net Worth"])]

def make_chart():
    return (
        alt.Chart(all_paths_df)
        .mark_line(opacity=0.08, strokeWidth=0.6)
        .encode(
            x=alt.X("Age:Q", title="Age"),
            y=alt.Y("Net Worth:Q", title="Net worth (£)", scale=alt.Scale(domain=axis_domain), axis=alt.Axis(format=",.0f")),
            detail=alt.Detail("Run:N"),
            color=alt.Color("Outcome:N", scale=alt.Scale(domain=["Succeeded", "Failed", "Unknown"],
                            range=["#2a6f6f", "#c0392b", "#8a8a8a"]), title="Outcome"),
            tooltip=[alt.Tooltip("Run:N", title="Run"), alt.Tooltip("Age:Q", title="Age", format=".1f"),
                     alt.Tooltip("Net Worth:Q", title="Net worth", format=",.0f"), "Outcome:N"],
        )
        .properties(height=460)
    )

base = make_chart()
variants = [
    ("A: fit + container (current)", base, True),
    ("B: pad + container", base.properties(autosize={"type": "pad", "contains": "padding"}), True),
    ("G: fit-x + container", base.properties(autosize={"type": "fit-x", "contains": "padding"}), True),
    ("H: fit + no contains + container", base.properties(autosize={"type": "fit"}), True),
    ("I: pad, no contains + container", base.properties(autosize={"type": "pad"}), True),
    ("J: fit-x, no contains + container", base.properties(autosize={"type": "fit-x"}), True),
]
for label, chart, use_cw in variants:
    st.write(f"### {label}")
    st.altair_chart(chart, use_container_width=use_cw)
