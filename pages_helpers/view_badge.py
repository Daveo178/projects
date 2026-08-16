"""Reusable view-mode badge for the \"Show in today's value\" toggle.

The Home-page toggle drives an `simulation_results["view_mode"]` flag
in the engine's results dict (`"today"` when today's-value mode is
on, `"nominal"` for the default). Every results-bearing page
(Home / Timeline / Tax View / Scenarios / What If) needs to surface
this state to the user so a viewer can never confuse a today's-money
projection for a nominal projection.

Centralising the badge rendering in one helper ensures:

  * Visual consistency — every page shows the SAME badge text,
    colour, and icon (a yellow-amber st.info banner — chosen over
    `st.success`/`st.error`/`st.warning` for a NEUTRAL advisory tone
    because today's-money mode is informational, not an error or a
    success state).
  * Headline phrasing — the badge mentions the four key invariant
    deltas (mortgage interest kept, property zeroed, DB / SP flat,
    DC / asset growth uses real rates) so a user seeing the badge
    alone knows what changed between modes without having to read
    the toggle's help text on the Home page.
  * Hidden-by-default — only renders when `view_mode == "today"`,
    so the nominal view stays visually identical to the pre-feature
    baseline (no spurious badge cluttering legacy pages).

Usage
=====
Import at the top of any results-bearing page:

    from pages_helpers.view_badge import render_view_mode_badge

Then call it right after the `results = st.session_state.simulation_results`
binding (before the first `st.subheader(...)`):

    results = st.session_state.simulation_results
    render_view_mode_badge(results)
    # ... first subheader starts here ...

The caller may pass an explicit `results` dict OR rely on
session-state auto-discovery (default `results=None` reads
`st.session_state.simulation_results`). The two-argument form
facilitates unit testing without Streamlit session_state.
"""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st


_BadgeText = (
    "📉 **INFLATION STRIPPED** — figures shown are in today's "
    "purchasing power. Mortgage interest still applies; property "
    "value growth is zeroed; DB pension and State Pension stay flat "
    "at their year-0 base figures; DC pot and other asset growth use "
    "real (= nominal − inflation) rates."
)


def render_view_mode_badge(results: Optional[dict] = None) -> None:
    """Render the view-mode badge at the top of a results page.

    Renders nothing when `view_mode != "today"`. Reads from
    `st.session_state.simulation_results` when `results=None`
    (the common call path).

    Parameters
    ----------
    results : dict, optional
        Pre-fetched simulation results dict. When None, the helper
        reads `st.session_state.get("simulation_results")` so call
        sites can save a session-state lookup.

    Notes
    -----
    * Uses `st.info(...)` (blue-cyan advisory background) rather
      than `st.success` (green) / `st.error` (red) / `st.warning`
      (amber) because today's-money mode is INFORMATIONAL — it's
      a valid projection, not a warning or a celebration.

    * First visible difference vs nominal: mortgage remains on
      its full nominal trajectory (interest keeps applying) so
      users don't assume the toggle fully "turns off" mortgage
      accounting.

    * `st.markdown` would be a third rendering option, but
      `st.info` is preferred because the brand-chrome stylesheet
      (`brand_chrome.py`) already styles `st.info` containers
      in a consistent way across the app — using `st.info` keeps
      the badge on-brand without re-implementing styling.
    """
    if results is None:
        results = st.session_state.get("simulation_results")
    if not results:
        return
    if results.get("view_mode") != "today":
        return
    st.info(_BadgeText)


__all__ = ["render_view_mode_badge"]
