"""Global sidebar controls — household-level sliders that apply across ALL pages.

WHY THIS MODULE EXISTS
======================
Before this module, the `inflation_rate` slider was duplicated on three
pages (Pensions, Assets, Quick Estimate) with three different widget keys,
three different save paths, and three opportunities for them to drift out
of sync. The user asked for a SINGLE global slider in the sidebar so:

1. There is exactly ONE source of truth for the inflation assumption.
2. Every page sees the same value without duplicating the widget.
3. Changing inflation on ANY page (via the sidebar) instantly propagates
   to ALL pages because it writes to `household_data["inflation_rate"]`.

DESIGN DECISIONS
================

* **No auto-save to disk**: the sidebar slider writes to the in-memory
  `household_data` dict only. The next time any page's Save button is
  clicked, the sidebar value is persisted along with the page's own
  fields. This avoids spurious disk writes on every slider nudge.

* **Idempotent write**: every call to `render_global_controls_sidebar()`
  writes `data["inflation_rate"] = slider_value / 100`. The slider's
  Streamlit key preserves state across reruns, and the write is
  idempotent (calling it N times produces the same `data` dict), so
  there's no harm in calling it from every page.

* **Distinct Streamlit key**: `"global_inflation_rate"` — intentionally
  different from the three old page-specific keys (`"inflation_rate"`,
  `"inflation_rate_assets"`, `"qe_inflation_rate"`) to avoid widget-key
  collisions with stale session_state entries from old page visits.

USAGE
=====

In every page file AND `main.py`, add near the top:

    from pages_helpers.global_controls import render_global_controls_sidebar
    render_global_controls_sidebar()

The Pages-side inflation sliders have been REMOVED from Pensions (2),
Assets (3), and Quick Estimate (0) — they now all share this one
sidebar widget.
"""
from __future__ import annotations

import streamlit as st


_INFLATION_KEY: str = "global_inflation_rate"


def render_global_controls_sidebar() -> float:
    """Render the global inflation slider in the sidebar and return the
    current inflation rate as a decimal (e.g. 0.025 for 2.5%).

    Behaviour contract:

    * Reads the default slider position from
      `household_data["inflation_rate"]` (default 2.5%).
    * Writes the slider value / 100 to `household_data["inflation_rate"]`
      on EVERY render (idempotent).
    * Does NOT call `save_household(...)` — the page that triggered the
      rerun (via its own Save button) handles persistence.
    * Returns the decimal rate so callers that compute pre-render
      values (e.g. `_qe_sync_data`'s closure) can reference it without
      a second `data.get(...)` lookup.

    The slider is rendered INSIDE `st.sidebar` so it appears in the
    global-controls block on every page, keeping the page body clean.
    """
    data = st.session_state.get("household_data") or {}
    current_pct = float(data.get("inflation_rate", 0.025)) * 100.0

    with st.sidebar:
        st.markdown("---")
        st.caption("⚙️ **Global controls**")
        slider_pct = st.slider(
            "Inflation assumption (% per year)",
            min_value=0.0,
            max_value=10.0,
            value=current_pct,
            step=0.1,
            key=_INFLATION_KEY,
            help=(
                "Annual inflation used as the deflator for today's-value "
                "projections AND as the baseline uplift for Inflation-adjusted "
                "/ Tapered spending strategies. Default 2.5% (UK CPI target). "
                "Changing this affects ALL pages — no need to re-enter it on "
                "Pensions / Assets / Quick Estimate."
            ),
        )
        decimal_rate = slider_pct / 100.0

        # Idempotent write — same value every render until the user
        # moves the slider. No `save_household(...)` here; the
        # page-level Save buttons handle disk persistence.
        data["inflation_rate"] = decimal_rate

    return decimal_rate


__all__ = [
    "render_global_controls_sidebar",
]
