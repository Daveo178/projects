import streamlit as st
from brand_chrome import apply_chrome
import pandas as pd
import numpy as np
import altair as alt

from simulation.monte_carlo import monte_carlo_simulation
from simulation.charts import failure_age_histogram, to_int_pounds
from simulation.years_and_months import format_age_label, get_p1_current_age
from storage import init_household
from pages_helpers.household_builder import build_household_from_session_state
from pages_helpers.global_controls import render_global_controls_sidebar
from pages_helpers.today_value_toggle import render_today_value_toggle


st.title("🎲 Monte Carlo Simulation")

st.write("""
This page runs a full Monte Carlo simulation of your retirement plan.

It uses:
- Randomised investment returns  
- Randomised inflation  
- Randomised spending shocks  
- Sequence‑of‑returns risk  
- 1000 independent simulation runs  

The result is a **probability of success** and a **fan chart** showing the range of possible outcomes.
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

required_keys = ["person1", "person2", "assets", "spending"]
missing = [k for k in required_keys if k not in data]

if missing:
    st.warning(f"Missing required data: {', '.join(missing)}. Please complete the input pages.")
    st.stop()

# Monte Carlo can now display either nominal or today's-money outcomes.
# The toggle persists the choice so the percentile bands use the same
# currency basis as the deterministic pages.
render_today_value_toggle(key_suffix="monte_carlo")

# -------------------------
# Build household object — delegated to the shared helper.
# The Monte Carlo engine simulates nominal stochastic paths internally
# and converts the displayed paths to today's money when requested.
# -------------------------
household = build_household_from_session_state()

# -------------------------
# Age axis (consistent with pages 10/11/12/13): `Year` is a year-offset
# from simulation start; `Age = Year + p1_current_age`. Centralised
# helper — replaces the duplicated `try: float(...); except: 55` block
# that used to live inline on this page (and pages 1/6/10/11/12/13).
# -------------------------
p1_current_age = get_p1_current_age(data)

# -------------------------
# Run Monte Carlo
# -------------------------
runs = st.number_input("Number of Monte Carlo runs", 100, 5000, 1000, key="mc_runs")

if st.button("Run Monte Carlo Simulation", key="run_mc"):
    with st.spinner("Running Monte Carlo simulation..."):
        mc = monte_carlo_simulation(
            household,
            runs=runs,
            today_value_mode=bool(data.get("show_in_todays_value", False)),
        )

    st.success("Monte Carlo simulation complete!")
    if data.get("show_in_todays_value", False):
        st.caption(
            "All Monte Carlo wealth figures below are in today's money. "
            "Each path is simulated with its own random inflation path, "
            "then converted using that path's cumulative inflation."
        )
    else:
        st.caption(
            "Monte Carlo wealth figures below are nominal future pounds. "
            "Turn on the today's-value toggle above to remove each path's "
            "sampled inflation from the displayed wealth figures."
        )

    # Compute the end-of-simulation age once and reuse across the 3
    # age-bearing subheaders below. `mc["percentiles"]["p50"]` is the
    # longest canonical series so its length is the simulation horizon;
    # `format_age_label` produces the same compact "Xy Ym" labels used
    # on pages 10/11/12 so the Monte Carlo chart titles match the rest
    # of the app.
    mc_horizon = len(mc["percentiles"]["p50"])
    last_age = p1_current_age + mc_horizon - 1
    age_range = (
        f"Age {format_age_label(p1_current_age)} \u2192 "
        f"{format_age_label(last_age)}"
    )

    # -------------------------
    # Probability of success — explicit numerator/denominator so the
    # failure histogram below is obviously NOT showing every run.
    # The user flagged that the "X% of simulations" phrasing was
    # ambiguous — was the histogram a count of all 1000 runs or just
    # the failures? Adding the `passed of N` form makes the
    # denominator unambiguous at a glance, and the caption
    # explicitly tells the user that the failure histogram below
    # shows only the failed runs.
    # -------------------------
    st.subheader("\U0001F4CA Probability of Success")
    passed = sum(1 for f in mc["failure_years"] if f is None)
    failed = runs - passed
    st.write(
        f"**{mc['success_rate'] * 100:.1f}%** "
        f"({passed} of {runs} runs) did not run out of money."
    )
    if failed > 0:
        st.caption(
            f"Failed: {failed} run{'s' if failed != 1 else ''}. "
            f"The histogram below shows the failure ages of those "
            f"{failed} runs only — the other {passed} runs are NOT "
            f"shown (they didn't run out of money)."
        )
    else:
        st.caption(
            f"All {runs} runs succeeded. The failure histogram below "
            f"is therefore empty."
        )

    # -------------------------
    # Percentile fan chart
    # -------------------------
    st.subheader(f"\U0001F4C8 Net Worth Percentile Bands ({age_range})")

    years = list(range(len(mc["percentiles"]["p50"])))

    df = pd.DataFrame({
        "Age": [y + p1_current_age for y in years],
        "10th Percentile": to_int_pounds(mc["percentiles"]["p10"]),
        "25th Percentile": to_int_pounds(mc["percentiles"]["p25"]),
        "Median (50th)": to_int_pounds(mc["percentiles"]["p50"]),
        "75th Percentile": to_int_pounds(mc["percentiles"]["p75"]),
        "90th Percentile": to_int_pounds(mc["percentiles"]["p90"]),
    })

    st.line_chart(
        df,
        x="Age",
        y=[
            "10th Percentile",
            "25th Percentile",
            "Median (50th)",
            "75th Percentile",
            "90th Percentile"
        ]
    )

    # -------------------------
    # Failure year histogram
    # -------------------------
    st.subheader(f"\U0001F4A5 Failure Age Distribution ({age_range})")

    # `failure_years` is a list of year-OFFSETS (per `monte_carlo.py`: the
    # `enumerate(results["net_worth"])` index, not an absolute year).
    # Convert absolutes for chart consistency with the rest of the app.
    failure_ages = [fy + p1_current_age for fy in mc["failure_years"] if fy is not None]

    if len(failure_ages) == 0:
        st.success("No failures in any simulation run.")
    else:
        # Keep ages precise internally, but use categorical month labels on
        # the chart so a fractional current age cannot render as a long
        # floating-point value such as 75.94250513347023.
        hist_df = failure_age_histogram(
            mc["failure_years"],
            p1_current_age,
        )
        failure_age_order = hist_df["Failure Age"].tolist()
        failure_chart = (
            alt.Chart(hist_df)
            .mark_bar()
            .encode(
                x=alt.X(
                    "Failure Age:N",
                    title="Failure age",
                    sort=failure_age_order,
                ),
                y=alt.Y(
                    "Failed Runs:Q",
                    title="Failed runs",
                    axis=alt.Axis(format="d"),
                ),
                tooltip=[
                    alt.Tooltip("Failure Age:N", title="Age"),
                    alt.Tooltip("Failed Runs:Q", title="Runs"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(failure_chart, use_container_width=True)
        st.caption(
            "Pension figures are gross, so income tax reduces the amount "
            "available for spending. For example, £33,600 of gross pensions "
            "is about £31,600 after the modelled tax, before any DC top-up. "
            "The Monte Carlo also varies investment returns, inflation and "
            "spending from run to run; a failure is recorded when year-end "
            "nominal simulated net worth is £0 or below."
        )

    # -------------------------
    # Worst-case, median, and best-case paths — split into THREE
    # separate charts. The previous single-chart overlay was
    # almost useless: the single-run extremes (all_paths.min /
    # all_paths.max) span a huge range that squished the median
    # into a thin band at the chart centre. With three independent
    # charts, each gets its own y-axis scale appropriate to its
    # data, and the median is no longer visually compressed.
    #
    # Note: "worst case" and "best case" here are the SINGLE most
    # extreme runs out of `runs`, NOT percentiles — `all_paths.min`
    # and `all_paths.max` pick one path each. The percentile fan
    # chart above (p10 / p25 / p50 / p75 / p90) covers the
    # percentile interpretation. If a future user wants
    # percentile-based "worst case" semantics, swap
    # `all_paths.min(axis=0)` for `mc["percentiles"]["p10"]` and
    # `all_paths.max(axis=0)` for `mc["percentiles"]["p90"]`.
    # -------------------------
    all_paths = np.array(mc["all_paths"])
    worst_path = all_paths.min(axis=0)
    best_path = all_paths.max(axis=0)

    st.subheader(f"\U0001F4C9 Worst-Case Net Worth Curve ({age_range})")
    df_worst = pd.DataFrame({
        "Age": [y + p1_current_age for y in years],
        "Worst case (min at each year)": to_int_pounds(worst_path),
    })
    st.line_chart(
        df_worst,
        x="Age",
        y="Worst case (min at each year)",
    )
    st.caption(
        f"The minimum net worth at each year across all {runs} runs. "
        f"Note: this is a synthetic composite, NOT a single contiguous "
        f"run — the worst value at year 0 may come from a different "
        f"run than the worst at year 1 (axis=0 reduction over the "
        f"`(n_runs, n_years)` matrix). Y-axis is bounded by £0 because "
        f"assets can't go below zero (they just run out)."
    )

    st.subheader(f"\U0001F4CA Median (50th Percentile) Net Worth Path ({age_range})")
    df_median = pd.DataFrame({
        "Age": [y + p1_current_age for y in years],
        "Median (50th percentile)": to_int_pounds(mc["percentiles"]["p50"]),
    })
    st.line_chart(
        df_median,
        x="Age",
        y="Median (50th percentile)",
    )
    st.caption(
        "The 50th percentile path — half of the simulated runs "
        "ended above this line, half below. This is the best "
        "single-line representation of the 'typical' outcome."
    )

    st.subheader(f"\U0001F4C8 Best-Case Net Worth Curve ({age_range})")
    df_best = pd.DataFrame({
        "Age": [y + p1_current_age for y in years],
        "Best case (max at each year)": to_int_pounds(best_path),
    })
    st.line_chart(
        df_best,
        x="Age",
        y="Best case (max at each year)",
    )
    st.caption(
        f"The maximum net worth at each year across all {runs} runs. "
        f"Note: this is a synthetic composite, NOT a single contiguous "
        f"run — the best value at year 0 may come from a different "
        f"run than the best at year 1 (axis=0 reduction over the "
        f"`(n_runs, n_years)` matrix). Y-axis is unbounded because "
        f"asset growth is uncapped."
    )
