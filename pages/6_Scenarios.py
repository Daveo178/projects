import streamlit as st
import pandas as pd

from models.person import Person
from models.asset import Asset
from models.mortgage import Mortgage
from models.household import Household
from models.events import LifeEvent
from simulation.engine import run_simulation
# from simulation.monte_carlo import monte_carlo_simulation   # Optional upgrade
from simulation.charts import net_worth_chart, to_int_pounds
from storage import init_household

st.title("🔀 Scenario Comparison")
st.write("Compare two retirement scenarios side-by-side.")

# ---------------------------------------------------------
# 1. Ensure household data exists — load from disk on first visit
# ---------------------------------------------------------
init_household(st.session_state)

if not st.session_state.household_data:
    st.warning("Please enter your pension, assets, spending and events first.")
    st.stop()

data = st.session_state.household_data

# ---------------------------------------------------------
# Age axis (consistent with pages 10/11/12): `Year` is a year-offset
# from simulation start; `Age = Year + p1_current_age`. Same fallback
# pattern — default 55 if `data["person1"]["age"]` is missing.
# ---------------------------------------------------------
try:
    p1_current_age = int(data["person1"]["age"])
except (KeyError, TypeError, ValueError):
    p1_current_age = 55

# ---------------------------------------------------------
# 2. Scenario A Inputs (persistent)
# ---------------------------------------------------------
st.header("Scenario A")

a_spending = st.number_input(
    "Scenario A spending (£)",
    0,
    200_000,
    st.session_state.get("a_spending", data.get("spending", 30000)),
    key="a_spending"
)

a_ret_age_p1 = st.number_input(
    "Scenario A: Dave retirement age",
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
    "Scenario A: Shaz retirement age",
    min_value=0.0,
    max_value=80.0,
    value=float(st.session_state.get("a_ret_age_p2", data["person2"]["retirement_age"])),
    step=0.5,
    key="a_ret_age_p2"
)

a_strategy = st.selectbox(
    "Scenario A drawdown strategy",
    ["Fixed", "Inflation-adjusted", "Safe Withdrawal (4%)"],
    index=["Fixed", "Inflation-adjusted", "Safe Withdrawal (4%)"].index(
        st.session_state.get("a_strategy", data.get("drawdown_strategy", "Fixed"))
    ),
    key="a_strategy"
)

# ---------------------------------------------------------
# 3. Scenario B Inputs (persistent)
# ---------------------------------------------------------
st.header("Scenario B")

b_spending = st.number_input(
    "Scenario B spending (£)",
    0,
    200_000,
    st.session_state.get("b_spending", data.get("spending", 35000)),
    key="b_spending"
)

b_ret_age_p1 = st.number_input(
    "Scenario B: Dave retirement age",
    min_value=0.0,
    max_value=80.0,
    value=float(st.session_state.get("b_ret_age_p1", data["person1"]["retirement_age"])),
    step=0.5,
    key="b_ret_age_p1"
)

b_ret_age_p2 = st.number_input(
    "Scenario B: Shaz retirement age",
    min_value=0.0,
    max_value=80.0,
    value=float(st.session_state.get("b_ret_age_p2", data["person2"]["retirement_age"])),
    step=0.5,
    key="b_ret_age_p2"
)

b_strategy = st.selectbox(
    "Scenario B drawdown strategy",
    ["Fixed", "Inflation-adjusted", "Safe Withdrawal (4%)"],
    index=["Fixed", "Inflation-adjusted", "Safe Withdrawal (4%)"].index(
        st.session_state.get("b_strategy", data.get("drawdown_strategy", "Fixed"))
    ),
    key="b_strategy"
)

# ---------------------------------------------------------
# 4. Run Comparison
# ---------------------------------------------------------
if st.button("Run Comparison"):

    # ---------------- Scenario A ----------------
    p1A = Person(**data["person1"])
    p2A = Person(**data["person2"])
    p1A.retirement_age = a_ret_age_p1
    p2A.retirement_age = a_ret_age_p2

    assetsA = [Asset(**a) for a in data["assets"]]
    mortgageA = Mortgage(**data["mortgage"]) if data.get("mortgage") else None
    eventsA = [LifeEvent(**e) for e in data.get("events", [])]

    householdA = Household(
        person1=p1A,
        person2=p2A,
        assets=assetsA,
        mortgage=mortgageA,
        spending_target=a_spending,
        drawdown_strategy=a_strategy,
        events=eventsA
    )

    resultsA = run_simulation(householdA)
    dfA = net_worth_chart(resultsA)
    dfA["Scenario A"] = dfA["Net Worth"]

    # ---------------- Scenario B ----------------
    p1B = Person(**data["person1"])
    p2B = Person(**data["person2"])
    p1B.retirement_age = b_ret_age_p1
    p2B.retirement_age = b_ret_age_p2

    assetsB = [Asset(**a) for a in data["assets"]]
    mortgageB = Mortgage(**data["mortgage"]) if data.get("mortgage") else None
    eventsB = [LifeEvent(**e) for e in data.get("events", [])]

    householdB = Household(
        person1=p1B,
        person2=p2B,
        assets=assetsB,
        mortgage=mortgageB,
        spending_target=b_spending,
        drawdown_strategy=b_strategy,
        events=eventsB
    )

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

    # ---------------------------------------------------------
    # 6. Display Chart
    # ---------------------------------------------------------
    st.subheader("📊 Net Worth Comparison")
    st.line_chart(combined, x="Age", y=["Scenario A", "Scenario B"])

    # ---------------------------------------------------------
    # 7. Optional: Monte Carlo success probability
    # ---------------------------------------------------------
    # mcA = monte_carlo_simulation(householdA)
    # mcB = monte_carlo_simulation(householdB)
    #
    # st.write(f"Scenario A success probability: {mcA['success_rate']*100:.1f}%")
    # st.write(f"Scenario B success probability: {mcB['success_rate']*100:.1f}%")
