import streamlit as st
from brand_chrome import apply_chrome

from models.events import (
    EVENT_KIND_CASH,
    event_kind,
    format_event_summary,
)
from storage import init_household, save_household
from pages_helpers.global_controls import render_global_controls_sidebar

# ----------------------------------------
# Initialise session_state + apply brand chrome (stylesheet
# injection — LIGHT palette only, since the dark-mode radio was
# dropped) BEFORE the page's <st.title>...</st.title> so the
# stylesheet is in place before the title paints. Same pattern
# as pages 2 / 4 / 6 / etc. — `init_household -> apply_chrome ->
# title` so we never flash native Streamlit chrome on the title
# element before the brand stylesheet injects.
# ----------------------------------------
init_household(st.session_state)
apply_chrome()
render_global_controls_sidebar()

st.title("📅 Life Events")

# Ensure events list exists
if "events" not in st.session_state.household_data:
    st.session_state.household_data["events"] = []


events = st.session_state.household_data["events"]


# ----------------------------------------
# 2. Inputs (pre-filled with last used values)
# ----------------------------------------
# Three event shapes are supported through the form:
#   * "One-off cash event — inflow"  — money INTO the household
#     (inheritance, gift received, lump-sum windfall). Stored as
#     `{"amount": +N}`, the engine adds it to the Cash asset.
#   * "One-off cash event — outflow" — money OUT of the household
#     (large purchase, gift given, school fees). Stored as
#     `{"amount": -N}`, the engine subtracts it from the Cash asset.
#     The engine already supports signed amounts via
#     `asset.value += event.amount` in simulation/engine.py; this just
#     makes the sign explicit in the UI so the user never has to type
#     a literal `-` and can't forget it on the wrong row.
#   * "Downsizing event"             — sell_property_value +
#     new_property_value; swaps Property, drops sale proceeds into
#     Cash, clears mortgage. Engine branches on
#     `hasattr(event, "sell_property_value")`.
# Classification lives next to the dataclasses in models.events.

last_event = events[-1] if events else {}
last_kind = event_kind(last_event) or EVENT_KIND_CASH  # safe default for empty legacy data

event_kind_label = st.selectbox(
    "Event type",
    ("One-off cash event", "Downsizing event"),
    index=0 if last_kind == EVENT_KIND_CASH else 1,
)
is_cash = event_kind_label == "One-off cash event"

# Year is shared by all event kinds.
event_year = st.number_input(
    "Years from now",
    0.0,
    50.0,
    float(last_event.get("year", 0)),
)

if is_cash:
    # ----------------------------------------------------------
    # Direction selector — separates the sign from the magnitude
    # ----------------------------------------------------------
    # We default the selector to whatever sign the most-recent saved
    # cash event had (positive ⇒ inflow, negative ⇒ outflow), so
    # editing an existing row keeps its direction. If the last event
    # is a downsizing row, fall back to inflow (a safe default for a
    # brand-new cash event in the common case "I'm adding money").
    last_amount = (
        last_event.get("amount", 0)
        if last_kind == EVENT_KIND_CASH
        else 0
    )
    INFLOW_LABEL  = "💰 Cash inflow — money INTO the household"
    OUTFLOW_LABEL = "💸 Cash outflow — money OUT of the household"
    CASH_DIRECTION_OPTIONS = (INFLOW_LABEL, OUTFLOW_LABEL)
    cash_direction_label = st.selectbox(
        "Direction",
        CASH_DIRECTION_OPTIONS,
        index=0 if last_amount >= 0 else 1,
        help=(
            "Inflow hits the Cash asset as +£N (e.g. inheritance, gift received). "
            "Outflow hits the Cash asset as -£N (e.g. large purchase, gift given). "
            "The sign is applied automatically so you enter a positive magnitude below."
        ),
    )
    # Index-based comparison (not label-string equality) so a future
    # edit to either label's wording doesn't silently flip the saved
    # sign on every event. `tuple.index` returns 0 for the inflow
    # tuple-element and 1 for the outflow element by construction.
    is_inflow = CASH_DIRECTION_OPTIONS.index(cash_direction_label) == 0

    # Amount is always entered as a POSITIVE magnitude; the page picks
    # the sign at save time. This prevents the easy mistake of typing
    # `25000` for an outflow (engine would silently treat it as inflow).
    #
    # The `int(...)` cast keeps the default int-typed so it matches the
    # surrounding `number_input`'s int `min_value=0` / `max_value=1_000_000`
    # / `step=100` — Streamlit raises `StreamlitMixedNumericTypesError`
    # if any numeric arg differs in type. Without the cast, a fractional
    # saved amount would round-trip back as float and crash the form
    # on re-open. Truncation is benign for two reasons: (a) `step=100`
    # already nudges users toward whole-pound amounts, and (b) the
    # int-fallback `0` below is plain int (no cast needed — don't
    # cargo-cult `int()` onto it). If a user ever saves a fractional
    # amount to JSON, the next "Save Event" click silently overwrites
    # it with the truncated whole-pound value — acceptable for money
    # in this app, but worth knowing.
    if last_kind == EVENT_KIND_CASH and isinstance(last_amount, (int, float)):
        amount_default = int(abs(last_amount))
    else:
        amount_default = 0
    event_amount_abs = st.number_input(
        "Amount (£) — magnitude",
        min_value=0,
        max_value=1_000_000,
        value=amount_default,
        step=100,
    )
    event_amount = event_amount_abs if is_inflow else -event_amount_abs
    # Live sign-preview so the user sees the saved shape before click.
    # Suppressed when the magnitude is zero — otherwise the caption would
    # claim "amount = +0 (inflow)" which is misleading (the engine reads
    # 0 the same way regardless of sign).
    if event_amount_abs == 0:
        st.caption(
            "Sign is auto-applied based on direction; "
            "an amount of £0 has no impact either way."
        )
    else:
        # `:+.0f` (instead of `:d`) lets the preview render floats AND
        # ints cleanly. `:d` would raise `ValueError: Unknown format
        # code 'd' for object of type 'float'` if a fractional saved
        # amount ever round-trips through here — the type-preserving
        # default above makes that case possible.
        st.caption(
            f"This will be saved as `amount = {event_amount:+.0f}` "
            f"(sign {'inflow (+)' if is_inflow else 'outflow (−)'})."
        )
else:
    # Downsizing — sell the current home at this value, buy the new one
    # at this value; the difference lands in Cash and any outstanding
    # mortgage balance is cleared (side effects handled in
    # simulation/engine.py).
    # After deleting pages/9_Downsizing.py (its dedicated form used
    # 400k/250k pre-fills for first-time users), Page 5 became the
    # sole downsizing surface. Re-apply those pre-fills here for the
    # truly-first-time branch ONLY (no prior downsizing event in
    # `last_event`) so a brand-new user opening the downsizing
    # kind-toggle sees a sensible starting point instead of `0 / 0`.
    #
    # Belt-and-suspenders gate: keyed on the DICT itself
    # (`isinstance(last_event, dict) and "sell_property_value" in
    # last_event`) rather than on the derived `last_kind` label.
    # `last_kind` is computed two lines above via
    # `last_kind = event_kind(last_event) or EVENT_KIND_CASH` — if
    # `event_kind()` ever evolves to raise on a malformed shape, or
    # the `or EVENT_KIND_CASH` fallback mis-classifies a corrupt
    # downsizing dict, the kind-label gate would silently route to
    # the pre-fill branch and overwrite the user's real saved
    # £-amounts back to 400k / 250k. Inspecting the dict directly
    # avoids that whole failure mode: any dict that ACTUALLY carries
    # a `sell_property_value` key is treated as a real downsizing
    # entry no matter what `event_kind` thinks of it. Conversely,
    # the pre-fill branch only fires when the dict does NOT carry
    # the downsizing discriminator — i.e. truly first-time.
    if isinstance(last_event, dict) and "sell_property_value" in last_event:
        # Real downsizing dict present — read the exact saved values
        # (including legitimate 0). Bypasses any downstream mutation
        # of `last_kind`.
        sell_default = last_event.get("sell_property_value", 0)
        new_default = last_event.get("new_property_value", 0)
    else:
        # First-time downsizing branch (no events yet, last event is
        # cash, last event is malformed, or last_event is not a dict
        # at all): back-fill the legacy Page 9 pre-fills.
        sell_default = 400_000
        new_default = 250_000
    event_sell_value = st.number_input(
        "Sell property for (£)",
        0,
        5_000_000,
        sell_default,
    )
    event_new_value = st.number_input(
        "New property value (£)",
        0,
        5_000_000,
        new_default,
    )

event_desc = st.text_input(
    "Description",
    last_event.get("description", ""),
)

# ----------------------------------------
# 3. Add Event Button
# ----------------------------------------
if st.button("Add Event"):
    if is_cash:
        # Signed `amount` — positive = inflow, negative = outflow.
        # The engine picks this up via `attr += event.amount` on the
        # Cash asset; the direction selector above picks the sign at
        # save time.
        events.append(
            {
                "year": event_year,
                "amount": event_amount,
                "description": event_desc,
            }
        )
    else:
        events.append(
            {
                "year": event_year,
                "sell_property_value": event_sell_value,
                "new_property_value": event_new_value,
                "description": event_desc or "Downsizing",
            }
        )

    save_household(st.session_state.household_data)
    st.success("Event added!")

# ----------------------------------------
# 4. Display Existing Events
# ----------------------------------------
st.subheader("📋 Saved Events")

if len(events) == 0:
    st.info("No events added yet.")
else:
    for i, ev in enumerate(events):
        # `format_event_summary` returns None for malformed entries (non-dict
        # or missing both discriminating keys) so the page silently skips a
        # row rather than crashing — defensive against partial migrations.
        # For cash events the helper also prefixes the sign (`+£N (inflow)` /
        # `−£N (outflow)`) so the direction is visually obvious in the list.
        summary = format_event_summary(ev)
        if summary is None:
            st.warning(f"⚠️ Event #{i+1} is malformed and can't be displayed.")
            continue
        st.write(f"**{i+1}. {summary}**")

    # Optional delete button
    delete_index = st.number_input(
        "Delete event number",
        1,
        len(events),
        1,
    )

    if st.button("Delete Event"):
        removed = events.pop(delete_index - 1)
        save_household(st.session_state.household_data)
        if isinstance(removed, dict):
            st.warning(f"Deleted event: {removed.get('description', '')}")
        else:
            st.warning(f"Deleted event: {removed}")
