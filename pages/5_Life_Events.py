import streamlit as st

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
last_event = events[-1] if events else {}

event_year = st.number_input(
    "Years from now",
    0,
    50,
    last_event.get("year", 0)
)

event_amount = st.number_input(
    "Amount (£)",
    -1_000_000,
    1_000_000,
    last_event.get("amount", 0)
)

event_desc = st.text_input(
    "Description",
    last_event.get("description", "")
)

# ----------------------------------------
# 3. Add Event Button
# ----------------------------------------
if st.button("Add Event"):
    events.append({
        "year": event_year,
        "amount": event_amount,
        "description": event_desc
    })

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
        st.write(f"**{i+1}. Year +{ev['year']} — £{ev['amount']:,} — {ev['description']}**")

    # Optional delete button
    delete_index = st.number_input(
        "Delete event number",
        1,
        len(events),
        1
    )

    if st.button("Delete Event"):
        removed = events.pop(delete_index - 1)
        save_household(st.session_state.household_data)
        st.warning(f"Deleted event: {removed['description']}")
