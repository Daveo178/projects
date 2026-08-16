"""In-memory plan store + JSON export/import for the hosted planner.

WHY NO LOCAL FILES
==================
The original implementation persisted the plan to `household_data.json`
on local disk. That works for a single user running the app on their own
machine, but on Streamlit Community Cloud it is broken in two ways:

1. The container filesystem is EPHEMERAL — it is wiped whenever the app
   sleeps, restarts, or redeploys, so "saved" plans silently disappear.
2. It is SHARED — every visitor to the app hits the same container and
   the same file, so one visitor's save overwrites another visitor's
   plan (a privacy leak, not persistence).

So the app now keeps each visitor's plan purely in their own Streamlit
`session_state` (in-memory, isolated per browser tab), and exposes
`plan_to_json` / `plan_from_json` so users can download and re-upload
their plan themselves.

The `save_household` / `has_saved_plan` names are retained as thin
compatibility shims so the existing page call-sites keep working without
a rename churn. `init_household` seeds the in-memory dict instead of
reading a file. `load_household` / `delete_household` are gone entirely
(they only touched disk and have no remaining callers).
"""
from __future__ import annotations

import json
from typing import Any, Dict

# Key in `st.session_state` that holds the in-memory plan dict.
STATE_KEY = "household_data"


def init_household(state: Dict[str, Any]) -> None:
    """Seed the in-memory plan on the first access of a browser session.

    Streamlit reruns each page script on every interaction and preserves
    `session_state` across page navigations within a single browser tab,
    so we only initialise the dict once — after that the in-memory dict
    is the source of truth for the session.
    """
    if STATE_KEY not in state:
        state[STATE_KEY] = {}


def save_household(data: Dict[str, Any]) -> bool:
    """Compatibility shim — always succeeds.

    The plan already lives in `st.session_state.household_data`; every
    page mutates that dict in place, so there is nothing extra to write.
    Returns True so existing `if ok:` save-confirmation paths keep
    working unchanged.
    """
    return True


def has_saved_plan(state: Dict[str, Any]) -> bool:
    """True when the session already has a non-empty in-memory plan."""
    return bool(state.get(STATE_KEY))


def plan_to_json(data: Dict[str, Any]) -> str:
    """Serialize the plan dict for the browser download button."""
    return json.dumps(data, indent=2, default=str)


def plan_from_json(text: str) -> Dict[str, Any]:
    """Parse an uploaded plan JSON string into a dict.

    Raises ValueError on malformed JSON or a non-dict payload so the
    page can surface an error instead of corrupting `session_state`.
    """
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Uploaded file is not a valid plan object.")
    return data
