"""Shared `personal + employer` pension contribution widget block.

Used by **two pages** so the UX, soft-migration logic, and engine
contract stay in sync:

  1. `pages/0_Quick_Estimate.py`  — the Aviva-style landing page
  2. `pages/2_Pensions.py`      — the detailed Pensions page

The widget renders for ONE partner:

  * a horizontal radio with two modes:
      - "% of income"
      - "Flat £ per month"
  * one of two widgets below the radio (slider in % mode,
    number_input in flat mode), with the inactive mode's hidden
    value forced to 0 so the engine's `% > £` precedence picks
    cleanly.
  * an "Employer contribution (% of income)" slider.

Returns
-------
4-tuple `(personal_pct, personal_flat_monthly, employer_pct, touched)`:
- `personal_pct`     — user-entered % (decimal, e.g. `0.05`).
                       Zero when the user is in the flat-£ mode.
- `personal_flat_monthly` — user-entered flat £/month. Zero in
                            % mode.
- `employer_pct`     — user-entered % as decimal. Zero when no
                       employer contribution set.
- `touched`          — `True` once the user has interacted with
                       ANY widget in this partner's contribution
                       block (radio mode flip, slider drag, or
                       flat-£ edit). Used by the save block to
                       decide whether to wipe or preserve legacy
                       fields — see `resolve_legacy_after_save`
                       and the module docstring below for the
                       semantics.

The touched flag is the **explicit-zero BC fix**. A legacy user
with `monthly_contrib_pct=0.15` lands on the page with the
slider auto-migrated to 15%. If they EXPLICITLY drag the slider
to 0% intending to wipe their contribution, `touched=True` so
the save block recognises the intent and zeroes legacy. If they
don't touch the slider at all, `touched=False` and the migration
value (15%) is treated as a confirmation — legacy preserved.

Soft-migration from legacy fields
--------------------------------
If the saved dict has the new fields all zero but the LEGACY
`monthly_contrib_pct` or `monthly_contrib` non-zero, the helper
pre-fills the form with the legacy values so the user lands on
the page seeing what their plan was actually doing.

FP-drift guard
--------------
All "is this field > 0?" checks use `round(value, 6) > 0` rather
than raw `> 0` so a stored value like `1e-9` from slider
arithmetic doesn't accidentally flip a radio mode or take the
legacy-migration branch.
"""
from __future__ import annotations

import streamlit as st


def _touched_key(key_prefix: str) -> str:
    """Session-state key for the per-partner touched flag.

    Prefixed with an underscore so it never collides with a
    widget-key `${prefix}_*` (Streamlit requires widget keys to
    be unique within a render), and is also visually distinct as
    our own metadata rather than a widget.
    """
    return f"_{key_prefix}_user_touched"


def _mark_touched(key_prefix: str) -> None:
    """Streamlit `on_change` callback for every widget we render.

    Fires whenever the user interacts with any widget on the
    partner's contribution block (radio mode flip, personal %
    slider, personal flat-£ input, or employer % slider). Sets
    the touched flag in `session_state` so the save block can
    consult it after the helper returns.

    `on_change` is Set on every widget, so the same flag is
    raised whether the user drag-drags the slider, types in the
    flat-£ field, or switches the radio mode. Without firing on
    the radio, a user who only switches modes wouldn't trigger
    the touched flag — but switching modes implicitly zeroes the
    inactive field, which is a meaningful interaction.
    """
    st.session_state[_touched_key(key_prefix)] = True


def resolve_legacy_after_save(
    personal_pct: float,
    personal_flat: float,
    employer_pct: float,
    user_touched: bool,
    saved_legacy_pct: float,
    saved_legacy_flat: float,
) -> tuple[float, float]:
    """Pure helper to make the BC decision for one partner after
    `render_personal_employer_contrib_block` returns.

    Decision rules (deterministic, unit-tested in
    `tests/test_contrib_split.py::TestResolveLegacyAfterSave`):

      1. If ANY new contribution field is non-zero (after FP-drift
         rounding), the engine will use the new fields via
         precedence — write new fields AND zero legacy so a
         future refactor / audit doesn't accidentally double-
         count both representations.

      2. If all new fields are zero BUT `user_touched` is True
         (user interacted with the form, possibly dragging
         values down to 0), the user has expressed an explicit
         intent to wipe the contribution — zero legacy too.

      3. If all new fields are zero AND `user_touched` is False
         (untouched migrated-from-legacy state — soft-migration
         in `_render_contrib_block` already wrote a non-zero
         value into the new field, but if the user didn't take
         that route the new fields truly are zero), preserve
         the saved legacy values. This prevents a silent BC
         regression for a legacy user who opens either page but
         doesn't touch any widget.

    Returns:
        `(legacy_pct, legacy_flat)` to write into
        `data["personN"]["monthly_contrib_pct"]` /
        `data["personN"]["monthly_contrib"]`.
    """
    any_new = (
        round(personal_pct, 6) > 0
        or round(personal_flat, 6) > 0
        or round(employer_pct, 6) > 0
    )
    if any_new or user_touched:
        return 0.0, 0.0
    return float(saved_legacy_pct), float(saved_legacy_flat)


def render_personal_employer_contrib_block(
    key_prefix: str,
    saved: dict,
) -> tuple[float, float, float, bool]:
    """Render the per-partner personal + employer contribution UI.

    Args:
        key_prefix: Streamlit widget-key prefix used to disambiguate
            rendering for Person 1 vs Person 2 (e.g. `"qe_p1"`, `"qe_p2"`,
            `"d"`, `"s"`). MUST be unique per-partner-per-page or
            Streamlit raises `StreamlitDuplicateWidgetKey` on render.
        saved: the per-partner saved dict (model fields + legacy
            fields). Reads:
              * `personal_contrib_pct` (new)
              * `personal_contrib_flat_monthly` (new)
              * `employer_contrib_pct` (new)
              * `monthly_contrib_pct` (legacy combined %)
              * `monthly_contrib` (legacy flat £/month)

    Returns:
        `(personal_pct, personal_flat_monthly, employer_pct, touched)`
        as described in the module docstring. Inactive mode's value
        is forced to 0.0 so engine / AA helpers see clean precedence
        resolution. `touched` is sticky within a session — once set
        it stays True for the rest of the session so a user who
        briefly touched and then un-touched still counts as
        "explicit" for the save-BC decision.
    """
    pct_saved = float(saved.get("personal_contrib_pct", 0.0))
    flat_saved = float(saved.get("personal_contrib_flat_monthly", 0.0))
    legacy_pct = float(saved.get("monthly_contrib_pct", 0.0))
    legacy_flat = float(saved.get("monthly_contrib", 0.0))

    has_new = (
        round(pct_saved, 6) > 0 or round(flat_saved, 6) > 0
    )
    if has_new:
        default_mode_index = (
            0 if round(pct_saved, 6) > 0 else 1
        )
        initial_pct_ui = pct_saved * 100.0
        initial_flat_ui = flat_saved
        initial_employer_ui = (
            float(saved.get("employer_contrib_pct", 0.0)) * 100.0
        )
    elif round(legacy_pct, 6) > 0:
        default_mode_index = 0
        initial_pct_ui = legacy_pct * 100.0
        initial_flat_ui = 0.0
        initial_employer_ui = 0.0  # legacy didn't track employer
    elif round(legacy_flat, 6) > 0:
        default_mode_index = 1
        initial_pct_ui = 0.0
        initial_flat_ui = legacy_flat
        initial_employer_ui = 0.0
    else:
        default_mode_index = 0
        initial_pct_ui = 0.0
        initial_flat_ui = 0.0
        initial_employer_ui = 0.0

    contrib_mode = st.radio(
        "Personal contribution",
        ["% of income", "Flat £ per month"],
        index=default_mode_index,
        horizontal=True,
        key=f"{key_prefix}_contrib_mode",
        on_change=_mark_touched,
        args=(key_prefix,),
        help=(
            "Pick how you want to express your personal (employee) "
            "pension contribution. % of income is the usual case; "
            "Flat £ per month is convenient for self-employed or "
            "irregular-income contributors."
        ),
    )

    if contrib_mode == "% of income":
        personal_pct = st.slider(
            "Your contribution (% of income)",
            min_value=0.0,
            max_value=50.0,
            value=float(initial_pct_ui),
            step=0.5,
            key=f"{key_prefix}_personal_pct",
            on_change=_mark_touched,
            args=(key_prefix,),
            help=(
                "Your personal (employee) pension contribution as a "
                "percentage of annual income. The engine applies this "
                "to your wage-inflation-indexed income each year."
            ),
        ) / 100
        personal_flat = 0.0
    else:
        personal_flat = st.number_input(
            "Your contribution (£ / month)",
            min_value=0.0,
            max_value=5_000.0,
            value=float(initial_flat_ui),
            step=10.0,
            key=f"{key_prefix}_personal_flat",
            on_change=_mark_touched,
            args=(key_prefix,),
            help=(
                "Flat personal (employee) pension contribution per "
                "month, in today's pounds. Useful when your "
                "contribution isn't a clean % of salary."
            ),
        )
        personal_pct = 0.0

    employer_pct = st.slider(
        "Employer contribution (% of income)",
        min_value=0.0,
        max_value=25.0,
        value=float(initial_employer_ui),
        step=0.5,
        key=f"{key_prefix}_employer_pct",
        on_change=_mark_touched,
        args=(key_prefix,),
        help=(
            "Employer pension contribution as a percentage of your "
            "annual income. 3% is a typical UK private-sector "
            "minimum-match baseline."
        ),
    ) / 100

    touched = bool(st.session_state.get(_touched_key(key_prefix), False))
    return personal_pct, personal_flat, employer_pct, touched
