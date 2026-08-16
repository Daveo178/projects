"""Shared helpers exposed to the Streamlit pages layer.

Pulled OUT of `pages/` because Streamlit's multipage scanner treats
every `pages/*.py` file as a sidebar page — the Python
leading-underscore convention does NOT actually exclude files (only
`__init__.py` is automatically skipped), so the three helper
modules were rendering as three empty sidebar pages above the 13
real ones. The fix is to relocate them to a sibling directory that
Streamlit never scans, leaving `pages/` to contain only the 13
numbered user-facing pages.

Modules:
  * `pages_helpers.view_badge`       — yellow-amber
    "INFLATION STRIPPED" badge shown above results when the
    today's-value toggle is on. Used on Home, Timeline, Tax View.
  * `pages_helpers.today_value_toggle` — Shared "Show in today's
    value" toggle widget with a per-page key suffix so the same
    widget instance lives on multiple pages without
    `StreamlitDuplicateWidgetKey` errors when the user navigates
    within the same browser session. Used on Timeline, Scenarios,
    What If (and Home, which still inlines its own copy for the
    inline Run-Simulation button tied to its on_today_value_toggle
    callback — see the migration follow-up in `pages/1_Home.py`).
  * `pages_helpers.household_builder` — `build_household_from_
    session_state()` factory used by Timeline's today-value
    rebuild path. The Home page also has an inline copy (still
    in the page for tighter coupling with its toggle callback)
    — centralising it into this helper is a planned follow-up.
"""
