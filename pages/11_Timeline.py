import streamlit as st
import pandas as pd
import altair as alt

from simulation.charts import to_int_pounds
from storage import init_household

st.title("📅 Retirement Timeline")

st.write("""
This page shows a full timeline of your retirement plan:
- Income / Spending / Mortgage Payment
- Indexed Pension
- Net worth
- Mortgage Balance
- Annual Funding Sources (stacked by source)
- Life events
""")

# -------------------------
# Ensure simulation AND household data exist
# -------------------------
init_household(st.session_state)

if "simulation_results" not in st.session_state or not st.session_state.simulation_results:
    st.warning("Please run a simulation first.")
    st.stop()

results = st.session_state.simulation_results

# -------------------------
# Derive current age for the age-axis treatment. The Pension page stores
# `age` as an int (via `st.number_input` with int min/max). Unlike the Home
# page, Timeline has NO upstream `required_keys` guard, so the dict access
# really can miss — the bare `int(...)` Home uses would KeyError here.
# Fall back to 55 so the page still renders a usable axis range.
# -------------------------
try:
    p1_current_age = int(
        st.session_state.household_data["person1"]["age"]
    )
except (KeyError, TypeError, ValueError):
    p1_current_age = 55

sim_horizon = len(results["years"])
last_age = p1_current_age + sim_horizon - 1


def _add_age_column(frame):
    """Return a copy of `frame` with an `Age` column derived from its
    `Year` column. Replaces `Year` so plot axes and table headers come out
    as actual ages, matching the Home-page convention."""
    out = frame.copy()
    out["Age"] = out["Year"] + p1_current_age
    return out


# -------------------------
# Build DataFrame
# -------------------------
# `mortgage_payment` and `pension_income` are newer results fields. Older
# saved sessions may still carry results from before these fields existed
# — fall back to all zeros so the third / fourth lines simply render flat
# at £0 rather than crashing the page.
mortgage_payment = results.get(
    "mortgage_payment",
    [0.0] * len(results["years"]),
)
pension_income = results.get(
    "pension_income",
    [0.0] * len(results["years"]),
)

df = pd.DataFrame({
    "Year": results["years"],
    "Income": to_int_pounds(results["income"]),
    "Spending": to_int_pounds(results["spending"]),
    "Mortgage Payment": to_int_pounds(mortgage_payment),
    "Pension": to_int_pounds(pension_income),
    "Net Worth": to_int_pounds(results["net_worth"]),
    "Mortgage Balance": to_int_pounds(results["mortgage_balance"]),
})

# Compute the age-axis version once — the three line charts below share it.
age_range = f"Age {p1_current_age} → {last_age}"
df_age = _add_age_column(df)

# -------------------------
# Income, Spending, Mortgage Payment (Pension is on its OWN sub-chart below
# because the indexed pension creep is hard to read when squeezed against the
# much larger Income series on a shared y-axis).
# -------------------------
# Honour the "Include mortgage payment in displayed spending" toggle from
# the Assets page. When True the Spending line on this chart shows the
# combined figure (lifestyle + mortgage); when False today's three-line
# view (Income / Spending / Mortgage Payment) is preserved. The engine
# itself is unchanged — both columns are already summed in drawdown's
# total_need — so the toggle is purely a presentation concern on this
# and the home page chart.
include_mortgage_in_spending = (
    st.session_state.household_data
    .get("mortgage", {})
    .get("include_in_spending", False)
)

st.subheader(
    f"💰 Income, Spending & Mortgage Payment ({age_range})"
)
# Clamp the Income line at £0. The engine already does this on its own
# (defensive `max(0, income)` at the end of the drawdown block), but the
# chart applies a second guard so a future engine refactor that loosens
# the pre-clamp behaviour cannot surprise the UI with negative take-home.
# Spending / Mortgage Payment lines keep their raw values — they are not
# wallet-fill figures and the user explicitly wants to see them above
# zero even if mortages haven't started yet.
income_clamped = (
    pd.Series(to_int_pounds(results["income"]))
    .clip(lower=0)
    .astype(int)
    .tolist()
)
df_income_chart = df_age.copy()
df_income_chart["Income"] = income_clamped

if include_mortgage_in_spending:
    # Combine the two columns into a single "Spending" series for the
    # toggle-ON view, then drop the separate "Mortgage Payment" column
    # so the line chart only sees what it should plot. Element-wise
    # pandas Series sum is already int64+int64 → int64, so no extra
    # `.astype(int)` is needed (it would be a no-op).
    combined_spending = (
        pd.Series(to_int_pounds(results["spending"]))
        + pd.Series(to_int_pounds(mortgage_payment))
    )
    df_income_chart = df_income_chart.drop(
        columns=["Spending", "Mortgage Payment"]
    )
    df_income_chart["Spending"] = combined_spending
    series_to_plot = ["Income", "Spending"]
    caption_extra = (
        "Spending includes the annual mortgage payment "
        "(lifestyle + mortgage, combined). "
    )
else:
    # The default 3-line frame is already constructed by the
    # df_age frame above; just point at the columns we want.
    df_income_chart["Spending"] = to_int_pounds(results["spending"])
    df_income_chart["Mortgage Payment"] = to_int_pounds(mortgage_payment)
    series_to_plot = ["Income", "Spending", "Mortgage Payment"]
    caption_extra = ""

st.line_chart(df_income_chart, x="Age", y=series_to_plot)
st.caption(
    caption_extra
    + "Income is the household's annual take-home "
    "(post income-tax, post NI, post pension-income). It is floored "
    "at £0 so the line never dips below zero — the stacked bar below "
    "shows where each year's spend actually came from."
)

# -------------------------
# Indexed Pension — DB + State Pension only, on its own y-axis.
# -------------------------
st.subheader(f"📈 Indexed Pension Over Time ({age_range})")
st.line_chart(df_age, x="Age", y="Pension")

# -------------------------
# Annual Funding Sources — stacked bar, one bar per age, each colour
# segment shows the £ contribution that year from one source.
#
# Funding source order (bottom-up of stack, also legend top-down):
#   1. Earned Income       — wages during working years.
#   2. DB Pension          — post `draw_age`, RPI/CPI indexed.
#   3. State Pension       — post `state_pension_age`, triple-locked.
#   4. UFPLS Tax-free      — 25% PCLS slice of each UFPLS drawdown.
#   5. UFPLS Taxable       — pre-tax £ drawn from DC pot as UFPLS.
#                            Drops to £0 quickly once the pot empties —
#                            this is the user-visible expression of the
#                            engine's phantom-drawdown fix.
#   6. ISA Withdrawals     — asset waterfall residual after UFPLS.
#   7. GIA Withdrawals     — ditto, drawn after ISA.
#   8. Cash Withdrawals    — drawn first in the residual waterfall.
#
# All series are read with `.get(key, zeros)` so older saved results
# (pre phantom-drawdown-fix) still render flat at 0 for the new keys,
# rather than crashing the page.
# -------------------------
st.subheader(f"📊 Annual Funding Sources ({age_range})")

FUNDING_SOURCES = [
    ("Earned Income",      "earned_income"),
    ("DB Pension",         "db_payout"),
    ("State Pension",      "state_payout"),
    ("UFPLS Tax-free",     "tax_free_income"),
    ("UFPLS Taxable",      "ufpls_taxable_gross"),
    ("ISA Withdrawals",    "isa_draw"),
    ("GIA Withdrawals",    "gia_draw"),
    ("Cash Withdrawals",   "cash_draw"),
]
src_df = pd.DataFrame({"Age": df_age["Age"]})
for label, key in FUNDING_SOURCES:
    raw = results.get(key, [0.0] * len(results["years"]))
    src_df[label] = (
        pd.Series(to_int_pounds(raw))
        .clip(lower=0)  # defensive second clamp
        .astype(int)
    )

melt = src_df.melt(id_vars=["Age"], var_name="Source", value_name="Amount")
chart = (
    alt.Chart(melt)
    .mark_bar(size=14)
    .encode(
        x=alt.X("Age:O", title="Age"),
        y=alt.Y("Amount:Q", title="£ per year", stack="zero"),
        color=alt.Color(
            "Source:N",
            sort=[label for label, _ in FUNDING_SOURCES],
            scale=alt.Scale(scheme="tableau10"),
            legend=alt.Legend(orient="right", title="Funding source"),
        ),
        tooltip=[
            "Age",
            alt.Tooltip("Source:N", title="Source"),
            alt.Tooltip("Amount:Q", format=",.0f", title="Amount £"),
        ],
    )
    .properties(height=440)
)
st.altair_chart(chart, use_container_width=True)
st.caption("""
Each bar shows where the year's spending was actually funded from,
stacked bottom-up:

* **Earned Income** — wages from pre-retirement work.
* **DB Pension** — defined-benefit pension (after `draw_age`,
  indexed by `db_growth_rate`, default 2.5%).
* **State Pension** — UK State Pension after `state_pension_age`,
  indexed by `state_pension_growth_rate`.
* **UFPLS Tax-free** — pension lump-sum via PCLS — the 25% tax-free
  portion of each UFPLS drawdown.
* **UFPLS Taxable** — pre-tax £ drawn from the DC pot as UFPLS
  (the remaining 75% subject to income tax). Drops to £0 once the
  DC pot empties — there is no phantom 50/50 split.
* **ISA / GIA / Cash Withdrawals** — non-pension assets drawn in
  priority order (Cash first, ISA next, GIA last) to cover any
  shortfall after pension income. Spikes here are how the chart
  shows the household dipping into its wealth.
""")

# -------------------------
# Net Worth
# -------------------------
st.subheader(f"📈 Net Worth Over Time ({age_range})")
st.line_chart(df_age, x="Age", y="Net Worth")

# -------------------------
# Mortgage
# -------------------------
st.subheader(f"🏠 Mortgage Balance Over Time ({age_range})")
st.line_chart(df_age, x="Age", y="Mortgage Balance")

# -------------------------
# Life Events Timeline — event rows and the count chart both key off the
# same `Age` column as the line charts above.
# -------------------------
st.subheader("🎉 Life Events Timeline")

events = results["events_triggered"]

event_rows = []
for year, ev_list in enumerate(events):
    age_at_event = year + p1_current_age
    for ev in ev_list:
        event_rows.append({"Age": age_at_event, "Event": ev})

if len(event_rows) == 0:
    st.info("No life events in this plan.")
else:
    event_df = pd.DataFrame(event_rows)
    st.dataframe(event_df)

    # Optional: event count chart, grouped by age of occurrence.
    event_count = event_df.groupby("Age").count()
    st.bar_chart(event_count)
