from dataclasses import dataclass


@dataclass
class LifeEvent:
    """A single life event (cash one-off OR downsizing — same dataclass).

    Pre-refactor this dataclass held only the one-off-cash shape:
    `LifeEvent(year, description, amount)`. Downsizing lived in a
    SIBLING `DownsizingEvent(year, sell_property_value,
    new_property_value)` dataclass — the two were kept disjoint
    so the engine could duck-type them via attribute presence.

    Post-refactor there is no `DownsizingEvent` anymore. Downsizing is
    a single extra discriminator inside this dataclass: a real cash
    event has `amount != 0` AND (dataclass-default)
    `sell_property_value == 0`; a real downsizing event has
    `sell_property_value > 0` AND (dataclass-default) `amount == 0`.
    The engine classifies via these value-based predicates (see
    `simulation/engine.py`'s step 5) so cash and downsizing remain
    mutually exclusive at the branch level — value predicates are
    coprime because dataclass defaults are 0.0.

    Field-order rule: optional fields with defaults follow the three
    required positionals. This keeps the three-positional constructor
    `LifeEvent(year=Y, description=D, amount=A)` (the historic
    cash-only call shape) exactly equivalent to before, and lets a
    JSON-style `LifeEvent(**d)` round-trip find `sell_property_value`
    / `new_property_value` as keywords on downsizing dicts (where
    `pages/5_Life_Events.py`'s downsizing branch saves them) and
    silently default to 0.0 on cash dicts (where those keys are
    absent).

    `description` is intentionally a required positional (no default) —
    every UI save path in `pages/5_Life_Events.py` includes a
    description (real text or empty string), and a missing description
    would render as an opaque memo row in `triggered` lists.
    """
    year: int
    # Default `"Downsizing"` preserves pre-refactor `DownsizingEvent`'s
    # default behaviour: a saved downsizing dict that happens to be
    # missing a `description` key still round-trips cleanly with the
    # sentinel value rather than crashing on missing-positional. Page 5
    # always writes a description in practice, so this default only
    # matters for hand-edited or migrated JSON. For a CASH one-off the
    # saved dict carries a real description so the default is never
    # observed.
    description: str = "Downsizing"
    # Positive = money in, negative = money out. Defaults to 0.0 so
    # `LifeEvent(**downsize_dict)` round-trips a downsizing dict (which
    # has no `amount` key) without raising.
    amount: float = 0.0
    sell_property_value: float = 0.0
    new_property_value: float = 0.0


# -------------------------------------------------------
# Pure helpers used by the Streamlit life-events page.
# -------------------------------------------------------
# Events are persisted as plain dicts in `household_data.json`. The
# engine (`simulation/engine.py`) classifies an in-memory `LifeEvent`
# via value-based predicates (`event.sell_property_value > 0` for
# downsizing; `event.amount != 0` else for cash; appended description
# for memos). The page-side helpers below operate on the DICT shape
# the page commits to JSON — so the UI can render a saved or
# in-progress event without first rebuilding a `LifeEvent` instance.

# The dict-shape and dataclass-shape predicates agree because:
#   * a downsizing dict has `sell_property_value` set AND no
#     `amount` key. After `LifeEvent(**d)` the resulting object has
#     `amount == 0.0` (default) and `sell_property_value == <real>`,
#     satisfying the engine's `sell_property_value > 0` gate.
#   * a cash dict has `amount` set AND no `sell_property_value` key.
#     After `LifeEvent(**d)` the object has
#     `sell_property_value == 0.0` (default) and `amount == <real>`,
#     falling through to the cash-or-memo branch.
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