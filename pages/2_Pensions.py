import streamlit as st

from simulation.aa import aa_status, effective_aa, project_annual_contribution
from simulation.years_and_months import (
    _split_years_into_years_and_months,
    _format_years_months_caption,
)
from storage import init_household, save_household

st.title("💼 Pensions")

# ----------------------------------------
# UK Pension Annual Allowance (AA) helper + page-level disclaimer.
# HMRC rule (2023/24 + 2024/25): standard AA = £60,000, tapers down to a
# £10,000 floor for incomes above £200,000. We approximate the threshold
# income as the user's `income_until_retirement` (the Pensions page has
# no separate field for non-employment income). Not modelled: employer
# pension contributions, carry-forward from prior tax years, defined-
# benefit scheme accrual values, or the two-stage "adjusted income"
# test — so this is a planning approximation, not advice.
# ----------------------------------------
def _show_aa_status(name, pct_value, flat_value, income):
    proj = project_annual_contribution({
        "monthly_contrib_pct": pct_value,
        "income_until_retirement": income,
        "monthly_contrib": flat_value,
    })
    aa = effective_aa(income)
    # Comparison direction lives in `simulation.aa.aa_status` so it can be
    # unit-tested directly without rendering the warning / caption. The page
    # helper only decides the visual treatment for each returned token.
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


st.info(
    "🇬🇧 **UK Pension Annual Allowance** — standard £60,000/yr, "
    "tapered to £10,000 above £200,000 threshold income. "
    "This page uses threshold income alone. HMRC's full rule additionally "
    "requires adjusted income above £260,000 before tapering activates, "
    "so the warning shown here may fire for users who would actually "
    "qualify for the full £60,000 AA under the real two-stage test. "
    "Each partner has their own independent AA envelope. "
    "Not modelled: employer contributions, carry-forward from prior tax "
    "years, and defined-benefit accrual values."
)

# ----------------------------------------
# 1. Initialise session_state — seed from disk on first visit
# ----------------------------------------
init_household(st.session_state)

# Convenience shortcuts
p1 = st.session_state.household_data.get("person1", {})
p2 = st.session_state.household_data.get("person2", {})


# ----------------------------------------
# Soft migration: derive the % slider default from a legacy monthly £ value
# when present (gives legacy users a slider that matches their old contribution
# amount on first open, rather than silently rebasing to 15%). New users with
# no stored data get the 15% default directly.
# ----------------------------------------
def _migrate_contrib_pct(p_dict, default_if_empty=0.15):
    pct = p_dict.get("monthly_contrib_pct", None)
    if pct is not None:
        return pct
    mc = p_dict.get("monthly_contrib", 0)
    inc = p_dict.get("income_until_retirement", 0)
    if mc > 0 and inc > 0:
        # Cap at 50% so a wildly-shaped legacy plan doesn't render off-scale.
        return min(0.50, (mc * 12) / inc)
    return default_if_empty


p1_pct_default = _migrate_contrib_pct(p1)
p2_pct_default = _migrate_contrib_pct(p2)



# ----------------------------------------
# 2. Dave
# ----------------------------------------
st.header("Dave")

# ---- Retirement-age form ----------------------------------------------
# Dave's retirement-age control. The shared Years+Months helpers from
# `simulation.years_and_months` (also used by the Mortgage form on
# pages/3_Assets.py) split the saved float + render the friendly
# English caption. Verb "retires" + empty noun so the caption reads
# "Retires in 60 years and 6 months." rather than the
# boilerplate-noun "Person retires in..."
d_age = st.number_input("Age", 18, 100, p1.get("age", 55), key="d_age")

d_ret_default_years, d_ret_default_months = _split_years_into_years_and_months(
    p1.get("retirement_age", 60)
)
col_d_ret_years, col_d_ret_months = st.columns(2)
with col_d_ret_years:
    d_ret_years = st.number_input(
        "Retirement age (years)",
        min_value=0,
        max_value=80,
        value=d_ret_default_years,
        key="d_ret_years",
    )
with col_d_ret_months:
    d_ret_months = st.number_input(
        "Retirement age (months)",
        min_value=0,
        max_value=11,
        value=d_ret_default_months,
        key="d_ret_months",
        help="Additional months beyond the years field. For example '6' here with '60' in Years gives a retirement age of 60.5. The engine only contributes to the DC pot for the fractional slice of the closing year.",
    )
st.caption(
    _format_years_months_caption(
        verb="retires",
        noun="",
        years=d_ret_years, months=d_ret_months,
        empty_message="Already retired today (no remaining working period).",
    )
)

d_sp = st.number_input("State Pension age", 60, 80, p1.get("state_pension_age", 67), key="d_sp")
d_dc = st.number_input("DC pot (£)", 0, 5_000_000, p1.get("dc_pot", 0), key="d_dc")
d_contrib_pct = st.slider(
    "Monthly DC contribution (% of annual income)",
    0.0, 50.0,
    p1_pct_default * 100,
    step=0.5,
    key="d_contrib_pct",
    help="Total pension contribution as a percentage of annual income (wage-inflation indexed each year). Added monthly to the DC pot; growth compounds monthly. Default 15% reflects a typical total pension contribution. Leave at 0% to fall back to a flat £ figure below.",
) / 100
d_contrib_flat = st.number_input(
    "Flat monthly contribution (£, used only when % is 0)",
    0, 5000,
    p1.get("monthly_contrib", 0),
    key="d_contrib_flat",
    help="Legacy absolute £ figure. Used by the engine only when the % slider above is set to 0. New users can leave this at 0.",
)
d_income = st.number_input("Annual income until retirement (£)", 0, 500_000, p1.get("income_until_retirement", 0), key="d_income")
_show_aa_status("Dave", d_contrib_pct, d_contrib_flat, d_income)
d_income_growth = st.slider(
    "Annual income growth (% wage inflation)",
    0.0, 10.0,
    p1.get("income_growth_rate", 0.025) * 100,
    step=0.1,
    key="d_income_growth",
    help="Annual wage-inflation applied to the annual income figure from 'now' until retirement_age. Default 2.5% reflects typical UK wage inflation. Drops to 0 at retirement — DB / State Pension / drawdown take over.",
) / 100
d_db = st.number_input("DB annual income (£)", 0, 200_000, p1.get("db_income", 0), key="d_db")
d_draw = st.number_input("DB draw age", 50, 80, p1.get("draw_age", 60), key="d_draw")
d_pcls_percent = st.slider(
    "Tax‑free lump sum percentage (PCLS)",
    0, 25,
    p1.get("pcls_percent", 0),
    key="d_pcls_percent"
)
d_dc_growth = st.slider(
    "DC pot annual growth (%)",
    0.0, 15.0,
    p1.get("dc_growth_rate", 0.05) * 100,
    step=0.1,
    key="d_dc_growth",
    help="Average annual investment growth applied to the DC pot. Compounds on the opening balance every year, including during retirement. Default 5% reflects a long-run balanced portfolio nominal return.",
) / 100
d_db_growth = st.slider(
    "DB pension annual growth (%)",
    0.0, 10.0,
    p1.get("db_growth_rate", 0.025) * 100,
    step=0.1,
    key="d_db_growth",
    help="Annual indexation applied to the DB pension income once it begins paying. Default 2.5% reflects typical RPI / CPI indexation.",
) / 100
d_sp_growth = st.slider(
    "State Pension annual growth (%)",
    0.0, 10.0,
    p1.get("state_pension_growth_rate", 0.025) * 100,
    step=0.1,
    key="d_sp_growth",
    help="Annual indexation applied to the State Pension once the State Pension age is reached. Default 2.5% approximates the triple-lock.",
) / 100



# ----------------------------------------
# 3. Shaz
# ----------------------------------------
st.header("Shaz")

s_age = st.number_input("Age ", 18, 100, p2.get("age", 55), key="s_age")

s_ret_default_years, s_ret_default_months = _split_years_into_years_and_months(
    p2.get("retirement_age", 60)
)
col_s_ret_years, col_s_ret_months = st.columns(2)
with col_s_ret_years:
    s_ret_years = st.number_input(
        "Retirement age (years) ",
        min_value=0,
        max_value=80,
        value=s_ret_default_years,
        key="s_ret_years",
    )
with col_s_ret_months:
    s_ret_months = st.number_input(
        "Retirement age (months) ",
        min_value=0,
        max_value=11,
        value=s_ret_default_months,
        key="s_ret_months",
        help="Additional months beyond the years field. For example '6' here with '60' in Years gives a retirement age of 60.5. The engine only contributes to the DC pot for the fractional slice of the closing year.",
    )
st.caption(
    _format_years_months_caption(
        verb="retires",
        noun="",
        years=s_ret_years, months=s_ret_months,
        empty_message="Already retired today (no remaining working period).",
    )
)

s_sp = st.number_input("State Pension age ", 60, 80, p2.get("state_pension_age", 67), key="s_sp")
s_dc = st.number_input("DC pot (£) ", 0, 5_000_000, p2.get("dc_pot", 0), key="s_dc")
s_contrib_pct = st.slider(
    "Monthly DC contribution (% of annual income)",
    0.0, 50.0,
    p2_pct_default * 100,
    step=0.5,
    key="s_contrib_pct",
    help="Total pension contribution as a percentage of annual income (wage-inflation indexed each year). Added monthly to the DC pot; growth compounds monthly. Default 15% reflects a typical total pension contribution. Leave at 0% to fall back to a flat £ figure below.",
) / 100
s_contrib_flat = st.number_input(
    "Flat monthly contribution (£, used only when % is 0)",
    0, 5000,
    p2.get("monthly_contrib", 0),
    key="s_contrib_flat",
    help="Legacy absolute £ figure. Used by the engine only when the % slider above is set to 0. New users can leave this at 0.",
)
s_income = st.number_input("Annual income until retirement (£) ", 0, 500_000, p2.get("income_until_retirement", 0), key="s_income")
_show_aa_status("Shaz", s_contrib_pct, s_contrib_flat, s_income)
s_income_growth = st.slider(
    "Annual income growth (% wage inflation)",
    0.0, 10.0,
    p2.get("income_growth_rate", 0.025) * 100,
    step=0.1,
    key="s_income_growth",
    help="Annual wage-inflation applied to the annual income figure from 'now' until retirement_age. Default 2.5% reflects typical UK wage inflation. Drops to 0 at retirement — DB / State Pension / drawdown take over.",
) / 100
s_db = st.number_input("DB annual income (£)", 0, 200_000, p2.get("db_income", 0), key="s_db")
s_draw = st.number_input("DB draw age", 50, 80, p2.get("draw_age", 60), key="s_draw")
s_pcls_percent = st.slider(
    "Tax‑free lump sum percentage (PCLS)",
    0, 25,
    p2.get("pcls_percent", 0),
    key="s_pcls_percent"
)
s_dc_growth = st.slider(
    "DC pot annual growth (%)",
    0.0, 15.0,
    p2.get("dc_growth_rate", 0.05) * 100,
    step=0.1,
    key="s_dc_growth",
    help="Average annual investment growth applied to the DC pot. Compounds on the opening balance every year, including during retirement. Default 5% reflects a long-run balanced portfolio nominal return.",
) / 100
s_db_growth = st.slider(
    "DB pension annual growth (%)",
    0.0, 10.0,
    p2.get("db_growth_rate", 0.025) * 100,
    step=0.1,
    key="s_db_growth",
    help="Annual indexation applied to the DB pension income once it begins paying. Default 2.5% reflects typical RPI / CPI indexation.",
) / 100
s_sp_growth = st.slider(
    "State Pension annual growth (%)",
    0.0, 10.0,
    p2.get("state_pension_growth_rate", 0.025) * 100,
    step=0.1,
    key="s_sp_growth",
    help="Annual indexation applied to the State Pension once the State Pension age is reached. Default 2.5% approximates the triple-lock.",
) / 100



# ----------------------------------------
# 4. Save button
# ----------------------------------------
if st.button("Save Pension Data"):
    st.session_state.household_data["person1"] = {
        "name": "Dave",
        "age": d_age,
        # Persist as a single float so the engine sees one canonical
        # `retirement_age` value regardless of whether the user entered
        # an integer years + 0 months or a partial-year combination
        # (e.g. `60 years 6 months` → `60.5`). The explicit `float(...)`
        # cast guarantees the JSON value is serialised as a number even
        # when years and months are decimal literals. The two-field
        # form mirrors the Mortgage Years+Months input on pages/3_Assets.py.
        "retirement_age": float(d_ret_years) + d_ret_months / 12.0,
        "state_pension_age": d_sp,
        "dc_pot": d_dc,
        "monthly_contrib": d_contrib_flat,  # legacy £ field — engine reads it only when monthly_contrib_pct is 0
        "monthly_contrib_pct": d_contrib_pct,
        "income_until_retirement": d_income,
        "income_growth_rate": d_income_growth,
        "db_income": d_db,
        "draw_age": d_draw,
        "pcls_percent": d_pcls_percent,
        "dc_growth_rate": d_dc_growth,
        "db_growth_rate": d_db_growth,
        "state_pension_growth_rate": d_sp_growth,
    }

    st.session_state.household_data["person2"] = {
        "name": "Shaz",
        "age": s_age,
        # Same Years+Months → float conversion as Person 1 (Dave) above.
        "retirement_age": float(s_ret_years) + s_ret_months / 12.0,
        "state_pension_age": s_sp,
        "dc_pot": s_dc,
        "monthly_contrib": s_contrib_flat,  # legacy £ field — engine reads it only when monthly_contrib_pct is 0
        "monthly_contrib_pct": s_contrib_pct,
        "income_until_retirement": s_income,
        "income_growth_rate": s_income_growth,
        "db_income": s_db,
        "draw_age": s_draw,
        "pcls_percent": s_pcls_percent,
        "dc_growth_rate": s_dc_growth,
        "db_growth_rate": s_db_growth,
        "state_pension_growth_rate": s_sp_growth,
    }

    save_household(st.session_state.household_data)
    st.success("Pension data saved!")
