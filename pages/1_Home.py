import streamlit as st
from brand_chrome import apply_chrome

import pandas as pd
import altair as alt
import plotly.graph_objects as go

# Altair theme is GLOBAL state on the `alt` module — `enable()`
# mutates the module's default-theme registry, so it's set on every
# render (light mode is now permanent, so `default` is the only
# theme; the prior dark/light conditional was dropped with the
# Theme radio).
alt.themes.enable("default")

from simulation.engine import run_simulation
from simulation.charts import (
    net_worth_chart,
    net_worth_composition_chart,
    pension_breakdown_chart,
    income_vs_spending_chart,
    to_int_pounds,
)
from simulation.years_and_months import (
    attach_age_columns,
    format_age_label,
    get_p1_current_age,
)
from storage import (
    init_household,
    has_saved_plan,
    plan_to_json,
    plan_from_json,
)
from pages_helpers.view_badge import render_view_mode_badge
from pages_helpers.household_builder import build_household_from_session_state
from pages_helpers.today_value_toggle import render_today_value_toggle
from pages_helpers.global_controls import render_global_controls_sidebar

render_global_controls_sidebar()

st.title("🏠 Home — Overview Dashboard")

st.write("This page shows your retirement simulation results based on the data entered on the other pages.")

# Render brand chrome (stylesheet injection — LIGHT palette only,
# since the dark-mode radio was dropped). Same call as `main.py`
# and the other 12 pages — see `brand_chrome.py` for the rationale.
apply_chrome()

# Seed the in-memory plan on first script run (no disk read).
init_household(st.session_state)


def _load_uploaded_plan():
    """One-shot handler for the plan file_uploader.

    Fires only when a NEW file is uploaded (Streamlit calls `on_change`
    on value change, not on every rerun), so it can safely overwrite
    `session_state.household_data` without clobbering later edits on
    unrelated reruns. Errors are stashed in session_state for the page
    body to render once.
    """
    uploaded = st.session_state.get("plan_uploader")
    if uploaded is None:
        return
    try:
        raw = uploaded.getvalue().decode("utf-8")
        st.session_state.household_data = plan_from_json(raw)
        st.session_state.simulation_results = None
        st.session_state["_plan_upload_error"] = None
        st.session_state["_plan_uploaded"] = True
    except (ValueError, UnicodeDecodeError) as exc:
        st.session_state["_plan_upload_error"] = str(exc)
        st.session_state["_plan_uploaded"] = False


# -------------------------
# Persistence toolbar — in-memory only, with JSON export/import so
# the user can keep their own copy (no local files on the host).
# -------------------------
col_status, col_download, col_upload, col_reset = st.columns([2, 1, 1, 1])

with col_status:
    if has_saved_plan(st.session_state):
        st.caption(
            "💾 Plan is held in this browser session (in-memory). "
            "Download it to keep a personal copy."
        )
    else:
        st.caption("ℹ️ No plan yet — enter your details, then download to keep a copy.")

with col_download:
    st.download_button(
        "⬇️ Download plan",
        data=plan_to_json(st.session_state.get("household_data", {})),
        file_name="couples_retirement_plan.json",
        mime="application/json",
        key="download_plan",
        help="Save your plan as a JSON file you can re-upload later.",
    )

with col_upload:
    st.file_uploader(
        "Upload plan",
        type=["json"],
        key="plan_uploader",
        on_change=_load_uploaded_plan,
        label_visibility="collapsed",
        help="Restore a plan from a previously downloaded JSON file.",
    )
    if st.session_state.get("_plan_upload_error"):
        st.error(f"Couldn't load plan: {st.session_state['_plan_upload_error']}")
        st.session_state.pop("_plan_upload_error", None)
    if st.session_state.get("_plan_uploaded"):
        st.success("Plan loaded.")
        st.session_state.pop("_plan_uploaded", None)

with col_reset:
    if st.button("🗑️ Reset Plan", key="reset_plan"):
        st.session_state.household_data = {}
        st.session_state.simulation_results = None
        st.warning("Plan cleared from this browser session.")

# -------------------------
# Validate required data
# -------------------------
data = st.session_state.household_data

required_keys = ["person1", "person2", "assets", "spending"]
missing = [k for k in required_keys if k not in data]

if missing:
    st.warning(f"Please enter your pension, assets, spending and events first (missing: {', '.join(missing)}).")
    st.stop()

# -------------------------
# "SHOW IN TODAY'S VALUE" TOGGLE
# -------------------------
# Delegated to the shared `pages_helpers/today_value_toggle` helper —
# same widget instance that Timeline, Scenarios, and What-If use.
# Migrated from an inline copy (pre-audit) so the toggle's label,
# help text, disabled logic, and persistence contract are identical
# across all four engine-driving pages.
# -------------------------
def _rebuild_results_after_toggle_flip() -> None:
    """Rebuild `simulation_results` inline so charts re-render in
    today's-money terms on the very next rerender."""
    household = build_household_from_session_state()
    st.session_state.simulation_results = run_simulation(household)

_today_value_disabled = not all(
    k in data for k in ("person1", "person2", "assets", "spending")
)
render_today_value_toggle(
    key_suffix="home",
    disabled=_today_value_disabled,
    on_change_rebuild_results=_rebuild_results_after_toggle_flip,
)

# -------------------------
# RUN SIMULATION BUTTON
# -------------------------
if st.button("Run Simulation"):
    # --- Build Household object (delegated to the shared helper) ---
    household = build_household_from_session_state()

    # --- Run Simulation ---
    # Note: the engine mutates `household` in place (`asset.grow()`,
    # `person.dc_pot += ...`) but NOT `st.session_state.household_data`,
    # because Person/Asset objects are constructed fresh from the dict above.
    # We deliberately do NOT save after the run — persisting here would be
    # a footgun if anyone ever reuses the session_state-backed models.
    results = run_simulation(household)
    st.session_state.simulation_results = results

    st.success("Simulation complete!")

# -------------------------
# DISPLAY RESULTS
# -------------------------
if "simulation_results" in st.session_state and st.session_state.simulation_results:
    results = st.session_state.simulation_results

    # View-mode badge — "INFLATION STRIPPED" appears at the very
    # top of the results block when the user has flipped the
    # today's-value toggle on the same page. Helper renders nothing
    # in nominal mode so the legacy default looks byte-identical.
    # The badge text intentionally reiterates the four key
    # invariants (mortgage kept, property zeroed, DB / SP flat,
    # DC / asset growth real rates) so a user who skipped the
    # Home-page toggle's help text still knows what changed.
    render_view_mode_badge(results)

    # ---------------------------------------------------------
    # Dashboard metric cards — key headline figures in a compact
    # 4-column row. Uses `st.metric()` for the native Streamlit
    # card look (bold value + delta arrow + muted label). The four
    # figures mirror what most UK retirement tools surface above
    # the fold: net worth today, peak net worth, years until the
    # FIRST partner retires, and a sustainability pass/fail.
    # `to_int_pounds` rounds to whole £ so the metric cards render
    # "£250,000" not "£250,000.00"; years-to-retirement stays as
    # a float to preserve months precision from the Pensions page.
    # ---------------------------------------------------------
    _final_nw = results["net_worth"][-1]
    _peak_nw = max(results["net_worth"])
    _p1_block = data.get("person1", {})
    _p2_block = data.get("person2", {})
    _p1_age_f = float(_p1_block.get("age", 55.0))
    _p1_ret_f = float(_p1_block.get("retirement_age", _p1_age_f))
    _p2_age_f = float(_p2_block.get("age", 55.0))
    _p2_ret_f = float(_p2_block.get("retirement_age", _p2_age_f))
    _years_to_ret = max(
        0.0,
        min(_p1_ret_f - _p1_age_f, _p2_ret_f - _p2_age_f),
    )

    col_nw, col_peak, col_years, col_sus = st.columns(4)
    with col_nw:
        st.metric(
            "Net worth (end of plan)",
            f"£{_final_nw:,.0f}",
            delta=None,
        )
    with col_peak:
        st.metric(
            "Peak net worth",
            f"£{_peak_nw:,.0f}",
            delta=None,
        )
    with col_years:
        st.metric(
            "First partner retires in",
            f"{_years_to_ret:g} yrs" if _years_to_ret > 0 else "Already retired",
            delta=None,
        )
    with col_sus:
        if results["net_worth"][-1] >= 0:
            st.metric(
                "Sustainability",
                "✅ Sustainable",
                delta=None,
            )
        else:
            st.metric(
                "Sustainability",
                "⚠️ Runs out",
                delta=None,
            )

    # ---------------------------------------------------------
    # Headline banner — pre-retirement phantom-cash uplift fix.
    # ---------------------------------------------------------
    # Without `cash_buffer=True` the engine's step 4 amortises the
    # mortgage every pre-retirement year without tracking the cash
    # that paid it — so the Asset Composition chart just below
    # can show household wealth rising during the working years
    # even when wages + investment growth are insufficient to cover
    # spending + mortgage. The effect is real but small and is
    # the most common cause of the question "Why was my net worth
    # going up while I was still working?" — surfacing the headline
    # fix here means the user sees the explanation right next to
    # the chart that shows the artifact. Gated on three concurrent
    # conditions:
    #
    #   1. `cash_buffer` is False (either explicit or via the
    #      dataclass default for legacy saved plans that pre-date
    #      the field). Skip when True — the user has already opted
    #      in, no nag.
    #   2. The household has an active mortgage (`outstanding > 0`).
    #      Skip when no mortgage — phantom uplift cannot manifest
    #      without a step-4 amortisation, so the banner would be
    #      noise for mortgage-free households.
    #   3. At least one partner still has years before
    #      `retirement_age`. Skip when both partners are already
    #      retired (or at retirement) — the flag's effect is
    #      locked to pre-retirement years only.
    #
    # Subject to all three gates, the banner uses `st.info(...)`
    # (neutral advisory tone — not a warning) and points at the
    # Assets page checkbox (Page 3) where the flag is opt-in.
    # ---------------------------------------------------------
    _p1_block = data.get("person1", {})
    _p2_block = data.get("person2", {})
    _p1_age = float(_p1_block.get("age", 55.0))
    _p1_ret = float(_p1_block.get("retirement_age", _p1_age))
    _p2_age = float(_p2_block.get("age", 55.0))
    _p2_ret = float(_p2_block.get("retirement_age", _p2_age))
    _mortgage_block = data.get("mortgage", {})
    _has_mortgage = float(_mortgage_block.get("outstanding", 0)) > 0
    _cash_buffer_enabled = bool(data.get("cash_buffer", False))
    _either_pre_retirement = (_p1_age < _p1_ret) or (_p2_age < _p2_ret)

    if (
        not _cash_buffer_enabled
        and _has_mortgage
        and _either_pre_retirement
    ):
        st.info(
            "ℹ️ **Heads up: net worth rose while you were still "
            "working — that's a phantom-uplift effect.**\n\n"
            "Without **cash buffer** mode, the engine's mortgage "
            "step reduces the loan balance each year without "
            "tracking the cash that paid it. The chart below "
            "shows your `Asset Composition` rising during the "
            "working years as if the mortgage paid itself — "
            "bookkeeping, not real cash inflow.\n\n"
            "👉 **Fix:** turn on `For mortgage shortfalls, dip "
            "into Cash / ISA / GIA` on the **Assets** page "
            "(Page 3). The engine will then drain your savings "
            "to cover pre-retirement deficits so the chart "
            "reflects actual cash flow, not ledger drift."
        )

    # Home-page x-axis is AGE from current age (Person 1's age) rather than a
    # raw year count from 0 upwards. Other pages still use `Year`. We pull the
    # current age from session_state (not from results) so the chart stays in
    # sync with the value shown on the Pensions page even before a re-run.
    # Centralised helper — replaces the previous bare `float(...)` access that
    # was vulnerable to malformed-JSON / Reset-Plan edge cases. The earlier
    # `required_keys` guard above makes the dict access safer than on pages
    # 10/11/12/13 but `get_p1_current_age` adds a 55.0 fallback if a future
    # refactor relaxes the guard.
    p1_current_age = get_p1_current_age(data)

    # Centralised age-label pipeline (consolidated from the prior
    # inline `_attach_age_column` helper on this page and the
    # `_add_age_column` helper on `pages/11_Timeline.py`). Both
    # columns (`Age` float + `AgeLabel` string) are produced in a
    # single call — `st.line_chart` consumers only read `Age`,
    # Altair consumers read `AgeLabel` for the x-axis tick text.

    # Compute the end-of-simulation age once and reuse across the 5
    # subheaders below. `format_age_label` returns compact "Xy Ym"
    # labels (e.g. "55y" / "55y 10m") — replaces the legacy `:g`
    # formatter that produced noise like "Age 55.8333 → 99.8333" on
    # Page 2's months-precision fractional-age plans.
    last_age = p1_current_age + len(results["years"]) - 1
    age_range = f"Age {format_age_label(p1_current_age)} → {format_age_label(last_age)}"

    # ---------------------------------------------------------
    # Asset-class composition over time (replaces the previous
    # stacked-area chart with stacked vertical bars). The engine
    # already exposes per-class series (ISA / GIA / Cash / Property /
    # DC Pension) so we just melt them into an Altair stacked-bar
    # chart. The peak-gross-wealth total across the horizon pins the
    # y-axis at `peak_total * 1.01` so bar heights are visually
    # 1-for-1 comparable across ages (same convention as
    # pages/12_Asset_Allocation.py). Bar size is fixed at 18px so
    # ~30 yearly bars fit side-by-side on standard Streamlit widths
    # without merging.
    # ---------------------------------------------------------
    st.subheader(f"🥧 Asset Composition Over Time ({age_range})")
    composition_df = attach_age_columns(
        net_worth_composition_chart(results), p1_current_age
    )
    ASSET_CLASS_COLUMNS = ["ISA", "GIA", "Cash", "Property", "DC Pension"]
    composition_melt = composition_df.melt(
        id_vars=["Age", "AgeLabel"],
        value_vars=ASSET_CLASS_COLUMNS,
        var_name="Asset Class",
        value_name="Value",
    )
    peak_total = composition_melt.groupby("Age")["Value"].sum().max()
    y_axis_max = max(peak_total * 1.01, 1.0)
    composition_chart = (
        alt.Chart(composition_melt)
        .mark_bar(size=18)
        .encode(
            # `AgeLabel:O` (string) renders compact "Xy Ym" tick text
            # ("55y", "55y 10m", …); `Age:O` (float) would render
            # decimal expansion like "55", "55.8333", "56", ….
            x=alt.X("AgeLabel:O", title="Age", sort="ascending"),
            y=alt.Y(
                "Value:Q",
                stack="zero",
                title="£ (gross wealth)",
                scale=alt.Scale(domain=[0, y_axis_max], nice=False),
                axis=alt.Axis(format=",.0f"),
            ),
            color=alt.Color(
                "Asset Class:N",
                # Explicit sort drives legend order AND the `color_N_order`
                # basis the Order encoding uses, so the visual stack
                # follows the same ISA → GIA → Cash → Property → DC Pension
                # order quoted in the caption below. Without this, Altair
                # would alphabetically stack them (Cash at bottom through
                # Property at top) — a discrepancy that's only mildly
                # visible on stacked areas but jumps out on bars because
                # each segment is a discrete band.
                sort=ASSET_CLASS_COLUMNS,
                scale=alt.Scale(scheme="category10"),
                title="Asset class",
                legend=alt.Legend(orient="right"),
            ),
            order=alt.Order("color_N_order:Q", sort="ascending"),
            tooltip=[
                alt.Tooltip("Age:O", title="Age"),
                "Asset Class:N",
                alt.Tooltip("Value:Q", title="£", format=",.0f"),
            ],
        )
        .properties(height=440)
    )
    st.altair_chart(composition_chart, use_container_width=True)
    st.caption(
        "Stacked vertical bars — one bar per year, split into "
        "ISA / GIA / Cash / Property / DC Pension. Total bar height "
        "= gross household wealth at that age. Mortgage is DEBT (not "
        "an asset), so it is charted separately below — "
        "`Gross assets − Mortgage balance = True net worth`."
    )

    # ---------------------------------------------------------
    # Plotly mini-version — a complementary interactive view of
    # the same asset trajectory. Same DataFrame (`composition_df`)
    # as the Altair stacked-bar above, rendered via `st.plotly_chart`
    # so we get hover-for-exact-£, click-to-toggle legend items,
    # toolbar zoom / pan / range-select, and double-click-to-reset
    # for free. Bar style is **grouped** (one per asset class,
    # side-by-side) rather than the stacked position used above —
    # this gives a different visual angle and lets the viewer
    # read each asset's £-value at any age without summing them
    # mentally. Plotly's default `category10` palette is what
    # Altair's `scheme="category10"` maps to, so ISA / GIA / Cash /
    # Property / DC Pension carry the SAME colours across both charts.
    # Color palette is left to Plotly defaults so the two pages
    # remain visually in lockstep without explicit color literals.
    # ---------------------------------------------------------
    st.subheader(f"📊 Asset Trajectory — Plotly Mini ({age_range})")
    plotly_grouped_fig = go.Figure()
    for _asset_col in ASSET_CLASS_COLUMNS:
        plotly_grouped_fig.add_trace(
            go.Bar(
                # Bind to `AgeLabel` strings (same x-axis treatment as
                # the Altair stacked-bar above) so the Plotly mini shows
                # "55y", "55y 10m", … rather than integer-rounding `Age`
                # floats that drift off-by-half-year from the Altair
                # chart's fractional ages. Until this consolidation, the
                # Plotly mini crawled with `int(round(age))` so a
                # 55.8333 current_age slid to "56" while the Altair
                # chart above showed "55y 10m" — visually inconsistent.
                x=list(composition_df["AgeLabel"]),
                y=composition_df[_asset_col],
                name=_asset_col,
                # Unified hovertemplate: bold asset name on top,
                # age + £ value below. The `<extra></extra>` empty
                # tag suppresses Plotly's default trace-name box
                # so the hover reads as a single tidy tooltip rather
                # than as a name-tag + value-tag double box.
                hovertemplate=(
                    f"<b>{_asset_col}</b><br>"
                    "Age %{x}<br>"
                    "£%{y:,.0f}<extra></extra>"
                ),
            )
        )
    plotly_grouped_fig.update_layout(
        barmode="group",
        # Plotly's template is per-Figure (not a global like Altair's),
        # so we resolve it directly on the figure. `plotly_white` is
        # the LIGHT-theme look — light mode is now permanent, so the
        # prior `plotly_dark` fallback was dropped with the Theme radio.
        template="plotly_white",
        title={
            "text": "Asset Trajectory (grouped bars · interactive)",
            "x": 0.02,
            "xanchor": "left",
        },
        xaxis_title="Age",
        yaxis_title="£ (gross wealth)",
        legend_title="Asset class",
        height=420,
        # `x unified` shows one hover box across all of the asset
        # bars at the hovered age — easier to compare ISA vs GIA
        # vs Cash etc. at a single year than the per-trace default.
        hovermode="x unified",
        margin=dict(l=0, r=0, t=50, b=0),
        # Match the Altair composition block's `axis=alt.Axis(format=",.0f")`
        # so the two y-axes read consistently — full £ values with
        # thousand-separators ("200,000" / "1,000,000") rather than
        # Plotly's default compact SI notation ("200k" / "1M"). Without
        # this, the Plotly axis quietly shows the Si abbreviation while
        # the Altair axis (right above) shows the full pounds — looks
        # inconsistent at-a-glance.
        yaxis_tickformat=",.0f",
    )
    st.plotly_chart(plotly_grouped_fig, use_container_width=True)
    st.caption(
        "Plotly mini-version of the asset trajectory. Hover any bar "
        "for exact £ at that age; click any legend item to show / "
        "hide; toolbar supports zoom / pan / box-select; "
        "double-click an axis to reset."
    )

    # Mortgage balance trend on its own scale so the stacked-area
    # chart above is allowed to be purely positive (zero to peak_gross)
    # without the dashed line dipping below the x-axis. After repayment
    # the line just renders flat at £0.
    st.subheader(f"🏠 Mortgage Balance Over Time ({age_range})")
    mortgage_df = pd.DataFrame({
        "Year": results["years"],
        "Mortgage Balance": to_int_pounds(
            results.get("mortgage_balance", [0.0] * len(results["years"]))
        ),
    })
    st.line_chart(attach_age_columns(mortgage_df, p1_current_age), x="Age", y="Mortgage Balance")
    st.caption("Outstanding mortgage balance at each year-end. Drops to £0 when the mortgage is fully repaid.")

    # Honour the "Include mortgage payment in spending figure" toggle
    # from the Assets page. When True the engine's `total_need` treats
    # the spending figure as total outgoings (mortgage included) and
    # this chart shows one combined Spending line at that figure. When
    # False the engine funds spending + mortgage on top and the
    # three-line view (Income / Spending / Mortgage Payment) is
    # preserved. Flipping the toggle DOES re-run the simulation — the
    # income bars move to match the new target.
    include_mortgage_in_spending = (
        st.session_state.household_data
        .get("mortgage", {})
        .get("include_in_spending", False)
    )
    st.subheader("💰 Income, Spending & Mortgage Payment")
    st.line_chart(
        attach_age_columns(
            income_vs_spending_chart(results, include_mortgage_in_spending),
            p1_current_age,
        ),
        x="Age",
        y=(
            ["Income", "Spending"]
            if include_mortgage_in_spending
            else ["Income", "Spending", "Mortgage Payment"]
        ),
    )
    if include_mortgage_in_spending:
        st.caption(
            "Spending is lifestyle + mortgage combined (toggle from "
            "the Assets page is ON)."
        )
    else:
        st.caption(
            "Spending is lifestyle only; mortgage payment is shown as "
            "its own line. Toggle 'Include mortgage payment in "
            "displayed spending' on the Assets page to combine them."
        )

    # ---------------------------------------------------------
    # Indexed Pension Income — split into DB Pension vs State Pension
    # so the user can see WHICH pension source each £ comes from
    # (the previous single-line "Indexed Pension Over Time" sub-chart
    # was confusing — it summed DB + State Pension into one line,
    # so viewers mistook the combined total for the State Pension
    # alone). The two series are pre-tax, pre-NI. `db_payout` and
    # `state_payout` may be absent in older saved payloads — the
    # `pension_breakdown_chart` helper falls back to all-zeros
    # rather than crashing on KeyError, so legacy sessions still
    # render cleanly (with the missing series flat at £0).
    # ---------------------------------------------------------
    st.subheader(f"💷 Indexed Pension Income — DB + State Pension ({age_range})")
    st.caption(
        "Pre-tax income the household receives from each pension source. "
        "DB Pension activates at draw_age and indexes by db_growth_rate. "
        "State Pension activates at state_pension_age and indexes by "
        "state_pension_growth_rate. Both are pre-tax and pre-NI."
    )
    st.line_chart(
        attach_age_columns(pension_breakdown_chart(results), p1_current_age),
        x="Age",
        y=["DB Pension", "State Pension"],
    )

    # Sustainability warning
    if results["net_worth"][-1] < 0:
        st.error("⚠️ Warning: Your plan is not sustainable. Assets run out before the end of the simulation.")
    else:
        st.success("✅ Your plan appears sustainable within the simulation horizon.")
