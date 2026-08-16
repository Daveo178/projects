import streamlit as st
from brand_chrome import apply_chrome
import pandas as pd
import numpy as np

from simulation.engine import run_simulation
from simulation.monte_carlo import monte_carlo_simulation
from simulation.charts import to_int_pounds
from simulation.years_and_months import format_age_label, get_p1_current_age
from storage import init_household
from pages_helpers.household_builder import build_household_from_session_state
from pages_helpers.today_value_toggle import render_today_value_toggle
from pages_helpers.global_controls import render_global_controls_sidebar


st.title("🧪 What‑If Engine")

st.write("""
Experiment with different retirement scenarios:
- Retire earlier or later
- Change spending
- Adjust contributions
- Stress test investment returns
- Explore alternative futures
""")

# -------------------------
# Ensure data exists — seeded from disk if present
# -------------------------
init_household(st.session_state)
apply_chrome()
render_global_controls_sidebar()

if not st.session_state.household_data:
    st.warning("Please enter your pension, assets, spending and events first.")
    st.stop()

data = st.session_state.household_data

# -------------------------
# Today's-value toggle — What If mirror of the Home-page toggle, so
# a user running a "what-if" comparison can flip today's-value
# mode here without going back to Home. The flag persists into
# `household_data["show_in_todays_value"]` and is consumed by
# the next "Run What-If Scenario" click by the shared
# `build_household_from_session_state` helper (which propagates
# the flag to the returned `Household` dataclass so the
# deterministic `run_simulation` path honours it). No inline
# rebuild callback — this
# page only renders charts after the explicit Run click, so
# persisting is sufficient.
#
# The deterministic and Monte Carlo charts use the same displayed currency
# basis. Monte Carlo samples nominal market/inflation paths internally and
# converts completed paths to today's money when the toggle is enabled.
# -------------------------
_today_value_disabled = not all(
    k in data for k in ("person1", "person2", "assets", "spending")
)
render_today_value_toggle(
    key_suffix="what_if",
    disabled=_today_value_disabled,
)

# Age axis (consistent with pages 10/11/12): `Year` is a year-offset
# from simulation start; `Age = Year + p1_current_age`. Centralised
# helper — replaces the duplicated `try: float(...); except: 55`
# block that used to live inline on this page (and pages 1/6/8/10/11/12).
p1_current_age = get_p1_current_age(data)

required_keys = ["person1", "person2", "assets", "spending"]
missing = [k for k in required_keys if k not in data]

if missing:
    st.warning(f"Missing required data: {', '.join(missing)}. Please complete the input pages.")
    st.stop()

# -------------------------
# Build household object
# -------------------------
def build_household(overrides):
    """Build a What-If scenario household by delegating to the shared
    `build_household_from_session_state` helper, then mutating the
    returned `Household` dataclass to apply the page's per-run
    overrides (retirement_age, monthly_contrib, spending, asset
    growth rate). The helper handles the seven-step
    Person / Asset / Mortgage / LifeEvent / Household construction;
    this thin wrapper is just the page-specific override layer.

    `show_in_todays_value` is propagated by the helper itself from
    `st.session_state.household_data`. The deterministic path honours
    it, and the MC path uses the same choice for its displayed currency
    while preserving stochastic nominal sampling internally.
    """
    household = build_household_from_session_state()
    household.person1.retirement_age = overrides["ret_age_p1"]
    household.person2.retirement_age = overrides["ret_age_p2"]
    household.person1.monthly_contrib = overrides["contrib_p1"]
    household.person2.monthly_contrib = overrides["contrib_p2"]
    # The What-If contribution controls are explicit scenario inputs.
    # Clear the percentage/flat split fields so the overridden legacy
    # monthly amounts are not silently ignored by the engine's new-field
    # precedence rules.
    for person in (household.person1, household.person2):
        person.personal_contrib_pct = 0.0
        person.personal_contrib_flat_monthly = 0.0
        person.employer_contrib_pct = 0.0
        person.monthly_contrib_pct = 0.0
    household.spending_target = overrides["spending"]
    household.inflation_rate = overrides["inflation"]
    household.person1.dc_growth_rate = overrides["growth_rate"]
    household.person2.dc_growth_rate = overrides["growth_rate"]
    for asset in household.assets:
        asset.growth_rate = overrides["growth_rate"]
    return household

# -------------------------
# What‑If Controls
# -------------------------
st.subheader("Adjust Scenario")

col1, col2 = st.columns(2)

with col1:
    # `number_input` (NOT slider) with `step=0.5` so users can run a
    # What-If scenario with a partial-year retirement age — e.g. "What
    # if Person 1 retires at 59.5 instead of 60?" The slider widget is
    # int-only out of the box and can't discretise at half-year steps
    # elegantly. Mirrors the Pension page's Years+Months input shape —
    # just expressed as a single number + half-year step here because
    # the What-If page is a quick A/B tool, not a full planner form.
    ret_age_p1 = st.number_input(
        "Person 1 retirement age",
        min_value=0.0,
        max_value=80.0,
        value=float(data["person1"]["retirement_age"]),
        step=0.5,
    )
    contrib_p1 = st.number_input("Person 1 monthly contribution (£)", 0.0, 5000.0, float(data["person1"]["monthly_contrib"]))

with col2:
    ret_age_p2 = st.number_input(
        "Person 2 retirement age",
        min_value=0.0,
        max_value=80.0,
        value=float(data["person2"]["retirement_age"]),
        step=0.5,
    )
    contrib_p2 = st.number_input("Person 2 monthly contribution (£)", 0.0, 5000.0, float(data["person2"]["monthly_contrib"]))

spending = st.number_input("Annual spending target (£)", 5000.0, 200000.0, float(data["spending"]))

growth_rate = st.slider("Expected investment growth rate", 0.00, 0.10, 0.05, step=0.005)
inflation = st.slider("Inflation assumption", 0.00, 0.05, 0.025, step=0.005)

runs = st.number_input("Monte Carlo runs", 100, 5000, 1000)

# -------------------------
# Run Scenario
# -------------------------
if st.button("Run What‑If Scenario"):
    overrides = {
        "ret_age_p1": ret_age_p1,
        "ret_age_p2": ret_age_p2,
        "contrib_p1": contrib_p1,
        "contrib_p2": contrib_p2,
        "spending": spending,
        "growth_rate": growth_rate,
        "inflation": inflation,
    }

    household = build_household(overrides)

    with st.spinner("Running scenario..."):
        det = run_simulation(household)
        # Keep the stochastic horizon identical to the deterministic
        # scenario and the household's configured joint-life horizon.
        scenario_years = len(det["years"])
        mc = monte_carlo_simulation(
            household,
            runs=int(runs),
            years=scenario_years,
            today_value_mode=bool(household.show_in_todays_value),
        )

    st.success("Scenario complete!")

    # Compute the end-of-simulation age once PER CHART GROUP. The
    # deterministic engine path (`run_simulation`) and the Monte
    # Carlo path (`monte_carlo_simulation`) can return different
    # `years`-list lengths if either is wired to a different horizon
    # downstream — using a single `sim_horizon` here would silently
    # render a stale suffix on the MC subheader if the horizons ever
    # diverge. Two variables, used independently below.
    det_horizon = len(det["years"])
    det_last_age = p1_current_age + det_horizon - 1
    det_age_range = (
        f"Age {format_age_label(p1_current_age)} → "
        f"{format_age_label(det_last_age)}"
    )

    mc_horizon = len(mc["percentiles"]["p50"])
    mc_last_age = p1_current_age + mc_horizon - 1
    mc_age_range = (
        f"Age {format_age_label(p1_current_age)} → "
        f"{format_age_label(mc_last_age)}"
    )

    # -------------------------
    # Deterministic charts
    # -------------------------
    st.subheader(f"📈 Deterministic Net Worth ({det_age_range})")
    df_det = pd.DataFrame({
        "Age": [y + p1_current_age for y in det["years"]],
        "Net Worth": to_int_pounds(det["net_worth"]),
        "Income": to_int_pounds(det["income"]),
        "Spending": to_int_pounds(det["spending"]),
    })
    st.line_chart(df_det, x="Age", y="Net Worth")

    st.subheader(f"💰 Income vs Spending ({det_age_range})")
    st.line_chart(df_det, x="Age", y=["Income", "Spending"])

    # -------------------------
    # Currency-basis explanation. Both deterministic and Monte Carlo
    # charts use the same displayed currency basis. Monte Carlo retains
    # stochastic market/inflation paths while using this scenario's
    # household means and overrides.
    # -------------------------
    if household.show_in_todays_value:
        st.caption(
            "ℹ️ Both deterministic and Monte Carlo charts are shown in "
            "today's money. Monte Carlo keeps its random market and "
            "inflation paths, then converts each completed path using "
            "that path's cumulative inflation."
        )
    else:
        st.caption(
            "ℹ️ Both deterministic and Monte Carlo charts are shown in "
            "nominal future pounds."
        )

    # -------------------------
    # Monte Carlo — probability is a single-number output so no
    # `age_range` suffix on its subheader.
    # -------------------------
    st.subheader("🎲 Monte Carlo Success Probability")
    st.write(f"**{mc['success_rate'] * 100:.1f}%** probability of not running out of money.")

    st.subheader(f"📊 Monte Carlo Percentile Bands ({mc_age_range})")
    df_mc = pd.DataFrame({
        "Age": [y + p1_current_age for y in range(len(mc["percentiles"]["p50"]))],
        "10th": to_int_pounds(mc["percentiles"]["p10"]),
        "25th": to_int_pounds(mc["percentiles"]["p25"]),
        "50th": to_int_pounds(mc["percentiles"]["p50"]),
        "75th": to_int_pounds(mc["percentiles"]["p75"]),
        "90th": to_int_pounds(mc["percentiles"]["p90"]),
    })
    st.line_chart(df_mc, x="Age", y=["10th", "25th", "50th", "75th", "90th"])
