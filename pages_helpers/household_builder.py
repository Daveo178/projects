"""Shared household-building helpers for engine-driving pages.

Centralises the `Household(...)` dataclass construction that the
Home page (Page 1), Timeline (Page 11, post-toggle re-run), and any
future engine-driving page need. Lifted out of the inline
`_build_household_from_session_state()` function that used to live
in `pages/1_Home.py` so:

  * All pages that need to RE-RUN `simulation_results` when a session-state
    field changes (today's-value toggle, future global plan-mode toggles,
    etc.) can rebuild the dataclass without duplicating the seven-step
    `Person / Asset / Mortgage / LifeEvent / Household` build.

  * The Home page's Run Simulation button and the toggle's
    `on_change` callback BOTH call the same builder, so a future
    refactor of, say, the contribution-mapping logic only has to
    land in one place to keep both code paths consistent.

Notes
-----
* `build_household_from_session_state()` raises `KeyError` when a
  required key (e.g. `"person1"`) is missing in
  `st.session_state.household_data`. Callers are expected to have
  guarded the missing-keys case BEFORE calling this helper (the
  Home page's `required_keys` check + `st.stop()` happens earlier
  in the script). Adding a `None`-fallback here would hide real
  bugs — the page-level guard is the right place to silence them.
* `drawdown_strategy` defaults to "Fixed" when the saved JSON predates
  the dataclass field — symmetric with the original inline helper.
"""

from __future__ import annotations

# `st.session_state.household_data` is read inside
# `build_household_from_session_state` — the module must explicitly
# import streamlit, otherwise the first call to the helper will
# raise `NameError: name 'st' is not defined`. (Pre-fix the module
# relied on `st` being in the caller's globals, which is fragile
# and py_compile-blind because the reference is inside a function
# body, evaluated at call time.) The `# noqa: F821` on the
# `st.session_state` line is a keep-suppress for linters that would
# otherwise flag the reference — but the actual resolution comes
# from THIS import, not a runtime guard.
import streamlit as st

from models.asset import Asset
from models.events import LifeEvent
from models.household import Household
from models.mortgage import Mortgage
from models.person import Person
from pages_helpers.strategy_options import normalize_drawdown_strategy


def build_household_from_session_state(
    show_in_todays_value: Optional[bool] = None,
) -> Household:
    """Build a `Household` dataclass from `st.session_state.household_data`.

    Mirrors the original inline `_build_household_from_session_state`
    in `pages/1_Home.py` — extracted verbatim so any cross-page caller
    (e.g. the Timeline page's re-run-on-toggle path) reconstructs
    the same household dataclass byte-for-byte.

    Parameters
    ----------
    show_in_todays_value : bool, optional
        When set, override the household's `show_in_todays_value` flag
        for this specific build. When `None` (the default), read the
        flag from `st.session_state.household_data["show_in_todays_value"]`
        (defaulting to `False` if missing). The flag propagates to the
        `Household` dataclass field so `simulation.engine.resolve_today_value_settings`
        picks it up; without this, the engine would always see the
        `Household` dataclass default of `False` and the today-value
        mode would silently no-op. Scenarios and What If pass
        `show_in_todays_value=bool(data.get("show_in_todays_value", False))`
        explicitly for the same effective behaviour; Home, Timeline,
        and Monte Carlo rely on the session-state read.

    Required keys (raises `KeyError` if any are missing):
        * `"person1"` — partner-1 dict
        * `"person2"` — partner-2 dict
        * `"assets"`  — list of asset dicts
        * `"spending"` — lifestyle spending £/yr

    Optional keys (silently defaulted):
        * `"mortgage"` — None if missing or `{}`
        * `"events"`  — `[]` if missing
        * `"drawdown_strategy"` — `"Fixed"` if missing
        * `"cash_buffer"` — `False` if missing (the dataclass default)
        * `"single_retiree"` — `False` if missing; when true, all
          Person 2 inputs are retained but excluded from the model
        * `"life_expectancy_end_age"` — `95.0` if missing
        * `"show_in_todays_value"` — `False` if missing (only used
          when the `show_in_todays_value` parameter is `None`)
        * `"inflation_rate"` — `0.025` if missing (engine default)

    Returns
    -------
    Household
        A fully-populated dataclass; `run_simulation(household)` is
        then a single function call away from a `simulation_results`
        dict.
    """
    d = st.session_state.household_data  # noqa: F821 — `st` imported at module top

    if show_in_todays_value is None:
        show_in_todays_value = bool(
            d.get("show_in_todays_value", False)
        )

    p1 = Person(**d["person1"])
    p2 = Person(**d["person2"])

    assets = [Asset(**a) for a in d["assets"]]

    mortgage = None
    if "mortgage" in d and d["mortgage"]:
        mortgage = Mortgage(**d["mortgage"])

    events = []
    if "events" in d:
        events = [LifeEvent(**e) for e in d["events"]]

    return Household(
        person1=p1,
        person2=p2,
        assets=assets,
        mortgage=mortgage,
        spending_target=d["spending"],
        drawdown_strategy=normalize_drawdown_strategy(
            d.get("drawdown_strategy", "Fixed")
        ),
        events=events,
        cash_buffer=bool(d.get("cash_buffer", False)),
        single_retiree=bool(d.get("single_retiree", False)),
        taper_start_age=float(d.get("taper_start_age", 75.0)),
        taper_rate=float(d.get("taper_rate", 0.02)),
        taper_floor_gbp=float(d.get("taper_floor_gbp", 10_000.0)),
        late_life_step_1_age=float(d.get("late_life_step_1_age", 75.0)),
        late_life_step_1_rate=float(d.get("late_life_step_1_rate", 0.0)),
        late_life_step_2_age=float(d.get("late_life_step_2_age", 85.0)),
        late_life_step_2_rate=float(d.get("late_life_step_2_rate", 0.0)),
        gogo_bump_pct=float(d.get("gogo_bump_pct", 0.0)),
        life_expectancy_end_age=float(
            d.get("life_expectancy_end_age", 95.0)
        ),
        drawdown_priority=list(
            d.get("drawdown_priority", ["Pension", "Cash", "ISA", "GIA"])
        ),
        show_in_todays_value=show_in_todays_value,
        inflation_rate=float(d.get("inflation_rate", 0.025)),
    )


__all__ = ["build_household_from_session_state"]
