from dataclasses import dataclass


@dataclass
class LifeEvent:
    year: int
    description: str
    amount: float  # positive = money in, negative = money out


@dataclass
class DownsizingEvent:
    year: int
    sell_property_value: float
    new_property_value: float
    description: str = "Downsizing"


# -------------------------------------------------------
# Pure helpers used by the Streamlit life-events page.
# -------------------------------------------------------
# Events are persisted as plain dicts in `household_data.json`. The engine
# (`simulation/engine.py`) duck-types them via `hasattr(event, "amount")`
# (one-off cash event) vs `hasattr(event, "sell_property_value")` (downsizing
# event). Mirroring that classification here in a pure helper:
#   * lets the UI render both kinds without crashing on `KeyError`,
#   * drops the need to re-list the discriminating keys in every page that
#     wants to display events,
#   * makes the rule unit-testable without importing Streamlit.
EVENT_KIND_CASH = "cash"
EVENT_KIND_DOWNSIZE = "downsize"


def event_kind(event):
    """Classify an event dict by key presence, mirroring the engine's
    duck-typing. Returns ``"downsize"`` if the dict has a
    ``sell_property_value`` key, ``"cash"`` if it has an ``amount`` key,
    ``None`` for anything else (non-dict, or a dict missing both keys —
    which would be malformed and should not be rendered).
    """
    if not isinstance(event, dict):
        return None
    if "sell_property_value" in event:
        return EVENT_KIND_DOWNSIZE
    if "amount" in event:
        return EVENT_KIND_CASH
    return None


def format_event_summary(event):
    """Render an event dict as a single-line Markdown summary string.

    Cash event (inflow):  ``1. Year +10 — 💰 +£25,000 (inflow) — Inheritance``
    Cash event (outflow): ``1. Year +10 — 💸 −£5,000 (outflow) — Gift to children``
    Cash event (£0):      ``1. Year +10 — £0 — Memo``              (no direction)
    Downsizing event:     ``1. Year +10 — 🏠 Downsizing (sell £400,000 → buy £250,000) — Description``

    The sign in the source dict drives the direction label so the
    Streamlit page (and any other consumer) can see at a glance whether
    the event adds to or subtracts from Cash, without having to read the
    signed amount itself.

    Returns ``None`` if ``event`` is not a dict or has neither expected
    key, so the caller can defensively hide the row instead of crashing.
    Every dict-not-found access uses ``.get(key, default)`` so a legacy
    event with only ``year`` (e.g. partial migration) still renders
    rather than raising ``KeyError``.
    """
    if not isinstance(event, dict):
        return None
    kind = event_kind(event)
    if kind is None:
        return None

    # Event index is filled in by the caller (the Streamlit page numbers
    # events 1-indexed), so we leave that out and let the caller prepend
    # it. Everything else is owned here.
    year = event.get("year", "?")
    desc = event.get("description") or ""

    if kind == EVENT_KIND_DOWNSIZE:
        sell = event.get("sell_property_value", 0)
        new = event.get("new_property_value", 0)
        return (
            f"Year +{year} — 🏠 Downsizing "
            f"(sell £{sell:,} → buy £{new:,}) — {desc or 'Downsizing'}"
        )

    # EVENT_KIND_CASH — sign disambiguates inflow vs outflow so the
    # viewer doesn't have to read the signed £ figure to see the
    # direction. Magnitude is shown absolute (£abs), with the literal
    # +/− unicode sign on the front so copy-pasting the row still
    # preserves the saved shape (e.g. "+£25,000" vs "−£5,000").
    # `:,.0f` rounds fractional amounts (rare today, but the
    # type-preserving default on the page already preserves them) to
    # whole pounds so the visible shape stays "£25,000" not
    # "£25,000.0".
    amount = event.get("amount", 0)
    if amount > 0:
        return f"Year +{year} — 💰 +£{amount:,.0f} (inflow) — {desc}"
    if amount < 0:
        return f"Year +{year} — 💸 −£{abs(amount):,.0f} (outflow) — {desc}"
    # £0 — neither inflow nor outflow; just a memo row. Without the
    # explicit direction marker the helper matches the historical
    # rendered shape (`Year +5 — £0 — Note`) so legacy-zero entries
    # don't suddenly display a misleading direction tag.
    return f"Year +{year} — £{amount:,.0f} — {desc}"