"""Reusable \"Show in today's value\" toggle widget.

Used by every engine-driving page (Home, Timeline, Scenarios, What If)
so the user can flip the toggle from any of those pages and have the
same `household_data["show_in_todays_value"]` flag take effect on the
next render. Centralising the widget here ensures:

  * Cross-page consistency — every instance renders the same label,
    same help text, same icon, same on_change semantics. A user
    moving between Home / Timeline / Scenarios sees the SAME toggle
    phrase and gets the SAME behaviour.

  * Single behaviour contract — the toggle always persists
    `household_data["show_in_todays_value"]` (so subsequent runs
    anywhere in the app inherit the state), and OPTIONALLY rebuilds
    `st.session_state.simulation_results` for pages that consume
    that dict directly (Timeline, Home).

  * No duplication of the Streamlit widget arg list (label, key,
    help_text) — each caller passes a `key_suffix` and gets back
    the rendered toggle. A future tweak to the label propagates
    app-wide without touching every page.

Usage
-----
At the top of any engine-driving page:

    from pages_helpers.today_value_toggle import render_today_value_toggle

    # Timeline-style: persist AND rebuild simulation_results inline
    _ = render_today_value_toggle(
        key_suffix="timeline",
        on_change_rebuild_results=lambda: _rebuild_results(),
    )

    # Scenarios-style: persist only (next "Run Comparison" picks it up)
    _ = render_today_value_toggle(key_suffix="scenarios")

The `key_suffix` ensures the Streamlit widget keys are unique per
page (so the toggle's `key="show_today_value_timeline"` differs from
`"show_today_value_scenarios"`), eliminating cross-page
`StreamlitDuplicateWidgetKey` errors when a user navigates between
pages within the same browser tab.
"""

from __future__ import annotations

from typing import Callable, Optional

import streamlit as st


_DEFAULT_HELP = (
    "Educational / simplified mode: strips inflation out of the "
    "projection. Mortgage interest KEEPS applying; property value "
    "growth is zeroed; DB pension and State Pension stay flat at "
    "their year-0 base figures; DC pot and other asset growth use "
    "real (= nominal − inflation) rates.\n\n"
    "Math convention: a 7% nominal asset return assumed at 2.5% "
    "inflation becomes 4.5% in today's money (simple subtraction, "
    "not Fischer's equation — matches how the rates are quoted on "
    "the Pension page).\n\n"
    "This toggle is SHARED across all engine-driving pages — once "
    "you flip it on any page, every page's next render / next run "
    "uses today's-money rules."
)


def render_today_value_toggle(
    key_suffix: str,
    *,
    disabled: bool = False,
    on_change_rebuild_results: Optional[Callable[[], None]] = None,
    help_text: str = _DEFAULT_HELP,
    label: str = "Show in today's value (no inflation, real terms only)",
) -> bool:
    """Render the today's-value toggle widget and persist its state.

    Parameters
    ----------
    key_suffix : str
        Unique per-page suffix for the widget's Streamlit key
        (e.g. `"timeline"`, `"scenarios"`, `"what_if"`). Required
        to avoid `StreamlitDuplicateWidgetKey` when a user navigates
        between pages that all have this toggle.

    disabled : bool, optional
        When True, the widget renders disabled (greyed-out) — used
        by the Home page when required keys haven't been entered.
        Defaults to False.

    on_change_rebuild_results : callable, optional
        Callback fired inside `on_change` to rebuild
        `st.session_state.simulation_results` inline (so a Timeline
        / Home page's charts re-render in today's-money terms on
        the very same page refresh, no manual Run Simulation click
        required). When None, the toggle only persists the flag
        — pages with their own Run button (Scenarios "Run Comparison",
        What If "Run What-If Scenario") consume the flag at the next
        run.

    help_text : str, optional
        Tooltip text. Defaults to the standard explanation referencing
        the four invariant deltas (mortgage kept, property zeroed,
        DB / SP flat, DC / asset growth real rates) plus the simple-
        subtraction math convention.

    label : str, optional
        Visible label. Defaults to "Show in today's value (no inflation,
        real terms only)" — the same label the Home page already uses.

    Returns
    -------
    bool
        The toggle's CURRENT value (pre-flip), read from
        `household_data["show_in_todays_value"]`. Useful for pages
        that gate logic on this flag inside their own code paths
        (e.g. showing the INFLATION-STRIPPED badge via
        `pages_helpers.view_badge.render_view_mode_badge(results)`).
    """
    data = st.session_state.household_data
    prev_value = bool(data.get("show_in_todays_value", False))

    widget_key = f"show_today_value_{key_suffix}"

    def _on_change() -> None:
        # Streamlit commits the new value to `st.session_state[widget_key]`
        # BEFORE this callback runs. We read the new value from there
        # (NOT from the closed-over `prev_value`, which still points
        # at the pre-flip value).
        new_val = bool(st.session_state[widget_key])
        # Persist into the household-data dict so subsequent runs /
        # other pages inheriting the same browser session see the
        # new mode. `data` is the same dict-as-reference that
        # `st.session_state.household_data` points to, so writing
        # `data["show_in_todays_value"] = new_val` is equivalent to
        # `st.session_state.household_data["show_in_todays_value"]`.
        if isinstance(data, dict):
            data["show_in_todays_value"] = new_val
        # Optional inline rebuild for pages that consume
        # `simulation_results` directly without an explicit "Run"
        # button (Timeline). The new value is in
        # `st.session_state.household_data["show_in_todays_value"]`
        # by the time the callback fires, so any rebuild using the
        # shared `build_household_from_session_state()` helper will
        # see the new flag.
        if on_change_rebuild_results is not None:
            on_change_rebuild_results()

    st.toggle(
        label,
        value=prev_value,
        key=widget_key,
        disabled=disabled,
        help=help_text,
        on_change=_on_change,
    )
    if disabled:
        st.caption(
            "ℹ️ Complete pages 1–7 first — the toggle unlocks once "
            "all required fields are entered."
        )
    return prev_value


__all__ = ["render_today_value_toggle"]
