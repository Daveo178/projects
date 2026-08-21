"""`main.py` — entry point for "Retirement Planner".

Three things happen here, in order:
1. `st.set_page_config(...)` — registers the app name + wide layout.
2. `apply_chrome()` from `brand_chrome` — injects the brand
   stylesheet (LIGHT palette only, since light mode is now
   permanent — the dark-mode radio was removed per user request).
   Every other page also calls `apply_chrome()` at the top, so the
   palette propagates uniformly across all 13 pages (the
   pre-helper state of main.py-only injection meant non-main pages
   rendered without the brand palette). See `brand_chrome.py`.
3. `init_household(...)` — seeds the in-memory plan dict on the first
   visit of a browser tab. Plans live in per-visitor `session_state`
   (no local files), so the app is safe to host on Streamlit
   Community Cloud; use the Home page's Download/Upload buttons to
   keep a personal copy.
"""

import streamlit as st

from brand_chrome import apply_chrome
from storage import init_household, has_saved_plan
from pages_helpers.global_controls import render_global_controls_sidebar


st.set_page_config(
    page_title="Retirement Planner",
    layout="wide",
)

# Brand stylesheet — LIGHT palette (light mode is now permanent).
# Called once per script run; Streamlit re-runs top-to-bottom on
# every interaction so the stylesheet is re-injected after every
# navigation. The identical helper is also called at the top of
# every numbered page (`pages/1_Home.py` ... `pages/13_What_If.py`).
apply_chrome()


# Initialise session state — seed the in-memory plan on first visit of a
# browser tab (no disk read; the plan lives only in this session).
init_household(st.session_state)

# Global sidebar controls — inflation slider shared across ALL
# pages (Quick Estimate + the detailed pages read the same value).
render_global_controls_sidebar()

if "simulation_results" not in st.session_state:
    st.session_state.simulation_results = None

st.title("Retirement Planner")
st.write("Use the sidebar to navigate through your retirement planning dashboard.")

# Keep this deliberately short and user-facing. Add the newest item at the
# top so visitors can quickly see what has changed without opening a detail
# page or reading technical release notes.
with st.expander("📝 Recent changes", expanded=True):
    st.markdown(
        "**August 2026**\n\n"
        "- **More realistic Monte Carlo:** DC pension growth, DB indexation "
        "and ISA/GIA/cash/property returns are now sampled fresh every year "
        "of each run, so a simulation experiences year-to-year market "
        "variation instead of one fixed rate for the whole run.\n"
        "- **State Pension tracks inflation:** In Monte Carlo the State "
        "Pension now rises with each run's sampled inflation, and stays flat "
        "in the today's-money view.\n"
        "- **Clearer spending plans:** Quick Estimate now supports three "
        "explicit age-based spending phases, such as £40,000 until age 70, "
        "£30,000 until age 80, then £20,000 until age 94.\n"
        "- **Better visibility:** Your phase schedule is retained in the "
        "saved plan and appears as a stepped line on the income graph.\n"
        "- **Backwards compatibility:** Existing percentage-taper plans "
        "continue to run on the detailed Spending page."
    )

with st.expander("📘 How to use the planner and how the engine works", expanded=False):
    st.markdown(
        "### Quick start\n"
        "1. Open **Quick Estimate** from the sidebar.\n"
        "2. Enter each person’s date of birth, retirement date, pension pots, "
        "DB income and earnings.\n"
        "3. Enter ISA, GIA, cash, property and any mortgage details.\n"
        "4. Enter your three spending phases in today’s money. For example: "
        "£40,000 until age 70, £30,000 until age 80, then £20,000 until age 94.\n"
        "5. Click **Run Quick Estimate**. The detailed pages use the same saved plan.\n"
        "6. Download the plan from **Home** if you want to keep a copy outside this browser session."
    )

    st.markdown("### Tax and the amount you draw")
    st.markdown(
        "The spending figure is treated as the amount you want available for "
        "your lifestyle **after income tax**. The engine therefore does not "
        "simply add a fixed tax percentage to your spending.\n\n"
        "When a post-retirement shortfall is funded from a DC pension, it "
        "calculates the gross pension withdrawal, applies the tax-free PCLS "
        "allowance where available, calculates tax on the taxable UFPLS "
        "portion, and keeps increasing the gross withdrawal until the "
        "after-tax cash requirement is met or the available pots are exhausted."
    )
    st.markdown(
        "Tax is calculated **separately for each person**, using the model’s "
        "2024/25 assumptions: £12,570 personal allowance, 20% basic rate, "
        "40% higher rate and 45% additional rate. The personal allowance is "
        "also tapered at high income. Pension withdrawals can therefore "
        "require a larger gross draw when they use up the basic-rate band, "
        "move into the higher-rate band, or reach the additional-rate band."
    )
    st.markdown(
        "The engine recalculates tax cumulatively across repeated pension "
        "draws in the same year, so it does account for the higher marginal "
        "bands. It is **not a tax optimiser**, however: it follows the "
        "drawdown priority you choose. Put Cash/ISA/GIA before Pension if "
        "you want to defer taxable pension income; the model treats normal "
        "Cash, ISA and GIA withdrawals as untaxed, and CGT on GIA withdrawals "
        "is currently outside scope."
    )
    st.markdown(
        "National Insurance is applied to earned salary only. DB pensions, "
        "State Pension and pension withdrawals do not attract NI in this model."
    )

    st.markdown("### Pension drawdown and spending rules")
    st.markdown(
        "- Pension drawdown is normally gated until at least one person has "
        "retired. Before then, the income line can sit below spending to show "
        "a real cash-flow gap.\n"
        "- The default drawdown order is **Pension → Cash → ISA → GIA**. "
        "The detailed Spending page lets you change that order.\n"
        "- The tax-free pension amount is limited by the saved PCLS allowance "
        "and the engine’s 25%-of-that-withdrawal preference; the rest of the "
        "pension withdrawal is taxable.\n"
        "- If the pension and liquid assets cannot meet the requirement, the "
        "income received is allowed to fall short rather than inventing money.\n"
        "- Property is not normally drawn down. It only changes through its "
        "growth assumption or an explicit life event such as downsizing."
    )

    st.markdown("### Growth, inflation and timing")
    st.markdown(
        "- DC pensions compound monthly and receive contributions while the "
        "person is working. ISA, GIA, cash and property grow annually using "
        "their saved assumptions.\n"
        "- Quick Estimate runs in **today’s money**. It removes inflation from "
        "investment and wage growth using the simple real-rate convention "
        "nominal growth minus the global inflation assumption; DB and State "
        "Pension payments stay flat in that view, and property growth is "
        "zeroed. Mortgage interest still applies.\n"
        "- The simulation runs year by year to the joint-life plan horizon. "
        "The couple’s horizon is driven by the later partner’s selected end "
        "age, while single-retiree mode excludes Person 2.\n"
        "- Mortgage interest is applied, then the scheduled payment reduces "
        "the balance. Unless **include mortgage in spending** is enabled, the "
        "mortgage payment is funded in addition to lifestyle spending."
    )

    st.markdown("### Monte Carlo assumptions and ranges")
    st.markdown(
        "The Monte Carlo page runs 100–5,000 paths, with 1,000 by default. "
        "The table shows the current model settings and the approximate "
        "95% range implied by the normal distributions. These are not hard "
        "limits unless a floor is explicitly shown."
    )
    st.markdown(
        "| Variable | Current app setting | Approx. modelled range | Broad professional-style planning band* |\n"
        "|---|---|---:|---:|\n"
        "| ISA / GIA annual return | User mean; default 5%, 10% SD | About -15% to +25% at default | About 3%–8% return; 6%–20% volatility depending on portfolio |\n"
        "| DC pension growth | User mean, sampled fresh each year; 5 percentage-point SD; -30% floor | Single-year user rate ± about 10 percentage points at 95% | About 3%–8% return; 6%–20% volatility depending on asset mix |\n"
        "| Property annual return | Default 2%, 5% SD | About -8% to +12% at default | About 3%–7% return; commonly higher volatility than this model |\n"
        "| Cash annual return | Default 1%, 1% SD | About -1% to +3% at default | About 1%–4% return; usually low volatility |\n"
        "| Inflation | Default 2.5%, 1 percentage-point SD each year | About 0.5%–4.5% at 95% | Roughly 2%–4% central planning range, with wider stress tests |\n"
        "| DB growth | User mean, sampled fresh each year; 1 percentage-point SD | Single-year user rate ± about 2 percentage points at 95% | Usually linked to explicit inflation or policy assumptions |\n"
        "| State Pension growth | Indexed to that run's sampled inflation each year; flat in today's-money view | Tracks the sampled inflation band (about 0.5%–4.5% at 95%) | Usually linked to explicit inflation or policy assumptions |\n"
        "| Wage growth | User rate, sampled once per run; 1 percentage-point SD | User rate ± about 2 percentage points at 95% | Usually linked to explicit inflation or policy assumptions |\n"
        "| Spending shock | Independent 5% SD each year | About 90%–110% of that year’s planned spend at 95% | No universal standard; advisers often use explicit spending scenarios and one-off costs |"
    )
    st.caption(
        "*The professional-style column is a broad comparison guide, not a "
        "published FCA or industry standard. Public professional tools do "
        "not use one common parameter set: assumptions vary by provider, "
        "portfolio risk level, time horizon, fee treatment and whether figures "
        "are nominal or real."
    )
    st.markdown(
        "**Important limitations of this implementation:** returns for ISA, "
        "GIA, cash and property are independently sampled each year, with no "
        "asset correlations or inflation/return correlation. DC growth is "
        "sampled fresh each year too; DB indexation is sampled annually "
        "around the user's rate; State Pension growth is linked to the "
        "sampled inflation path; wage growth is sampled once per run. Tax, "
        "charges, GIA capital gains tax, mortality, care costs and "
        "investment allocation changes are not randomised. Success currently "
        "means year-end total modelled net worth stays above zero; property "
        "can therefore contribute to the success result even though it is not "
        "normally drawn down."
    )
    st.markdown(
        "Use the results as a **general personal planning guide** and compare "
        "the percentile bands with deterministic stress cases. They do not "
        "replace regulated financial or tax advice from a qualified planner."
    )

    st.markdown("### Important planning notes")
    st.markdown(
        "This is an illustrative planning model, not regulated financial or "
        "tax advice. It does not model every UK tax rule, State Pension "
        "entitlement, scheme-specific pension rule, investment fee, sequence "
        "of returns detail, GIA capital gain, inheritance-tax treatment or "
        "care-cost scenario. Monte Carlo adds randomised returns, inflation "
        "and spending shocks, but it is still only a range of modelled outcomes."
    )

# A tiny status hint so the user knows how their plan is held.
if has_saved_plan(st.session_state):
    st.caption(
        "💾 Your plan is held in this browser session (in-memory). "
        "Use the Home page's Download button to keep a personal copy."
    )
else:
    st.caption(
        "ℹ️ No plan yet — your inputs live in this browser session and "
        "can be downloaded from the Home page."
    )
