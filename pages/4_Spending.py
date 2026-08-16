"""`pages/4_Spending.py` — Spending & Drawdown page (detail-only).

The annual **spending target** and the plan-end age are entered on
the **Quick Estimate** page (`pages/0_Quick_Estimate.py`), which is
the single basis for the calculation. This page holds ONLY the
drawdown detail: the spending strategy, the tapered-spending
parameters, the drawdown wrapper priority, the pre-retirement
cash-flow deficit signal, and the maximum-sustainable-spending
solver.
"""
import streamlit as st
from brand_chrome import apply_chrome

from storage import init_household, save_household
from simulation.deficit_signal import compute_pre_retirement_deficit_signal
from simulation.years_and_months import format_age_label, years_and_months_input
from pages_helpers.global_controls import render_global_controls_sidebar
from pages_helpers.household_builder import build_household_from_session_state
from pages_helpers.strategy_options import (
    DRAW_DOWN_STRATEGIES,
    normalize_drawdown_strategy,
)

# Render brand chrome (stylesheet injection — LIGHT palette only).
apply_chrome()
render_global_controls_sidebar()

st.title("💷 Spending & Drawdown")

# ----------------------------------------
# 1. Initialise session_state — seed from disk on first visit
# ----------------------------------------
init_household(st.session_state)

# Convenience handle to the seeded saved-household dict — also
# surfaced in the form pre-fill defaults below.
data = st.session_state.household_data

# The spending target itself lives on the Quick Estimate page — this
# page only shows it (read-only) so the drawdown analysis below is
# comprehensible.
saved_spending = float(data.get("spending", 0.0))
saved_strategy = normalize_drawdown_strategy(
    data.get("drawdown_strategy", "Fixed")
)

st.caption(
    f"**Annual spending target: £{saved_spending:,.0f}/yr** — set on "
    "the **Quick Estimate** page. This page controls the **drawdown "
    "strategy** and how your income sources are pulled."
)

# ----------------------------------------
# 2. Inputs (pre-filled with saved values)
# ----------------------------------------
STRATEGIES = list(DRAW_DOWN_STRATEGIES)
strategy = st.selectbox(
    "Drawdown strategy",
    STRATEGIES,
    index=STRATEGIES.index(saved_strategy)
    if saved_strategy in STRATEGIES
    else 0,
)

# ----------------------------------------
# 2b. Tapered-strategy params — only rendered when the user picks
# "Tapered (down with age)". Streamlit re-runs top-to-bottom on
# every widget interaction so this conditional re-evaluates on the
# same rerun as the strategy dropdown, no `st.rerun()` needed.
# Defaults (75 / 0.02 / £10,000) mirror the `Household` dataclass
# defaults. Persisted under three top-level JSON keys
# (`taper_start_age`, `taper_rate`, `taper_floor_gbp`) so the
# engine's `getattr(household, ..., default)` defensive reads
# survive Plan imports / exports.
# ----------------------------------------
if strategy == "Tapered (down with age)":
    st.caption(
        "**Tapered (down with age)** — two-phase trajectory anchored "
        "on Person 1's `retirement_age` and `taper_start_age`:\n\n"
        "* **Pre-retirement (working years):** straight inflation-"
        "adjusted base. The go-go bump and the late-life taper do "
        "NOT apply to working years. (Engine contract; test-locked in "
        "`tests/test_tapered_spending.py`.)\n"
        "* **Phase 1 (Go-Go, optional):** with `gogo_bump_pct` > 0, "
        "spending ramps UP by `gogo_bump_pct`/yr every year from "
        "retirement until reaching the peak at `taper_start_age`. "
        "Default 0% means no ramp — spending stays at the "
        "inflation-adjusted base through Phase 1.\n"
        "* **Phase 2 (Slow-Go / No-Go):** after `taper_start_age`, "
        "spending ramps DOWN by `taper_rate`/yr (real terms). "
        "`taper_floor_gbp` caps the asymptotic approach to zero in "
        "extreme old age.\n"
        "* **Optional later-life steps:** apply a further one-off "
        "percentage reduction at each of two ages (for example, 75 "
        "and 85). The reductions are multiplicative and the floor is "
        "still applied last.\n\n"
        "Defaults: gogo=0%, peak age 75, decline 2%/yr, £10k floor "
        "and no extra step-downs. Note: all phases and age steps "
        "fire against Person 1's age only."
    )
    gogo_bump_pct = st.slider(
        "Go-Go spending bump (% / yr, between retirement and peak)",
        0.0,
        10.0,
        float(data.get("gogo_bump_pct", 0.0)),
        step=0.5,
        key="gogo_bump_pct",
        help=(
            "Real-terms percentage INCREASE applied to the inflation-"
            "adjusted base every year BETWEEN retirement_age and "
            "taper_start_age (the peak). Default 0% reproduces the "
            "no-bump Tapered curve."
        ),
    )
    taper_start_age = years_and_months_input(
        label_years="Peak / Taper start age (Person 1)",
        label_months="Months",
        default_years_float=float(data.get("taper_start_age", 75.0)),
        key_prefix="taper_start_age",
        min_years=50,
        max_years=90,
        help_months=(
            "Reference age (Person 1 scale) at which spending "
            "PEAKS (when gogo_bump_pct > 0) and the taper BEGINS. "
            "After this age, the inflation-adjusted base is "
            "compounded by (1 - rate) every simulated year."
        ),
    )
    taper_rate = st.slider(
        "Real decline rate after peak (% / yr)",
        0.0,
        10.0,
        float(data.get("taper_rate", 0.02)) * 100.0,
        step=0.1,
        key="taper_rate_pct",
        help=(
            "Annual real-terms decline applied AFTER taper_start_age. "
            "2%/yr reflects typical late-life lifestyle reduction."
        ),
    ) / 100.0
    taper_floor_gbp = st.number_input(
        "Spending floor (£ / yr, applied AFTER taper)",
        0,
        100_000,
        int(data.get("taper_floor_gbp", 10_000)),
        step=500,
        key="taper_floor_gbp",
        help=(
            "Hard minimum for the taper's asymptotic decline. "
            "£10,000 approximates State Pension level. Set to 0 to "
            "allow the taper to crush spending to zero in extreme "
            "old age."
        ),
    )

    st.markdown("**Optional later-life spending reductions**")
    st.caption(
        "Add a one-off reduction at two later ages. Set either rate to "
        "0% to leave that step disabled. The reduction applies in the "
        "year Person 1 reaches the selected age; both reductions are "
        "applied on top of the gradual taper."
    )
    step_1_age = years_and_months_input(
        label_years="First reduction age (Person 1)",
        label_months="Months",
        default_years_float=float(
            data.get("late_life_step_1_age", 75.0)
        ),
        key_prefix="late_life_step_1_age",
        min_years=50,
        max_years=110,
        help_months=(
            "Age at which the first additional spending reduction "
            "starts."
        ),
    )
    step_1_rate = st.slider(
        "First reduction (% of current spend)",
        0.0,
        50.0,
        float(data.get("late_life_step_1_rate", 0.0)) * 100.0,
        step=1.0,
        key="late_life_step_1_rate_pct",
        help=(
            "One-off reduction applied when Person 1 reaches the first "
            "reduction age. 10% means spending is multiplied by 90%."
        ),
    ) / 100.0
    step_2_age = years_and_months_input(
        label_years="Second reduction age (Person 1)",
        label_months="Months",
        default_years_float=float(
            data.get("late_life_step_2_age", 85.0)
        ),
        key_prefix="late_life_step_2_age",
        min_years=50,
        max_years=110,
        help_months=(
            "Age at which the second additional spending reduction "
            "starts. It is applied after the first reduction when "
            "the ages are different."
        ),
    )
    step_2_rate = st.slider(
        "Second reduction (% of current spend)",
        0.0,
        50.0,
        float(data.get("late_life_step_2_rate", 0.0)) * 100.0,
        step=1.0,
        key="late_life_step_2_rate_pct",
        help=(
            "One-off reduction applied when Person 1 reaches the second "
            "reduction age. 15% means spending is multiplied by 85%."
        ),
    ) / 100.0

# ----------------------------------------
# 2c. Drawdown wrapper priority — user-configurable ordering of
# ISA / GIA / Pension / Cash for the engine's step-7 drawdown
# waterfall. Always rendered (not strategy-gated). The "Pension"
# entry triggers the engine's PCLS/UFPLS waterfall (25%-tax-free
# UFPLS preference + per-spouse tax recompute); the other three
# route through `drain_single_asset_class` in the user's relative
# order.
# ----------------------------------------
ALL_WRAPPERS = ["Pension", "Cash", "ISA", "GIA"]
saved_priority = data.get("drawdown_priority", list(ALL_WRAPPERS))
default_priority = [w for w in saved_priority if w in ALL_WRAPPERS]
if not default_priority:
    default_priority = list(ALL_WRAPPERS)
drawdown_priority = st.multiselect(
    "Drawdown wrapper priority (first to drain → last to drain)",
    options=ALL_WRAPPERS,
    default=default_priority,
    key="drawdown_priority",
    help=(
        "Order in which the engine drains tax wrappers when the "
        "household is in cash-flow deficit. 'Pension' triggers "
        "the PCLS/UFPLS waterfall (25% tax-free, 75% taxable); "
        "the other three route through single-class drains in "
        "the user's relative order. De-selected wrappers are "
        "appended to the END in canonical order (Pension → "
        "Cash → ISA → GIA), so the engine always has somewhere "
        "to draw from if a residual shortfall remains."
    ),
)
st.caption(
    "**UK longevity tip:** most retirees benefit from "
    "**deferring pension draws** to keep the DC pot outside "
    "the IHT estate for as long as possible — list 'Pension' "
    "last (or de-select it). Conversely, drawing ISA / GIA "
    "first lets you 'fill' the **basic-rate band** before "
    "crystallising taxable pension income. Pre-retirement "
    "`cash_buffer` mode (Page 3 — Assets) ignores 'Pension' "
    "automatically because the DC pot is not drawable pre-retirement.\n\n"
    "**Reordering:** Streamlit's `st.multiselect` returns "
    "selected wrappers in `options` order, not click order — "
    "so to set a custom priority (e.g. `ISA → GIA → Pension "
    "→ Cash`), de-select all wrappers, then re-add them in "
    "your desired order."
)

# ----------------------------------------
# 3. Pre-retirement cash-flow deficit signal
# ----------------------------------------
# Pre-retirement, the engine NEVER touches retirement assets — so a
# plan where `spending + mortgage > earned_income` while still
# working leaves the Income chart line sitting below the Spending
# line with no visible explanation. This banner surfaces the gap.
# The spending figure is read from the saved data (owned by Quick
# Estimate); the strategy is overlaid from the live selectbox above
# so the banner reacts on the same rerun.
overlaid_for_signal = dict(data)
overlaid_for_signal["drawdown_strategy"] = strategy
signal = compute_pre_retirement_deficit_signal(overlaid_for_signal)

if signal is not None:
    age_label = format_age_label(signal.worst_year_age_p1)
    horizon_word = (
        "year" if signal.pre_retirement_year_count == 1 else "years"
    )
    mortgage_clause = (
        f" + your mortgage payment "
        f"(£{signal.annual_mortgage_when_active_gbp:,.0f}/yr "
        f"while the loan is active)"
        if signal.annual_mortgage_when_active_gbp > 0
        else ""
    )

    st.warning(
        f"⚠️ **Pre-retirement cash flow is in deficit**\n\n"
        f"Your annual spending (£{signal.annual_spending_gbp:,.0f})"
        f"{mortgage_clause} exceeds your projected household income "
        f"(wages + DB pension + State Pension) in the pre-retirement "
        f"horizon. Worst year: **age {age_label}** — you would be "
        f"**£{signal.worst_deficit_gbp:,.0f}/year** short that year. "
        f"Cumulative shortfall across the "
        f"{signal.pre_retirement_year_count}-{horizon_word} pre-"
        f"retirement horizon: "
        f"**£{signal.cumulative_deficit_gbp:,.0f}** (per-year "
        f"shortfalls summed).\n\n"
        f"👉 **Action:** bump **income until retirement** (or push "
        f"the retirement date later) for each partner on the "
        f"**Quick Estimate** page, or trim the **spending target** "
        f"there too. Mortgage overpayments can be reduced on the "
        f"**Assets** page (Page 3)."
    )

    # Residual-after-drain banner — surfaces the structural
    # underfunding that the cash_buffer opt-in can NOT bridge.
    if signal.cash_buffer_at_signal and signal.worst_residual_gbp > 0:
        residual_age_label = format_age_label(signal.worst_residual_year_age_p1)
        drained_label = (
            f"£{signal.total_assets_drained_gbp:,.0f}"
        )
        st.error(
            f"🚨 **Residual shortfall: cash_buffer drain can't fully "
            f"cover the gap**\n\n"
            f"Even with `cash_buffer` mode on (Page 3 — Assets — "
            f"'Cash-buffer mode'), the household's liquid savings "
            f"fall short in the pre-retirement horizon. Worst year: "
            f"**age {residual_age_label}** — you'd still be "
            f"**£{signal.worst_residual_gbp:,.0f}/year** short that "
            f"year after draining **£{drained_label}** of Cash / ISA "
            f"/ GIA. Cumulative residual across the "
            f"{signal.pre_retirement_year_count}-{horizon_word} pre-"
            f"retirement horizon: "
            f"**£{signal.cumulative_residual_gbp:,.0f}**.\n\n"
            f"📉 **Action:** to close a structural gap that asset "
            f"drain alone can't fix, add income on the **Quick "
            f"Estimate** page, trim lifestyle spend there, or plan "
            f"an asset sale / downsizing (Page 5 — Life Events). "
            f"The drain will have already covered {drained_label} "
            f"of the gap; the residual is the part your savings "
            f"can't reach."
        )

# ----------------------------------------
# 4. Save Button — strategy + taper params + drawdown priority. The
# spending target is NOT saved here (it lives on Quick Estimate).
# ----------------------------------------
if st.button("Save Spending"):
    st.session_state.household_data["drawdown_strategy"] = strategy
    # Taper-strategy params — only persisted when the user has
    # actually rendered them by selecting Tapered. Stored even when
    # Tapered isn't the active strategy so a user can switch
    # strategies without re-typing the values.
    if strategy == "Tapered (down with age)":
        st.session_state.household_data["taper_start_age"] = taper_start_age
        st.session_state.household_data["taper_rate"] = taper_rate
        st.session_state.household_data["taper_floor_gbp"] = taper_floor_gbp
        st.session_state.household_data["late_life_step_1_age"] = step_1_age
        st.session_state.household_data["late_life_step_1_rate"] = step_1_rate
        st.session_state.household_data["late_life_step_2_age"] = step_2_age
        st.session_state.household_data["late_life_step_2_rate"] = step_2_rate
        st.session_state.household_data["gogo_bump_pct"] = gogo_bump_pct
    # Drawdown wrapper priority — persisted at the top level (not
    # strategy-gated) so the engine's `_resolve_priority_list`
    # helper can read it on every drawdown path.
    st.session_state.household_data["drawdown_priority"] = (
        list(drawdown_priority) if drawdown_priority else []
    )

    save_household(st.session_state.household_data)
    st.success("Spending & drawdown strategy saved!")

# ----------------------------------------
# 5. Maximum-sustainable-spending solver (one-off calculator)
# ----------------------------------------
# INVERSE problem vs the spending widget on Quick Estimate: the user
# picks a target age and we solve for the maximum spending that
# exactly hits zero net worth at that age. Solves via bisection on
#   f(spending) := run_simulation(hh_copy_with_spend=S,
#                                  years=target_year_offset+1)
#                  .net_worth[target_year_offset]
# stopping when |f(s)| <= £200. Lives in
# simulation/sustainable_spending.py so it has no Streamlit
# dependency and is unit-testable directly.
with st.expander(
    "📐 Find Maximum Sustainable Spending for a Target Age",
    expanded=False,
):
    st.caption(
        "**Solver:** find the highest annual spending (in your "
        "saved currency mode — today's-money or nominal) that "
        "exactly depletes household wealth to **£0** at the age "
        "you pick below. Respects your current drawdown strategy "
        "and drawdown wrapper priority. Use it to validate your "
        "current spending figure, or hit 'Apply' to update it."
    )
    st.caption(
        "**Strategy matters:** Fixed and Tapered strategies "
        "produce different max-spending figures for the same "
        "wealth (Fixed ≈ 10-15% higher on typical UK profiles, "
        "because the Tapered tapers the spend AFTER the peak). "
        "Re-calculate after switching strategies on the widget "
        "above to see the change."
    )

    if "sustainable_target_age" not in st.session_state:
        st.session_state["sustainable_target_age"] = float(
            data.get("life_expectancy_end_age", 95.0)
        )

    target_age = years_and_months_input(
        label_years="Target age (depletes to £0)",
        label_months="Months",
        default_years_float=float(
            st.session_state["sustainable_target_age"]
        ),
        key_prefix="sustainable_target_age",
        min_years=40,
        max_years=110,
        help_months=(
            "Reference age at which the household's net worth "
            "should reach exactly £0. Default is your saved "
            "`life_expectancy_end_age` (set on Quick Estimate)."
        ),
    )

    # Calculate button — does NOT save to disk; only stashes the
    # result in session_state.
    _calc_clicked = st.button(
        "Calculate Maximum Sustainable Spending",
        type="secondary",
        use_container_width=True,
        key="calc_sustainable",
        help=(
            "Bisects on terminal net worth — ~1 second typical "
            "(18-25 iterations). Stashes the result in this session "
            "only; click 'Apply as my annual spending' below to commit."
        ),
    )
    if _calc_clicked:
        from simulation.sustainable_spending import (
            find_max_sustainable_spending,
        )
        _hh_for_solver = build_household_from_session_state()
        with st.spinner("Solving for max-sustainable spend…"):
            _result = find_max_sustainable_spending(
                _hh_for_solver, float(target_age)
            )
        st.session_state["sustainable_last_result"] = _result
        st.session_state["sustainable_last_target_age"] = float(
            target_age
        )

    # Result panel — paint only when a fresh solve has run AND the
    # target_age in session_state still matches the widget's current
    # target_age (0.05 yr tolerance).
    _last_result = st.session_state.get("sustainable_last_result")
    _last_target = st.session_state.get(
        "sustainable_last_target_age", None
    )
    if (
        _last_result is not None
        and _last_target is not None
        and abs(float(_last_target) - float(target_age)) < 0.05
    ):
        if _last_result.error:
            st.error(f"❌ {_last_result.error}")
        else:
            _strategy_label = (
                _last_result.strategy_at_run
                or "your current strategy"
            )
            _headline_html = (
                f"<div style='font-size:2rem;font-weight:700;"
                f"line-height:1.2;color:#1f7a3d;margin-bottom:0.25em'>"
                f"£{_last_result.max_spending_gbp:,.0f}/yr</div>"
            )
            st.markdown(_headline_html, unsafe_allow_html=True)
            if _last_result.converged:
                st.success(
                    f"✅ Sustainable to **age {float(target_age):.0f}** "
                    f"— {_last_result.iterations_used} solver "
                    f"iterations, ±£200 precision, "
                    f"{_strategy_label} strategy."
                )
            else:
                st.warning(
                    f"⚠️ **£{_last_result.max_spending_gbp:,.0f}/yr** "
                    f"— best estimate after "
                    f"{_last_result.iterations_used} iterations "
                    f"(did not fully converge within "
                    f"±£200 precision; pick a closer target age "
                    f"for tighter numbers)."
                )
            st.caption(
                f"Terminal net worth at age {float(target_age):.0f} "
                f"when spending at this rate: "
                f"**£{_last_result.terminal_net_worth_gbp:,.0f}** "
                f"(target £0). Strategy in run: "
                f"`{_strategy_label}`. Simulated "
                f"{_last_result.iterations_used} times."
            )

            # Apply CTA — commits the solver's answer as the spending
            # target (the Quick Estimate page reads the same value).
            if st.button(
                "Apply as my annual spending",
                type="primary",
                use_container_width=True,
                key="apply_sustainable",
                help=(
                    "Updates the annual spending target (used "
                    "everywhere — including the Quick Estimate chart) "
                    "AND applies it across the whole session. Use the "
                    "regular Save Spending button instead if you only "
                    "want to compare values without committing."
                ),
            ):
                st.session_state.household_data["spending"] = float(
                    _last_result.max_spending_gbp
                )
                save_household(st.session_state.household_data)
                st.success(
                    f"Annual spending target set to "
                    f"£{_last_result.max_spending_gbp:,.0f} "
                    f"and saved."
                )
                st.rerun()
