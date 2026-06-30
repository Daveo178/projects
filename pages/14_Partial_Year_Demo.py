"""
`pages/14_Partial_Year_Demo.py` — self-contained story page that exercises
the months-precision `retirement_age` feature added across the engine,
`models/person.py`, and the Years+Months form on `pages/2_Pensions.py`.

The headline: retiring 6 months later (vs exactly the rounded age)
produces a non-trivial uplift in the DC pot at the simulation horizon,
because the engine's step 2a/2b now wires
`fraction = min(1.0, retirement_offset - year)` into `_dc_monthly_compound`
so the fractional closing-year slice actually compounds AND contributes
(not just "rounded down to integer and lose the partial year").

Unlike most other pages, this one is FULLY SELF-CONTAINED — built-in
defaults so the demo runs the moment the page is opened, with no need
for the user to fill in pages 2-3 first. Inputs are themed around a
"Single partner" so the math reads cleanly; the multi-partner partial-
year independence contract is locked separately in
`tests/test_partial_year_retirement.py`.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import altair as alt

from models.person import Person
from models.household import Household
from simulation.engine import (
    _dc_monthly_compound,
    run_simulation,
)


# -------------------------------------------------------------
# Hero copy + framing
# -------------------------------------------------------------
st.set_page_config(
    page_title="Partial-Year Retirement Demo",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("⏱️ Partial-Year Retirement Demo")

st.write(
    """
Retiring at exactly **60** vs **60½** matters more than you'd think — six more
months of contributions, six more months of growth on those contributions, and
six more months of growth on the existing pot.

The simulation engine's step 2a/2b now wires `fraction = min(1.0,
retirement_offset - year)` into `_dc_monthly_compound` so a partial-year
`retirement_age` actually compounds AND contributes for the fractional slice
(rather than silently rounding down to the previous integer and forfeiting it).

Adjust the inputs below to see the diff play out live.
"""
)


# -------------------------------------------------------------
# Defaults baked into the page so the demo runs even if the user
# hasn't filled in the planner pages yet. Theme: a single partner
# aged 55 earning £60k with a 15% pension contribution and a £100k
# opening DC pot compounding at 5%/yr — broadly representative of a
# mid-career UK household planning their next 5-10 year horizon.
# -------------------------------------------------------------
DEFAULTS = dict(
    current_age=55,
    annual_income=60_000.0,
    dc_pot=100_000.0,
    dc_growth_pct=5.0,      # % form for the form; converted to decimal in helper
    contrib_pct=15.0,       # % form
    n_years=30,             # 55 → 85 horizon
    a_ret_age=60.0,         # integer-ish retirement
    b_ret_age=60.5,         # 6-month-later retirement
)


# -------------------------------------------------------------
# Single-partner helper — `run_simulation` requires a full Household
# with two Person objects. We build a SILENT partner2 (`state_pension_age=99`,
# `dc_pot=0`, `dc_growth_rate=0`, zero income / contributions / PCLS) so the
# active partner's DC pot is the only contributor to `results["dc_pot"]`.
# This matches the silent-partner pattern from
# `tests/test_partial_year_retirement.py` so the test fixture and the page
# agree on what "inert" means. `is_retired(year)` on the silent partner
# stays False throughout because retirement_age=99 is well past the
# horizon, leaving the post-retirement growth path on the silent partner
# definitively a no-op (pot stays 0 forever).
# -------------------------------------------------------------
def _build_demo_household(
    *,
    current_age: int,
    ret_age: float,
    annual_income: float,
    dc_pot: float,
    dc_growth: float,            # decimal form (e.g. 0.05)
    contrib_pct: float,          # decimal form (e.g. 0.15)
    n_years: int,
):
    active = Person(
        name="Active partner",
        age=current_age,
        retirement_age=ret_age,
        state_pension_age=99,
        dc_pot=dc_pot,
        db_income=0.0,
        draw_age=99,
        monthly_contrib=0.0,    # only the % pathway feeds M
        monthly_contrib_pct=contrib_pct,
        income_until_retirement=annual_income,
        income_growth_rate=0.0,  # flat income for a clean story
        pcls_percent=0,
        dc_growth_rate=dc_growth,
    )
    silent = Person(
        name="Silent partner (inert)",
        age=current_age,
        retirement_age=99,
        state_pension_age=99,
        dc_pot=0.0,
        db_income=0.0,
        draw_age=99,
        monthly_contrib=0.0,
        monthly_contrib_pct=0.0,
        income_until_retirement=0.0,
        income_growth_rate=0.0,
        pcls_percent=0,
        dc_growth_rate=0.0,
    )
    h = Household(
        person1=active,
        person2=silent,
        assets=[],                # no asset-growth interactions
        mortgage=None,            # no mortgage amortisation
        spending_target=0,        # no drawdown phase
        drawdown_strategy="Fixed",
        events=[],
    )
    return h, n_years


def _simulate_dc_pot(**kwargs) -> list[float]:
    """Run the engine and return ONLY the active partner's contribution
    to `results["dc_pot"]` (which is `person1.dc_pot + person2.dc_pot`).
    Since the silent partner's `dc_pot` stays at 0 across the whole
    horizon (zero opening, zero rate, zero contributions), the sum equals
    the active partner's pot alone — i.e., what the viewer expects a
    "single-partner story" to show."""
    h, n_years = _build_demo_household(**kwargs)
    results = run_simulation(h, years=n_years)
    return results["dc_pot"]


# -------------------------------------------------------------
# Controls — Streamlit auto-reruns every time an input changes,
# which is exactly what we want for a "live story" demo (the chart
# and metrics update on every keystroke / slider tick).
# -------------------------------------------------------------
st.subheader("⚙️ Demo inputs")

col_age, col_inc, col_pot, col_grw = st.columns(4)
with col_age:
    current_age = st.number_input(
        "Current age", min_value=18, max_value=80,
        value=DEFAULTS["current_age"], step=1, key="demo_current_age",
        help="The active partner's age today. Combined with retirement_age "
             "this determines how many years of contributions accumulate.",
    )
with col_inc:
    annual_income = st.number_input(
        "Annual income (£)", min_value=0, max_value=500_000,
        value=int(DEFAULTS["annual_income"]), step=5_000,
        key="demo_annual_income",
        format="%d",
        help="Annual pre-retirement salary. The engine computes the monthly "
             "DC contribution as `income × contribution_pct / 12`.",
    )
with col_pot:
    dc_pot = st.number_input(
        "DC pot opening (£)", min_value=0, max_value=5_000_000,
        value=int(DEFAULTS["dc_pot"]), step=10_000,
        key="demo_dc_pot", format="%d",
        help="Opening DC pot balance at simulation start. Compounds "
             "monthly at the DC growth rate.",
    )
with col_grw:
    dc_growth_pct = st.number_input(
        "DC growth (% / yr)", min_value=0.0, max_value=15.0,
        value=DEFAULTS["dc_growth_pct"], step=0.5, key="demo_dc_growth",
        help="Compounded monthly as (1 + r/12). 5% is a reasonable balanced-"
             "portfolio nominal return over a working career.",
    )

col_pct, col_yrs = st.columns(2)
with col_pct:
    contrib_pct_pct = st.number_input(
        "Pension contribution (% of income)", min_value=0.0, max_value=50.0,
        value=DEFAULTS["contrib_pct"], step=1.0,
        key="demo_contrib_pct",
        help="Total employee + employer pension contribution as a percentage "
             "of annual income. Add monthly to the DC pot at `contribution × "
             "income / 12` until retirement.",
    )
with col_yrs:
    n_years = st.slider(
        "Years simulated", min_value=5, max_value=50,
        value=DEFAULTS["n_years"], step=1, key="demo_n_years",
        help="How far to project the simulation. With `current_age=55` this "
             "defaults to age 85 (a 30-year horizon).",
    )

# Resolved inputs (the % string-inputs → decimal fractions the engine expects).
dc_growth = dc_growth_pct / 100.0
contrib_pct = contrib_pct_pct / 100.0

st.subheader("🅰️ vs 🅱️ — two retirement ages to compare")

col_a, col_b = st.columns(2)
with col_a:
    a_ret_age = st.number_input(
        "🅰️ Retirement age (Scenario A)",
        min_value=18.0, max_value=80.0,
        value=DEFAULTS["a_ret_age"], step=0.5, key="demo_a_ret_age",
        help="Default 60.0 (integer years+0 months). For the partial-year "
             "story, leave this at 60.0 and bump Scenario B to 60.5.",
    )
with col_b:
    b_ret_age = st.number_input(
        "🅱️ Retirement age (Scenario B)",
        min_value=18.0, max_value=80.0,
        value=DEFAULTS["b_ret_age"], step=0.5, key="demo_b_ret_age",
        help="Default 60.5 (60 years + 6 months). Works at any half-year "
             "increment — the engine handles 60.25, 60.75, etc. uniformly.",
    )


# -------------------------------------------------------------
# Compute once per render. Cache per-render so the rebuilds are quick
# (n_years=30 × 5 sensitivity scenarios ≈ 5 run_simulation calls, all
# pure-Python, sub-second total).
# -------------------------------------------------------------
common_kwargs = dict(
    current_age=current_age,
    annual_income=annual_income,
    dc_pot=dc_pot,
    dc_growth=dc_growth,
    contrib_pct=contrib_pct,
    n_years=n_years,
)

pot_a = _simulate_dc_pot(ret_age=a_ret_age, **common_kwargs)
pot_b = _simulate_dc_pot(ret_age=b_ret_age, **common_kwargs)

age_axis = list(range(current_age, current_age + n_years))


# -------------------------------------------------------------
# Math breakdown shared between the two tabs — the "where does the
# extra £X come from" summary. KEPT SIMPLE on purpose: only the
# cash-contribution bucket is mathematically exact. The compound
# effects (growth on those extra contributions to horizon, plus the
# compounding-cascade on the opening pot) eventually sum to the full
# `actual_diff = pot_b[-1] - pot_a[-1]` reported by the engine —
# but breaking them out into closed-form buckets neatly isn't exact
# (annuity-due timing of contributions across the closing partial-
# year slice interacts non-trivially with the post-gap compounding).
# The honest answer therefore is: report `actual_diff` as the
# ground-truth final number, and surface ONLY the precise bucket
# that has a clean closed form (extra cash contributions), with a
# short narrative that credits the engine rather than trying to
# decompose the rest.
#
# Edge case handling:
#   * `a_ret_age == b_ret_age` → `gap_months = 0`, narrative reports
#     "same retirement age", hero metric shows £0.
#   * `b_ret_age < a_ret_age`  → `gap_months < 0`, narrative flips
#     the direction and the metric-delta reflects the LOSS of
#     retiring earlier.
# -------------------------------------------------------------
def _math_breakdown(pot_a, pot_b) -> dict:
    """Return the gap direction + the one exact bucket (cash
    contributions) + the engine-reported ground-truth `actual_diff`.

    The compound-bucket math is intentionally NOT reproduced here —
    see the page-level comment above. The viewer's hero number is
    `actual_diff`; the cash-contribution bucket is the only number we
    can claim with mathematical precision.

    Banker's-rounding guard: `round(0.5) == 0` in Python under the
    half-to-even rule, so a half-month gap would otherwise silently
    register as `gap_months=0` and flip the narrative to "same
    retirement age". The `+ 1e-9` cushion nudges such edge cases up
    by a sub-ULP amount so `round()` returns the integer we actually
    want. Tiny enough that it doesn't affect any realistic input; the
    form's `step=0.5` constraint already prevents typical UI paths
    from hitting this corner.
    """
    gap_months = int(round(12 * (b_ret_age - a_ret_age) + 1e-9))
    M = annual_income * contrib_pct / 12
    extra_contribs = M * gap_months   # signed: positive = worked longer
    actual_diff = pot_b[-1] - pot_a[-1]   # engine ground truth
    if gap_months > 0:
        direction = "later"
    elif gap_months < 0:
        direction = "earlier"
    else:
        direction = "same"
    return {
        "gap_months": gap_months,
        "direction": direction,
        "extra_contribs": extra_contribs,
        "actual_diff": actual_diff,
    }


breakdown = _math_breakdown(pot_a, pot_b)


# -------------------------------------------------------------
# Tabs
# -------------------------------------------------------------
tab_diff, tab_sweep = st.tabs(["🅰️ vs 🅱️ Difference", "📈 Sensitivity Sweep"])


# =============================================================
# Tab 1: A vs B Difference — the headline story
# =============================================================
with tab_diff:
    # Three large metric columns — the visual centrepiece. Hero delta
    # shows signed `actual_diff` (engine ground truth); the delta-arrow
    # string-codes the direction (`abs` always positive).
    metric_a, metric_b, metric_delta = st.columns(3)
    with metric_a:
        st.metric(
            label=f"🅰️ Pot at horizon (retire at {a_ret_age:g})",
            value=f"£{pot_a[-1]:,.0f}",
        )
    with metric_b:
        st.metric(
            label=f"🅱️ Pot at horizon (retire at {b_ret_age:g})",
            value=f"£{pot_b[-1]:,.0f}",
        )
    with metric_delta:
        gap_label = abs(int(breakdown["gap_months"]))
        gap_noun = "month" if gap_label == 1 else "months"
        # Hero label is signed-direction so the user knows what the
        # delta represents even when it goes negative.
        if breakdown["direction"] == "same":
            hero_label = "💰 Δ at horizon (same retirement age)"
        elif breakdown["direction"] == "later":
            hero_label = f"💰 Δ from retiring {gap_label} {gap_noun} later"
        else:
            hero_label = f"💰 Δ from retiring {gap_label} {gap_noun} earlier"
        delta_arrow = "▲" if breakdown["actual_diff"] >= 0 else "▼"
        st.metric(
            label=hero_label,
            value=f"{delta_arrow} £{breakdown['actual_diff']:+,.0f}",
        )

    # Story copy — small, explanatory, between the metrics and the chart.
    # Only the cash-contributions bucket is mathematically exact (M ×
    # extra_months). The compound effects (growth on those contributions
    # + cascading compound on the opening pot) all flow through the
    # engine's partial-year branch and collapse into the reported
    # `actual_diff` — so the narrative credits the engine rather than
    # attempting an imprecise closed-form decomposition.
    gap_months_int = int(breakdown["gap_months"])
    direction = breakdown["direction"]
    if direction == "same":
        narrative = (
            f"🅰️ and 🅱️ are the **same retirement age** "
            f"({a_ret_age:g}). The two scenarios are mathematically "
            f"identical — the partial-year-of-contributions branch has "
            f"nothing to differentiate. The exact `actual_diff` is "
            f"£{breakdown['actual_diff']:+,.0f} (FP rounding only). "
            f"Bump 🅱️ by 0.5 or 1.0 to see the partial-year effect."
        )
    elif direction == "later":
        narrative = (
            f"Working **{gap_months_int} extra month{'s' if gap_months_int != 1 else ''}** "
            f"between age {a_ret_age:g} and {b_ret_age:g} adds "
            f"**£{breakdown['extra_contribs']:,.0f}** of pension "
            f"contributions (the only bucket with an exact closed "
            f"form). On top of that, the engine's partial-year-of-"
            f"contributions branch compounds those extra contributions "
            f"and applies extra growth to the existing pot during the "
            f"closing-year slice — the **total horizon-end effect is "
            f"£{breakdown['actual_diff']:+,.0f}** by age "
            f"{current_age + n_years}."
        )
    else:  # direction == "earlier"
        narrative = (
            f"Retiring **{abs(gap_months_int)} month{'s' if abs(gap_months_int) != 1 else ''} earlier** "
            f"(between age {b_ret_age:g} and {a_ret_age:g}) "
            f"costs **£{breakdown['extra_contribs']:,.0f}** of pension "
            f"contributions (signed negative). Through the engine's "
            f"partial-year-of-contributions branch, the total horizon-"
            f"end effect is **£{breakdown['actual_diff']:+,.0f}** — "
            f"a real loss of compounding power. This is a useful sanity "
            f"check: it confirms the partial-year branch fires for "
            f"`ret_age < a_ret_age` symmetrically."
        )
    st.info(narrative)

    # Line chart: dc_pot by age, two lines. Solid y-axis at the peak
    # total of both series so visuals are 1-for-1 comparable across
    # ages (same convention as `pages/12_Asset_Allocation.py`).
    st.subheader("📈 DC pot trajectory: 🅰️ vs 🅱️")

    chart_df = pd.DataFrame({
        "Age": age_axis,
        f"🅰️ Retire at {a_ret_age:g}": pot_a,
        f"🅱️ Retire at {b_ret_age:g}": pot_b,
    })
    chart_melt = chart_df.melt(
        id_vars=["Age"],
        value_vars=[
            f"🅰️ Retire at {a_ret_age:g}",
            f"🅱️ Retire at {b_ret_age:g}",
        ],
        var_name="Scenario",
        value_name="DC pot (£)",
    )
    peak_total = float(max(max(pot_a), max(pot_b))) * 1.01
    line_chart = (
        alt.Chart(chart_melt)
        .mark_line(strokeWidth=3)
        .encode(
            x=alt.X("Age:O", title="Age", sort="ascending"),
            y=alt.Y(
                "DC pot (£):Q",
                title="DC pot (£)",
                scale=alt.Scale(domain=[0, peak_total], nice=False),
                axis=alt.Axis(format=",.0f"),
            ),
            color=alt.Color(
                "Scenario:N",
                scale=alt.Scale(scheme="tableau10"),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[
                "Age",
                "Scenario",
                alt.Tooltip("DC pot (£):Q", format=",.0f", title="DC pot £"),
            ],
        )
        .properties(height=420)
    )
    st.altair_chart(line_chart, use_container_width=True)

    # Compact summary table — only the rows we can claim with
    # mathematical precision. The compound-growth rows are gone (the
    # engine's `actual_diff` is the ground truth; partial decomposition
    # was imprecise, see the math helper's docstring).
    st.subheader("📋 Summary")
    summary_df = pd.DataFrame({
        "Metric": [
            "Opening DC pot (today)",
            "Final DC pot (🅰️)",
            "Final DC pot (🅱️)",
            "Engine-reported Δ at horizon",
            "Extra pension contributions (cash only)",
        ],
        "Value (£)": [
            f"{dc_pot:,.0f}",
            f"{pot_a[-1]:,.0f}",
            f"{pot_b[-1]:,.0f}",
            f"{breakdown['actual_diff']:+,.0f}",
            (f"+{breakdown['extra_contribs']:,.0f}"
             if breakdown["extra_contribs"] >= 0
             else f"{breakdown['extra_contribs']:,.0f}"),
        ],
    })
    st.dataframe(summary_df, use_container_width=True, hide_index=True)


# =============================================================
# Tab 2: Sensitivity Sweep — 5 retirement ages from a_ret to a_ret+1
# =============================================================
with tab_sweep:
    st.write(
        f"""
Sweep retirement age from **{a_ret_age:g}** to **{a_ret_age + 1.0:g}** in
0.25-year steps. Each curve runs through the same engine code path so the
fractions between `🅰️` and the next integer share the same partial-year-of-
contributions wiring.

The lines diverge starting at age **{a_ret_age:g}** (where the first
scenario stops contributing) and re-converge into pure compound growth from
year **{int(a_ret_age + 1) - current_age + 1}** onward (all five scenarios
fully retired).
"""
    )

    sweep_offsets = [0.0, 0.25, 0.5, 0.75, 1.0]
    sweep_pot_series = []
    for offset in sweep_offsets:
        ret = a_ret_age + offset
        sweep_pot_series.append(
            _simulate_dc_pot(ret_age=ret, **common_kwargs)
        )

    # 5-line chart, one line per retirement-age value.
    sweep_df_dict = {"Age": age_axis}
    for offset, pot_series in zip(sweep_offsets, sweep_pot_series):
        label = f"Retire at {a_ret_age + offset:g}"
        sweep_df_dict[label] = pot_series
    sweep_df = pd.DataFrame(sweep_df_dict)
    sweep_melt = sweep_df.melt(
        id_vars=["Age"],
        value_vars=[f"Retire at {a_ret_age + o:g}" for o in sweep_offsets],
        var_name="Retirement age",
        value_name="DC pot (£)",
    )
    peak_sweep = float(
        max(max(s) for s in sweep_pot_series)
    ) * 1.01

    sweep_chart = (
        alt.Chart(sweep_melt)
        .mark_line(strokeWidth=2.5)
        .encode(
            x=alt.X("Age:O", title="Age", sort="ascending"),
            y=alt.Y(
                "DC pot (£):Q",
                title="DC pot (£)",
                scale=alt.Scale(domain=[0, peak_sweep], nice=False),
                axis=alt.Axis(format=",.0f"),
            ),
            color=alt.Color(
                "Retirement age:N",
                scale=alt.Scale(scheme="tableau10"),
                sort=[f"Retire at {a_ret_age + o:g}" for o in sweep_offsets],
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[
                "Age",
                "Retirement age",
                alt.Tooltip("DC pot (£):Q", format=",.0f", title="DC pot £"),
            ],
        )
        .properties(height=440)
    )
    st.altair_chart(sweep_chart, use_container_width=True)

    # Compact summary table — final horizon pot for each scenario +
    # the differential against the integer-floor baseline.
    sweep_summary_rows = []
    baseline_pot = sweep_pot_series[0][-1]  # ret_age = a_ret_age
    for offset, pot_series in zip(sweep_offsets, sweep_pot_series):
        sweep_summary_rows.append({
            "Retirement age (yrs)": f"{a_ret_age + offset:g}",
            f"DC pot at horizon (£)": f"{pot_series[-1]:,.0f}",
            f"Δ vs 🅰️ ({a_ret_age:g})": (
                "—" if offset == 0
                else f"{pot_series[-1] - baseline_pot:+,.0f}"
            ),
        })
    st.dataframe(
        pd.DataFrame(sweep_summary_rows),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "The Δ column shows the £-change vs the integer-floor baseline as "
        "the retirement age moves later in 0.25-year steps. Positive = the "
        "extra months produced a larger pot due to contributions + growth "
        "during the partial-year slice."
    )


# -------------------------------------------------------------
# Footer caption — link back to the planner pages + a math summary
# -------------------------------------------------------------
st.divider()
st.caption(
    "📖 Want to use this precision in your own plan? Open the **Pensions** "
    "page (sidebar) — the **Retirement age** field is now a Years + Months "
    "two-field form. Want to compare two scenarios against your full plan "
    "data? Open **Scenarios** — the retirement-age inputs there also accept "
    "half-year steps."
)
