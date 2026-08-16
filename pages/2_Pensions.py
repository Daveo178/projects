"""`pages/2_Pensions.py` — Pensions page (detail-only).

The BASIC pension inputs — date of birth, retirement date, State
Pension age, DC pot, DB income, DB draw age, PCLS %, income until
retirement, and the personal / employer contributions — are all
entered on the **Quick Estimate** page
(`pages/0_Quick_Estimate.py`), which is the single basis for the
calculation. This page holds ONLY the advanced per-partner **growth
assumptions** (wage inflation, DC growth, DB indexation, State
Pension indexation) plus a read-only UK Pension Annual Allowance
(AA) read-out computed from the contribution values Quick Estimate
saved.
"""
import streamlit as st
from brand_chrome import apply_chrome

from simulation.aa import aa_status, effective_aa, project_annual_contribution
from storage import init_household, save_household
from pages_helpers.global_controls import render_global_controls_sidebar

# Brand stylesheet (LIGHT palette only) + global sidebar inflation
# slider — same chrome every page uses.
apply_chrome()
render_global_controls_sidebar()

st.title("💼 Pensions — Growth assumptions")

st.caption(
    "Basic pension inputs (dates, pots, DB income, PCLS, "
    "contributions) are entered on the **Quick Estimate** page — "
    "this page only refines the **growth assumptions** used to "
    "project them."
)

# ----------------------------------------
# UK Pension Annual Allowance (AA) disclaimer.
# HMRC rule (2023/24 + 2024/25): standard AA = £60,000, tapers down to a
# £10,000 floor for incomes above £200,000. We approximate the threshold
# income as the user's `income_until_retirement` (the Quick Estimate
# page has no separate field for non-employment income). Not modelled:
# employer pension contributions, carry-forward from prior tax years,
# defined-benefit scheme accrual values, or the two-stage "adjusted
# income" test — so this is a planning approximation, not advice.
# ----------------------------------------
st.info(
    "🇬🇧 **UK Pension Annual Allowance** — standard £60,000/yr, "
    "tapered to £10,000 above £200,000 threshold income. "
    "This page uses threshold income alone. HMRC's full rule additionally "
    "requires adjusted income above £260,000 before tapering activates, "
    "so the warning shown here may fire for users who would actually "
    "qualify for the full £60,000 AA under the real two-stage test. "
    "Each partner has their own independent AA envelope. "
    "The projection now INCLUDES employer pension contributions "
    "(employee + employer combined = total AA exposure). Not modelled: "
    "carry-forward from prior tax years, and defined-benefit accrual "
    "values."
)

# ----------------------------------------
# 1. Initialise session_state — seed from disk on first visit
# ----------------------------------------
init_household(st.session_state)

data = st.session_state.household_data
p1 = data.get("person1", {})
p2 = data.get("person2", {})


def _show_aa_status_readonly(name: str, person: dict) -> None:
    """Read-only AA read-out from the SAVED contribution values.

    Contribution values are now owned by the Quick Estimate page, so
    this helper reads them from the saved `person` dict (rather than
    live widgets) and mirrors the same input-dict rules the engine's
    `_monthly_dc_contrib` uses: any new personal/employer field
    non-zero → use the new fields; otherwise fall back to legacy.
    """
    pct = float(person.get("personal_contrib_pct", 0.0))
    flat = float(person.get("personal_contrib_flat_monthly", 0.0))
    employer = float(person.get("employer_contrib_pct", 0.0))
    income = float(person.get("income_until_retirement", 0.0))
    legacy_pct = float(person.get("monthly_contrib_pct", 0.0))
    legacy_flat = float(person.get("monthly_contrib", 0.0))
    if pct > 0 or flat > 0 or employer > 0:
        proj_dict = {
            "personal_contrib_pct": pct,
            "personal_contrib_flat_monthly": flat,
            "employer_contrib_pct": employer,
            "income_until_retirement": income,
        }
    else:
        proj_dict = {
            "monthly_contrib_pct": legacy_pct,
            "monthly_contrib": legacy_flat,
            "income_until_retirement": income,
        }
    proj = project_annual_contribution(proj_dict)
    aa = effective_aa(income)
    if aa_status(proj, aa) == "exceeded":
        st.warning(
            f"⚠️ {name}: annual pension contribution "
            f"£{proj:,.0f} exceeds the effective AA "
            f"£{aa:,.0f} (income £{income:,.0f}). The excess will face "
            f"the HMRC Annual Allowance Charge."
        )
    else:
        st.caption(
            f"🇬🇧 {name} AA: £{proj:,.0f} of £{aa:,.0f} used "
            f"(income £{income:,.0f}, headroom £{aa - proj:,.0f})."
        )


def _render_growth_block(name: str, person: dict, prefix: str) -> dict:
    """Four per-partner growth-rate sliders — the page's only inputs.

    Widget keys are prefixed with the partner's old page prefix
    (`d` / `s`) so session_state continuity with the previous
    detailed page is preserved for users who had these widgets.
    """
    st.header(name)

    income_growth = st.slider(
        "Annual income growth (% wage inflation)",
        0.0, 10.0,
        float(person.get("income_growth_rate", 0.025)) * 100,
        step=0.1,
        key=f"{prefix}_income_growth",
        help=(
            "Annual wage-inflation applied to the annual income figure "
            "from 'now' until retirement_age (set on Quick Estimate). "
            "Default 2.5% reflects typical UK wage inflation."
        ),
    ) / 100

    dc_growth = st.slider(
        "DC pot annual growth (%)",
        0.0, 15.0,
        float(person.get("dc_growth_rate", 0.05)) * 100,
        step=0.1,
        key=f"{prefix}_dc_growth",
        help=(
            "Average annual investment growth applied to the DC pot. "
            "Compounds on the opening balance every year, including "
            "during retirement. Default 5% reflects a long-run balanced "
            "portfolio nominal return."
        ),
    ) / 100

    db_growth = st.slider(
        "DB pension annual growth (%)",
        0.0, 10.0,
        float(person.get("db_growth_rate", 0.025)) * 100,
        step=0.1,
        key=f"{prefix}_db_growth",
        help=(
            "Annual indexation applied to the DB pension income once it "
            "begins paying. Default 2.5% reflects typical RPI / CPI "
            "indexation."
        ),
    ) / 100

    sp_growth = st.slider(
        "State Pension annual growth (%)",
        0.0, 10.0,
        float(person.get("state_pension_growth_rate", 0.025)) * 100,
        step=0.1,
        key=f"{prefix}_sp_growth",
        help=(
            "Annual indexation applied to the State Pension once the "
            "State Pension age is reached. Default 2.5% approximates "
            "the triple-lock."
        ),
    ) / 100

    # Read-only AA consequence of the Quick-Estimate-set contributions.
    _show_aa_status_readonly(name, person)

    return {
        "income_growth_rate": income_growth,
        "dc_growth_rate": dc_growth,
        "db_growth_rate": db_growth,
        "state_pension_growth_rate": sp_growth,
    }


# ----------------------------------------
# 2. Per-partner growth blocks
# ----------------------------------------
d_rates = _render_growth_block("Person 1", p1, "d")
s_rates = _render_growth_block("Person 2", p2, "s")

# ----------------------------------------
# 3. Save — merges ONLY the four growth rates per partner so every
# field owned by the Quick Estimate page is preserved verbatim.
# ----------------------------------------
if st.button("Save Growth Assumptions"):
    data["person1"] = {**p1, **d_rates}
    data["person2"] = {**p2, **s_rates}
    save_household(data)
    st.success("Growth assumptions saved!")
