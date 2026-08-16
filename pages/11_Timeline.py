import streamlit as st
from brand_chrome import apply_chrome
import pandas as pd
import altair as alt

from simulation.charts import to_int_pounds
from storage import init_household
from simulation.years_and_months import (
    add_age_label_column,
    attach_age_columns,
    format_age_label,
    get_p1_current_age,
)
from pages_helpers.view_badge import render_view_mode_badge
from pages_helpers.today_value_toggle import render_today_value_toggle
from pages_helpers.household_builder import build_household_from_session_state
from pages_helpers.global_controls import render_global_controls_sidebar
from simulation.engine import run_simulation


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
apply_chrome()
render_global_controls_sidebar()

if "simulation_results" not in st.session_state or not st.session_state.simulation_results:
    st.warning("Please run a simulation first.")
    st.stop()

# -------------------------
# Today's-value toggle — Timeline mirror of the Home page toggle, so
# a user deep on this page can flip today's-value mode without
# navigating back to Home (cross-page consistency: the toggle
# writes the SAME `household_data["show_in_todays_value"]` flag the
# Home / Scenarios / What-If pages read on their next runs).
# -------------------------
def _rebuild_results_after_toggle_flip() -> None:
    """Rebuild `simulation_results` inline so Timeline charts
    re-render in today's-money terms on the very next rerender.
    Mirrors the Home page's `on_change` callback behaviour so the
    flip UX is consistent across pages."""
    household = build_household_from_session_state()
    st.session_state.simulation_results = run_simulation(household)

req_keys = ("person1", "person2", "assets", "spending")
_today_value_disabled = not all(
    k in st.session_state.household_data for k in req_keys
)
render_today_value_toggle(
    key_suffix="timeline",
    disabled=_today_value_disabled,
    on_change_rebuild_results=_rebuild_results_after_toggle_flip,
)

results = st.session_state.simulation_results

# View-mode badge — same rationale as the Home page's call.
# Placed immediately after the `results` binding and BEFORE the
# `p1_current_age` derivation so a user sees the badge first,
# before any other numerical chrome (subheaders, charts).
render_view_mode_badge(results)

# -------------------------
# Derive current age for the age-axis treatment. Centralised helper
# — replaces the duplicated `try: float(...); except: 55` block that
# used to live inline on this page (and pages 1/6/8/10/12/13).
# Timeline has NO upstream `required_keys` guard, so the
# `household_data["person1"]["age"]` access really can miss — the
# helper returns a 55.0 fallback in any failure mode.
# -------------------------
p1_current_age = get_p1_current_age(st.session_state.household_data)

sim_horizon = len(results["years"])
last_age = p1_current_age + sim_horizon - 1


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
# `format_age_label` returns compact "Xy Ym" labels (e.g. "55y" /
# "55y 10m"). Replaces the legacy `:g` formatter which truncated
# 5-6 sig figs and rendered fractional ages as decimal noise
# ("Age 55.8333 → 99.8333"). Whole-year ages render as "60y" so
# an integer-saved legacy plan looks unchanged vs the pre-feature
# behaviour. Note: this `age_range` line lives ~40 lines below the
# `sim_horizon` / `last_age` calc above because there's intermediate
# dataframe construction between them (stays intentionally inline
# with the rest of the page rather than hoisting above all sub-charts).
age_range = f"Age {format_age_label(p1_current_age)} → {format_age_label(last_age)}"
# Centralised age-label pipeline (consolidated from the prior
# inline `_add_age_column` helper on this page and the
# `_attach_age_column` helper on `pages/1_Home.py`). Both `Age`
# (float, for tooltips / numerics) and `AgeLabel` (string, for
# Altair `x="AgeLabel:O"` tick text) are produced in a single call.
df_age = attach_age_columns(df, p1_current_age)

# -------------------------
# Income, Spending, Mortgage Payment (Pension is on its OWN sub-chart below
# because the indexed pension creep is hard to read when squeezed against the
# much larger Income series on a shared y-axis).
# -------------------------
# Honour the "Include mortgage payment in spending figure" toggle from
# the Assets page. When True the engine's `total_need` treats the
# spending figure as total outgoings (mortgage included) and this chart
# shows the combined figure; when False today's three-line view (Income /
# Spending / Mortgage Payment) is preserved and the mortgage is funded on
# top. The toggle drives the engine's drawdown target AND this chart, so
# the income bars stay consistent with the Spending line either way.
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

# Convert the multi-series Income/Spending line chart to Altair so
# the x-axis can bind to `AgeLabel:O` (compact "Xy Ym" tick text)
# instead of the float `Age` column — native `st.line_chart` would
# render fractional ages as "55", "55.8333", "56", … on every tick.
income_melt = df_income_chart.melt(
    id_vars=["Age", "AgeLabel"],
    value_vars=series_to_plot,
    var_name="Series",
    value_name="Amount (£)",
)
income_chart = (
    alt.Chart(income_melt)
    .mark_line()
    .encode(
        x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
        y=alt.Y(
            "Amount (£):Q",
            title="£ per year",
            axis=alt.Axis(format=",.0f"),
        ),
        color=alt.Color(
            "Series:N",
            sort=series_to_plot,
            scale=alt.Scale(scheme="tableau10"),
            legend=alt.Legend(orient="right", title="Series"),
        ),
        tooltip=[
            "Age",
            alt.Tooltip("Series:N", title="Series"),
            alt.Tooltip("Amount (£):Q", format=",.0f", title="£"),
        ],
    )
    .properties(height=380)
)
st.altair_chart(income_chart, use_container_width=True)
st.caption(
    caption_extra
    + "Income is the household's annual take-home "
    "(post income-tax, post NI, post pension-income). It is floored "
    "at £0 so the line never dips below zero — the stacked bar below "
    "shows where each year's spend actually came from."
)

# -------------------------
# Indexed Pension — DB + State Pension only, on its own y-axis.
# Converted from `st.line_chart` to Altair so the x-axis binds to
# `AgeLabel:O` (compact "Xy Ym" tick text) instead of the float
# `Age` column.
# -------------------------
st.subheader(f"📈 Indexed Pension Over Time ({age_range})")
pension_chart = (
    alt.Chart(df_age)
    .mark_line()
    .encode(
        x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
        y=alt.Y(
            "Pension:Q",
            title="Indexed pension (£/yr)",
            axis=alt.Axis(format=",.0f"),
        ),
        tooltip=[
            "Age",
            alt.Tooltip("Pension:Q", format=",.0f", title="Pension £"),
        ],
    )
    .properties(height=320)
)
st.altair_chart(pension_chart, use_container_width=True)
st.caption(
    "DB Pension (post `draw_age`, indexed by `db_growth_rate`) + "
    "State Pension (post `state_pension_age`, indexed by "
    "`state_pension_growth_rate`), summed per partner. Each partner "
    "indexes at their own rate so the household's effective "
    "pension-creep year-on-year is the joined-up compound of the two."
)

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

# Add the `AgeLabel` column so the Altair x-axis renders compact
# "Xy Ym" tick text instead of legacy "55.8333…" fractional values.
# `Age` (the float) is preserved so the tooltip still shows the
# numeric age. `id_vars=["Age", "AgeLabel"]` keeps BOTH columns
# through the melt below.
src_df = add_age_label_column(src_df)

melt = src_df.melt(
    id_vars=["Age", "AgeLabel"],
    var_name="Source",
    value_name="Amount",
)
chart = (
    alt.Chart(melt)
    .mark_bar(size=14)
    .encode(
        x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
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
# Pre-retirement gate note — surfaces the engine's pre-retirement
# drawdown suppression policy (locked down by
# `TestDrawdownSuppressedPreRetirement` in tests/test_drawdown.py)
# so a user looking at the stacked bar and wondering why their
# working years show no drawdown bars / no ISA dips isn't left
# guessing. The companion planning-signal banner on Page 4
# (Spending) fires earlier in the workflow when `income <
# spending + mortgage` to nudge the user toward Page 2 before
# the timeline reveals the gap.
st.caption(
    """Pre-retirement years show no drawdown bars by design — drawdown is a post-retirement activity. If income < spending + mortgage pre-retirement, the Income line will sit below Spending to signal a real planning gap."""
)
# cash_buffer opt-in path — extends the gate note above. With the
# flag ON, Cash dips first, then ISA, then GIA in any working year
# where wages + DB + State Pension < spending + mortgage. Flag
# location: Page 3 (Assets) checkbox; production code: engine
# step 7's `elif cash_buffer_enabled`; test lock:
# tests/test_cash_buffer.py.
st.caption(
    """**When do ISA / GIA / Cash bars appear pre-retirement?** Only when the cash_buffer flag is ON (Page 3 (**Assets**) → 'For mortgage shortfalls, dip into Cash / ISA / GIA'). With the flag ON, Cash dips first, then ISA, then GIA in any working year where wages + DB pension + State Pension fall short of spending + mortgage."""
)

# -------------------------
# Net Worth — converted from `st.line_chart` to Altair so the x-axis
# binds to `AgeLabel:O` (compact "Xy Ym" tick text).
# -------------------------
st.subheader(f"📈 Net Worth Over Time ({age_range})")
net_worth_chart = (
    alt.Chart(df_age)
    .mark_line()
    .encode(
        x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
        y=alt.Y(
            "Net Worth:Q",
            title="Net worth (£)",
            axis=alt.Axis(format=",.0f"),
        ),
        tooltip=[
            "Age",
            alt.Tooltip("Net Worth:Q", format=",.0f", title="Net £"),
        ],
    )
    .properties(height=360)
)
st.altair_chart(net_worth_chart, use_container_width=True)
st.caption(
    "Net worth = total assets − outstanding mortgage. Driven by "
    "the asset waterfall in `simulation/drawdown.py`: pension "
    "drawdowns fund spending first, then Cash / ISA / GIA dip "
    "in priority order to cover any shortfall — those dips show up "
    "as the downward slope in retirement."
)

# -------------------------
# Mortgage — converted from `st.line_chart` to Altair so the x-axis
# binds to `AgeLabel:O` (compact "Xy Ym" tick text).
# -------------------------
st.subheader(f"🏠 Mortgage Balance Over Time ({age_range})")
mortgage_chart = (
    alt.Chart(df_age)
    .mark_line()
    .encode(
        x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
        y=alt.Y(
            "Mortgage Balance:Q",
            title="Outstanding mortgage (£)",
            axis=alt.Axis(format=",.0f"),
        ),
        tooltip=[
            "Age",
            alt.Tooltip(
                "Mortgage Balance:Q",
                format=",.0f",
                title="Mortgage £",
            ),
        ],
    )
    .properties(height=320)
)
st.altair_chart(mortgage_chart, use_container_width=True)
st.caption(
    "Outstanding mortgage balance at the end of each simulated "
    "year. Reaches £0 at `mortgage.end_year` (after which the line "
    "is flat at zero — overpayments accelerate this)."
)

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
    # `reset_index()` exposes Age as a column so `add_age_label_column`
    # can derive its `AgeLabel` string. Native `st.bar_chart` would
    # bind to the float Age index and show "55", "55.8333", … on the
    # x-axis; the Altair version binds to `AgeLabel:O` so tick text
    # renders "55y 10m".
    event_count = (
        event_df.groupby("Age").count().reset_index().rename(
            columns={"Event": "Count"}
        )
    )
    event_count = add_age_label_column(event_count)
    event_chart = (
        alt.Chart(event_count)
        .mark_bar(size=14)
        .encode(
            x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
            y=alt.Y(
                "Count:Q",
                title="Number of events",
                axis=alt.Axis(format=",.0f"),
            ),
            tooltip=[
                "Age",
                alt.Tooltip("Count:Q", format=",.0f", title="Events"),
            ],
        )
        .properties(height=240)
    )
    st.altair_chart(event_chart, use_container_width=True)
    st.caption(
        "Number of life-event rows scheduled to fire at each "
        "age. Useful for spotting ages where the household will "
        "be juggling multiple cashflows / property moves / "
        "gifting events in the same year."
    )
