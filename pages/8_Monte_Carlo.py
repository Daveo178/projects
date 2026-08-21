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
    # Per-run diagnostics — lets the user inspect the sampled assumptions
    # behind successful and failed paths without crowding the charts.
    # -------------------------
    diagnostics_df = pd.DataFrame(mc.get("run_diagnostics", []))
    if not diagnostics_df.empty:
        with st.expander("🔎 Inspect rates and assumptions used in each run", expanded=False):
            st.caption(
                "One row represents one simulation. Failed runs show their "
                "failure year and age; return and inflation columns show the "
                "mean/minimum/maximum sampled over that run. Download the "
                "full table for filtering and further analysis."
            )
            st.dataframe(diagnostics_df, use_container_width=True)
            st.download_button(
                "⬇️ Download Monte Carlo run diagnostics (CSV)",
                data=diagnostics_df.to_csv(index=False),
                file_name="monte_carlo_run_diagnostics.csv",
                mime="text/csv",
                key="download_mc_diagnostics",
                help=(
                    "Includes the outcome, failure age and the sampled "
                    "pension, inflation, asset-return and spending-shock "
                    "statistics for every run."
                ),
            )
            failed_rates_df = pd.DataFrame(
                mc.get("failed_run_rate_rows", [])
            )
            if failed_rates_df.empty:
                st.caption("No failed paths, so there are no failure-specific annual rates to download.")
            else:
                st.download_button(
                    "⬇️ Download exact annual rates for failed runs (CSV)",
                    data=failed_rates_df.to_csv(index=False),
                    file_name="monte_carlo_failed_run_annual_rates.csv",
                    mime="text/csv",
                    key="download_mc_failed_rates",
                    help=(
                        "Includes the exact annual inflation, spending shock "
                        "and asset-return rates used by each failed path, "
                        "plus its sampled pension and wage rates."
                    ),
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
    # All-paths chart — many faint lines show the distribution directly.
    # Rendered inline rather than inside a collapsed `st.expander`:
    # Vega-Lite measures its container width when it mounts, and a chart
    # mounted inside a hidden/collapsed container resolves a degenerate
    # width, leaving the marks and axes blank. A deterministic subsample
    # keeps 1,000–5,000 paths from overwhelming the browser.
    # -------------------------
    st.subheader("🕸️ All simulated paths")

    path_matrix = np.asarray(mc["all_paths"], dtype=float)
    total_paths, path_years = path_matrix.shape

    # The percentile fan chart already carries the statistical summary, so
    # this view only needs enough faint lines to reveal the spread. Evenly
    # spaced sampling preserves the fan shape without plotting thousands of
    # overlapping lines (visually dense and heavy for the browser).
    max_display_paths = 500
    if total_paths > max_display_paths:
        keep_indices = np.unique(
            np.linspace(0, total_paths - 1, max_display_paths, dtype=int)
        )
        path_matrix = path_matrix[keep_indices]
    else:
        keep_indices = np.arange(total_paths)
    displayed_paths = path_matrix.shape[0]

    all_paths_df = pd.DataFrame({
        "Run": np.repeat(np.arange(1, displayed_paths + 1), path_years),
        "Age": np.tile(
            [y + p1_current_age for y in range(path_years)],
            displayed_paths,
        ),
        "Net Worth": path_matrix.reshape(-1),
    })
    if not diagnostics_df.empty:
        outcome_by_run = diagnostics_df["Outcome"].tolist()
        all_paths_df["Outcome"] = np.repeat(
            [outcome_by_run[i] for i in keep_indices],
            path_years,
        )
    else:
        all_paths_df["Outcome"] = np.repeat(
            ["Unknown"] * displayed_paths,
            path_years,
        )

    # Robust viewport: fit the scale to the spread of the paths actually
    # being drawn. Use the 5th–95th percentile band of the (subsampled)
    # displayed paths, taking the widest extent across the whole horizon,
    # so the fan of lines fills the chart while genuine single-path
    # outliers (one lucky/unlucky run) are still clipped rather than
    # flattening the central distribution into a thin strip. A small
    # padding keeps the extreme lines off the plot edges.
    if np.isfinite(path_matrix).all():
        lower_bound = float(np.percentile(path_matrix, 5, axis=0).min())
        upper_bound = float(np.percentile(path_matrix, 95, axis=0).max())
        if lower_bound == upper_bound:
            lower_bound, upper_bound = lower_bound - 1.0, upper_bound + 1.0
        padding = (upper_bound - lower_bound) * 0.02
        axis_domain = [
            lower_bound - padding,
            upper_bound + padding,
        ]
    else:
        # A non-finite value (e.g. a NaN leaked into one simulated path)
        # would otherwise propagate into the scale domain and render a
        # completely blank chart — no axes, no lines. Fall back to the
        # observed finite path range so the chart always has a valid scale.
        finite = path_matrix[np.isfinite(path_matrix).all(axis=1)]
        if finite.size:
            lo, hi = float(finite.min()), float(finite.max())
            if lo == hi:
                lo, hi = lo - 1.0, hi + 1.0
        else:
            lo, hi = -1.0, 1.0
        axis_domain = [lo, hi]

    # Drop any non-finite rows before charting. Vega-Lite silently skips
    # individual NaN points, but a non-finite value in a scale input (or a
    # fully empty dataset) renders a blank chart; filtering keeps the fan
    # of lines intact while guaranteeing the scale always has valid data.
    if not np.isfinite(all_paths_df["Net Worth"]).all():
        all_paths_df = all_paths_df[np.isfinite(all_paths_df["Net Worth"])]

    if all_paths_df.empty:
        st.warning(
            "No finite simulated paths to display — the plan produced "
            "non-numeric values in every simulation run."
        )
    else:
        all_paths_chart = (
            alt.Chart(all_paths_df)
            .mark_line(opacity=0.08, strokeWidth=0.6)
            .encode(
                x=alt.X("Age:Q", title="Age"),
                y=alt.Y(
                    "Net Worth:Q",
                    title="Net worth (£)",
                    scale=alt.Scale(
                        domain=axis_domain,
                        # Default `nice` tick steps give readable round
                        # values (0, 100k, 200k, …) instead of only the
                        # two domain endpoints.
                    ),
                    axis=alt.Axis(format=",.0f"),
                ),
                detail=alt.Detail("Run:N"),
                color=alt.Color(
                    "Outcome:N",
                    scale=alt.Scale(
                        domain=["Succeeded", "Failed", "Unknown"],
                        range=["#2a6f6f", "#c0392b", "#8a8a8a"],
                    ),
                    title="Outcome",
                ),
                tooltip=[
                    alt.Tooltip("Run:N", title="Run"),
                    alt.Tooltip("Age:Q", title="Age", format=".1f"),
                    alt.Tooltip("Net Worth:Q", title="Net worth", format=",.0f"),
                    "Outcome:N",
                ],
            )
            # Explicit `fit-x` autosize: Streamlit's default `fit` autosize
            # (injected when the spec has none) can squash the plot into a
            # thin band at the bottom of the chart area, hiding all but the
            # two domain-endpoint ticks. `fit-x` keeps the container width
            # while letting the plot fill the full 460px height.
            .properties(height=460, autosize=alt.AutoSizeParams(type="fit-x"))
        )
        st.altair_chart(all_paths_chart, use_container_width=True)
    if displayed_paths < total_paths:
        st.caption(
            f"Showing an evenly-spaced sample of {displayed_paths:,} of "
            f"{total_paths:,} simulated paths as thin, translucent lines. "
            "The vertical scale spans the 5th–95th percentile range of the "
            "shown paths so the fan is easy to read; extreme single-path "
            "outliers are clipped from this view. Red paths failed under "
            "the model’s current year-end net-worth definition."
        )
    else:
        st.caption(
            f"Showing all {total_paths:,} simulated paths as thin, "
            "translucent lines. The vertical scale spans the 5th–95th "
            "percentile range of the shown paths so the fan is easy to "
            "read; extreme single-path outliers are clipped from this view. "
            "Red paths failed under the model’s current year-end net-worth "
            "definition."
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
