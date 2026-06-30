import streamlit as st

from models.events import (
    EVENT_KIND_CASH,
    event_kind,
    format_event_summary,
)
from storage import init_household, save_household

st.title("📅 Life Events")

# ----------------------------------------
# 1. Initialise session_state — seed from disk on first visit
# ----------------------------------------
init_household(st.session_state)

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
    0,
    50,
    last_event.get("year", 0),
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
    # The default preserves the original numeric type from the saved
    # event (int vs float) — coercing to `int` would silently truncate
    # fractional amounts if any future change ever stores decimals.
    if last_kind == EVENT_KIND_CASH and isinstance(last_amount, (int, float)):
        amount_default = abs(last_amount)
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
    sell_default = (
        last_event.get("sell_property_value", 0)
        if last_kind != EVENT_KIND_CASH
        else 0
    )
    new_default = (
        last_event.get("new_property_value", 0)
        if last_kind != EVENT_KIND_CASH
        else 0
    )
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
