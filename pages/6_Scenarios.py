import streamlit as st
from brand_chrome import apply_chrome

import pandas as pd

from simulation.engine import run_simulation
from pages_helpers.household_builder import build_household_from_session_state
from pages_helpers.global_controls import render_global_controls_sidebar
# from simulation.monte_carlo import monte_carlo_simulation   # Optional upgrade
from simulation.charts import net_worth_chart, to_int_pounds
from simulation.years_and_months import format_age_label, get_p1_current_age
from storage import init_household
from pages_helpers.today_value_toggle import render_today_value_toggle
from pages_helpers.strategy_options import (
    DRAW_DOWN_STRATEGIES,
    normalize_drawdown_strategy,
)


st.title("🔀 Scenario Comparison")
st.write("Compare two retirement scenarios side-by-side.")

# ---------------------------------------------------------
# 1. Ensure household data exists — load from disk on first visit
# ---------------------------------------------------------
init_household(st.session_state)

# Render brand chrome so the brand palette + stylesheet propagate
# to this page (LIGHT palette only — the dark-mode radio was dropped).
apply_chrome()
render_global_controls_sidebar()

if not st.session_state.household_data:
    st.warning("Please enter your pension, assets, spending and events first.")
    st.stop()

data = st.session_state.household_data

# -------------------------
# Today's-value toggle — Scenarios mirror of the Home-page toggle, so
# a user comparing two scenarios can flip today's-value mode here
# without going back to Home. The flag persists into
# `household_data["show_in_todays_value"]` and is read at the next
# "Run Comparison" click by the shared `build_household_from_session_state`
# helper (which propagates the flag to the returned `Household` dataclass
# so `simulation.engine.resolve_today_value_settings` picks it up).
# No inline rebuild callback — this page runs only when the user clicks
# "Run Comparison", so persisting the flag is sufficient.
# -------------------------
_today_value_disabled = not all(
    k in data for k in ("person1", "person2", "assets", "spending")
)
render_today_value_toggle(
    key_suffix="scenarios",
    disabled=_today_value_disabled,
)

# ---------------------------------------------------------
# Age axis (consistent with pages 10/11/12): `Year` is a year-offset
# from simulation start; `Age = Year + p1_current_age`. Centralised
# helper — replaces the duplicated `try: float(...); except: 55` block
# that used to live inline on this page (and pages 1/8/10/11/12/13).
# ---------------------------------------------------------
p1_current_age = get_p1_current_age(data)

# ---------------------------------------------------------
# 2. Scenario A Inputs (persistent)
# ---------------------------------------------------------
st.header("Scenario A")

a_spending = st.number_input(
    "Scenario A spending (£)",
    0.0,
    200_000.0,
    float(st.session_state.get("a_spending", data.get("spending", 30000))),
    key="a_spending"
)

a_ret_age_p1 = st.number_input(
    "Scenario A: Person 1 retirement age",
    min_value=0.0,
    max_value=80.0,
    # step=0.5 + float value so users can compare e.g. "retire at 60.5"
    # vs "retire at 60" without the form snapping back to integers.
    # Cast to float so a legacy int saved value still seeds without a
    # type error.
    value=float(st.session_state.get("a_ret_age_p1", data["person1"]["retirement_age"])),
    step=0.5,
    key="a_ret_age_p1"
)

a_ret_age_p2 = st.number_input(
    "Scenario A: Person 2 retirement age",
    min_value=0.0,
    max_value=80.0,
    value=float(st.session_state.get("a_ret_age_p2", data["person2"]["retirement_age"])),
    step=0.5,
    key="a_ret_age_p2"
)

strategy_options = list(DRAW_DOWN_STRATEGIES)
a_strategy_value = normalize_drawdown_strategy(
    st.session_state.get("a_strategy", data.get("drawdown_strategy", "Fixed"))
)
# Correct an invalid legacy/session value before Streamlit restores the
# keyed widget state; normalizing only the selectbox index is not enough.
st.session_state["a_strategy"] = a_strategy_value
a_strategy = st.selectbox(
    "Scenario A drawdown strategy",
    strategy_options,
    index=strategy_options.index(a_strategy_value),
    key="a_strategy"
)

# ---------------------------------------------------------
# 3. Scenario B Inputs (persistent)
# ---------------------------------------------------------
st.header("Scenario B")

b_spending = st.number_input(
    "Scenario B spending (£)",
    0.0,
    200_000.0,
    float(st.session_state.get("b_spending", data.get("spending", 35000))),
    key="b_spending"
)

b_ret_age_p1 = st.number_input(
    "Scenario B: Person 1 retirement age",
    min_value=0.0,
    max_value=80.0,
    value=float(st.session_state.get("b_ret_age_p1", data["person1"]["retirement_age"])),
    step=0.5,
    key="b_ret_age_p1"
)

b_ret_age_p2 = st.number_input(
    "Scenario B: Person 2 retirement age",
    min_value=0.0,
    max_value=80.0,
    value=float(st.session_state.get("b_ret_age_p2", data["person2"]["retirement_age"])),
    step=0.5,
    key="b_ret_age_p2"
)

b_strategy_value = normalize_drawdown_strategy(
    st.session_state.get("b_strategy", data.get("drawdown_strategy", "Fixed"))
)
st.session_state["b_strategy"] = b_strategy_value
b_strategy = st.selectbox(
    "Scenario B drawdown strategy",
    strategy_options,
    index=strategy_options.index(b_strategy_value),
    key="b_strategy"
)

# ---------------------------------------------------------
# 4. Run Comparison
# ---------------------------------------------------------
if st.button("Run Comparison"):

    # ---------------- Scenario A ----------------
    # Build the household from session_state via the shared helper
    # (saves the seven-step Person / Asset / Mortgage / LifeEvent /
    # Household construction that used to live inline here). The
    # helper also propagates `show_in_todays_value` to the
    # Household dataclass — previously a latent bug because the
    # engine reads the flag from the dataclass, not from
    # session_state. Per-scenario overrides (retirement_age,
    # spending_target, drawdown_strategy) are applied via
    # mutation AFTER the helper builds, since the helper doesn't
    # need to know about the page's per-scenario customisations.
    householdA = build_household_from_session_state()
    householdA.person1.retirement_age = a_ret_age_p1
    householdA.person2.retirement_age = a_ret_age_p2
    householdA.spending_target = a_spending
    householdA.drawdown_strategy = a_strategy

    resultsA = run_simulation(householdA)
    dfA = net_worth_chart(resultsA)
    dfA["Scenario A"] = dfA["Net Worth"]

    # ---------------- Scenario B ----------------
    # Same helper-then-mutate pattern as Scenario A. A and B
    # intentionally share the same `show_in_todays_value` flag
    # because the helper reads it from `household_data` once per
    # call — a single Run Comparison click reads the flag once
    # and both scenarios inherit it, so a side-by-side
    # comparison is always in the same view-mode.
    householdB = build_household_from_session_state()
    householdB.person1.retirement_age = b_ret_age_p1
    householdB.person2.retirement_age = b_ret_age_p2
    householdB.spending_target = b_spending
    householdB.drawdown_strategy = b_strategy

    resultsB = run_simulation(householdB)
    dfB = net_worth_chart(resultsB)
    dfB["Scenario B"] = dfB["Net Worth"]

    # ---------------------------------------------------------
    # 5. Merge safely (longevity-aware)
    # ---------------------------------------------------------
    combined = pd.merge(
        dfA[["Year", "Scenario A"]],
        dfB[["Year", "Scenario B"]],
        on="Year",
        how="outer"
    ).sort_values("Year").ffill()

    # Defensive re-round: today both scenarios share the same years so the
    # outer-merge + ffill never produces NaN and the int dtype from
    # `net_worth_chart` flows through untouched. But as soon as someone
    # adds "different end-year per scenario", `ffill` would silently
    # upcast int -> float64 and reintroduce the rounding slip we just
    # fixed. `to_int_pounds` is NaN-safe (preserves NaN), so re-applying
    # it post-merge keeps the whole-pound invariant across the merge
    # boundary regardless of horizon parity.
    combined["Scenario A"] = to_int_pounds(combined["Scenario A"].tolist())
    combined["Scenario B"] = to_int_pounds(combined["Scenario B"].tolist())

    # Convert Year-offset axis to absolute Age for chart consistency,
    # then drop the now-redundant `Year` column so the displayed
    # dataframe is a clean 3-column set (Age + Scenario A + Scenario B).
    combined["Age"] = combined["Year"] + p1_current_age
    combined = combined.drop(columns=["Year"])

    # Compute the end-of-simulation age once and reuse on the chart
    # subheader below. A and B share the same engine horizon (both
    # `run_simulation(...)` calls without an explicit `years=` param),
    # so `len(resultsA["years"]) == len(resultsB["years"])` and either
    # can be the source for `sim_horizon`. `format_age_label` produces
    # the same compact "Xy Ym" labels used on pages 10/11/12 so the
    # scenario-comparison chart title matches the rest of the app.
    sim_horizon = len(resultsA["years"])
    last_age = p1_current_age + sim_horizon - 1
    age_range = (
        f"Age {format_age_label(p1_current_age)} \u2192 "
        f"{format_age_label(last_age)}"
    )

    # ---------------------------------------------------------
    # 6. Display Chart
    # ---------------------------------------------------------
    st.subheader(f"\U0001F4CA Net Worth Comparison ({age_range})")
    st.line_chart(combined, x="Age", y=["Scenario A", "Scenario B"])

    # ---------------------------------------------------------
    # 7. Optional: Monte Carlo success probability
    # ---------------------------------------------------------
    # mcA = monte_carlo_simulation(householdA)
    # mcB = monte_carlo_simulation(householdB)
    #
    # st.write(f"Scenario A success probability: {mcA['success_rate']*100:.1f}%")
    # st.write(f"Scenario B success probability: {mcB['success_rate']*100:.1f}%")
