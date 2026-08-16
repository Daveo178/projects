"""`main.py` — entry point for "Couples' Retirement Planner".

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
    page_title="Couples' Retirement Planner",
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

st.title("Couples' Retirement Planner")
st.write("Use the sidebar to navigate through your retirement planning dashboard.")

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
