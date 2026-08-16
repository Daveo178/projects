"""
Regression tests for the pure helpers in `models/events.py`:

  * `event_kind(event)`         — classifies an event dict by key presence
                                  (mirrors the engine's hasattr()-based
                                  duck-typing in `simulation/engine.py`).
  * `format_event_summary(event)` — renders the dict as a single-line
                                  Markdown summary string. After the
                                  direction-toggle UI change on
                                  `pages/5_Life_Events.py`, cash events
                                  MUST prefix their sign (`+£N (inflow)`
                                  vs `−£N (outflow)`) so the viewer
                                  doesn't have to read the signed figure
                                  to see the direction.

The streamlit page in `pages/5_Life_Events.py` consumes these helpers
without crashing on the same dicts — see also the original KeyError
fix, where a downsizing dict (with `sell_property_value` instead of
`amount`) used to crash because the page displayed every event via
`st.write(f"... £{ev['amount']:,} ...")`.
"""

import unittest

from models.events import (
    EVENT_KIND_CASH,
    EVENT_KIND_DOWNSIZE,
    event_kind,
    format_event_summary,
)


class EventKindTests(unittest.TestCase):
    """`event_kind` mirrors `simulation/engine.py`'s hasattr()-based
    classification. If the engine adds a third duck-typed event kind
    we'll need to update both sites; these tests trap any drift."""

    def test_cash_dict_returns_cash_kind(self):
        self.assertEqual(event_kind({"year": 5, "amount": 100}), EVENT_KIND_CASH)

    def test_downsizing_dict_returns_downsize_kind(self):
        self.assertEqual(
            event_kind(
                {
                    "year": 10,
                    "sell_property_value": 400000,
                    "new_property_value": 250000,
                }
            ),
            EVENT_KIND_DOWNSIZE,
        )

    def test_empty_dict_returns_none(self):
        self.assertIsNone(event_kind({}))

    def test_year_only_dict_returns_none(self):
        # Legacy partial-migration entries with only `year` (e.g. cut off
        # mid-save) mustn't crash the page or the engine; classify as None.
        self.assertIsNone(event_kind({"year": 5}))

    def test_non_dict_returns_none(self):
        self.assertIsNone(event_kind("not a dict"))
        self.assertIsNone(event_kind(None))
        self.assertIsNone(event_kind(123))
        self.assertIsNone(event_kind(["year", 5]))
        self.assertIsNone(event_kind(object()))


class FormatEventSummaryCashTests(unittest.TestCase):
    """Sign-aware rendering for one-off cash events. The engine reads
    `asset.value += event.amount` so a positive amount is an inflow and
    a negative amount is an outflow — the helper makes that explicit
    in the visible summary string."""

    def test_positive_amount_renders_inflow(self):
        summary = format_event_summary(
            {"year": 5, "amount": 25000, "description": "Inheritance"}
        )
        self.assertIsNotNone(summary)
        # `Year +5 — ` prefix anchors the row format. A regression
        # that drops or rearranges the prefix (e.g. "Y5", "Year 5")
        # would still pass on `in`-checks below; the startswith
        # locks the prefix shape.
        self.assertTrue(summary.startswith("Year +5 \u2014 "))
        # Sign + magnitude + label must all be present so the row is
        # unambiguous without the user reading the signed figure.
        self.assertIn("+£25,000", summary)
        self.assertIn("(inflow)", summary)
        self.assertIn("Inheritance", summary)
        # No contradictory "outflow" tag on a positive event.
        self.assertNotIn("(outflow)", summary)

    def test_negative_amount_renders_outflow(self):
        summary = format_event_summary(
            {"year": 5, "amount": -5000, "description": "Gift to children"}
        )
        self.assertIsNotNone(summary)
        self.assertTrue(summary.startswith("Year +5 \u2014 "))
        # Negative is rendered with the U+2212 unicode minus so the
        # string reads as a negative figure; magnitude is absolute, so
        # a copy-paste preserves the saved shape.
        self.assertIn("−£5,000", summary)
        self.assertIn("(outflow)", summary)
        self.assertIn("Gift to children", summary)
        self.assertNotIn("(inflow)", summary)

    def test_zero_amount_renders_no_direction_label(self):
        # £0 is neither inflow nor outflow — the engine treats it the
        # same regardless of sign. The helper must NOT prefix a
        # misleading direction tag, otherwise a memo row would falsely
        # advertise itself as moving £.
        summary = format_event_summary(
            {"year": 5, "amount": 0, "description": "Memo"}
        )
        self.assertIsNotNone(summary)
        self.assertTrue(summary.startswith("Year +5 \u2014 "))
        self.assertIn("£0", summary)
        self.assertNotIn("(inflow)", summary)
        self.assertNotIn("(outflow)", summary)

    def test_float_amount_rounds_to_whole_pounds(self):
        # Locks in `:,.0f` rather than `:d` for the cash formatter. If
        # someone reverted to `:d`, this test would crash with
        # `ValueError: Unknown format code 'd' for object of type
        # 'float'` — the exact regression we fixed when adopting the
        # type-preserving `abs(last_amount)` default on the page.
        # Asserts that fractional inputs round to whole pounds (25000.7
        # → "£25,001") and that the raw decimal does NOT leak through.
        summary = format_event_summary(
            {"year": 5, "amount": 25000.7, "description": "Legacy float"}
        )
        self.assertIsNotNone(summary)
        self.assertIn("£25,001", summary)
        self.assertNotIn("£25,000.7", summary)
        self.assertNotIn("£25,000.", summary)
        self.assertIn("(inflow)", summary)

    def test_negative_float_amount_renders_outflow_with_unicode_minus(self):
        # Negative float through `:,.0f` → "−£5,000" (U+2212 unicode
        # minus, magnitude rounded to whole pounds). Locks in that
        # floats round-trip through the helper without crashing.
        summary = format_event_summary(
            {"year": 5, "amount": -5000.4, "description": "Legacy float outflow"}
        )
        self.assertIsNotNone(summary)
        self.assertIn("−£5,000", summary)
        self.assertIn("(outflow)", summary)
        self.assertNotIn("(inflow)", summary)

    def test_cash_event_with_no_description_still_renders(self):
        # Defensive against empty / legacy entries.
        summary = format_event_summary({"year": 5, "amount": 100})
        self.assertIsNotNone(summary)
        self.assertIn("+£100", summary)
        self.assertIn("(inflow)", summary)

    def test_cash_event_with_empty_description_renders_blank(self):
        summary = format_event_summary(
            {"year": 5, "amount": -1, "description": ""}
        )
        self.assertIsNotNone(summary)
        # Trailing em-dash is expected when desc is empty `\u2014` is the
        # em-dash separator, so we just check the figure made it through.
        self.assertIn("−£1", summary)
        self.assertIn("(outflow)", summary)


class FormatEventSummaryDownsizingTests(unittest.TestCase):
    def test_downsizing_with_description_renders(self):
        summary = format_event_summary(
            {
                "year": 10,
                "sell_property_value": 400000,
                "new_property_value": 250000,
                "description": "Moving to flat",
            }
        )
        self.assertIsNotNone(summary)
        self.assertIn("Downsizing", summary)
        self.assertIn("£400,000", summary)
        self.assertIn("£250,000", summary)
        self.assertIn("Moving to flat", summary)

    def test_downsizing_without_description_uses_default_label(self):
        # Mirrors the `DownsizingEvent` dataclass default
        # `description: str = "Downsizing"` — empty `description` should
        # not blow up the renderer.
        summary = format_event_summary(
            {
                "year": 10,
                "sell_property_value": 400000,
                "new_property_value": 250000,
            }
        )
        self.assertIsNotNone(summary)
        self.assertIn("Downsizing", summary)

    def test_downsizing_missing_values_fall_back_to_zero(self):
        # Partial entries (only `year` + `sell_property_value`, missing
        # `new_property_value`) should not raise KeyError.
        summary = format_event_summary(
            {"year": 10, "sell_property_value": 400000}
        )
        self.assertIsNotNone(summary)
        self.assertIn("£400,000", summary)
        self.assertIn("£0", summary)


class FormatEventSummaryMalformedTests(unittest.TestCase):
    """Same defensive shape as the page's display loop — the helper
    returns `None` for unclassifiable entries so the caller can skip
    the row rather than crash."""

    def test_non_dict_returns_none(self):
        self.assertIsNone(format_event_summary("not a dict"))
        self.assertIsNone(format_event_summary(None))
        self.assertIsNone(format_event_summary(42))

    def test_year_only_returns_none(self):
        # No `amount` and no `sell_property_value` key → can't render
        # anything meaningful for either kind.
        self.assertIsNone(format_event_summary({"year": 5}))

    def test_empty_dict_returns_none(self):
        self.assertIsNone(format_event_summary({}))


if __name__ == "__main__":
    unittest.main()


class TestLifeEventDataclass(unittest.TestCase):
    """`LifeEvent` is the SINGLE event dataclass post-refactor (cash
    one-offs AND downsizing — distinguished by `sell_property_value > 0`
    inside the engine rather than by separate sibling dataclasses).
    These tests lock in the round-trip behaviour that pages 1/5/6/8/13
    rely on: a dict-saving JSON shape unwrapped via `**` should
    instantiate cleanly as a `LifeEvent` regardless of which kind
    the dict is, and the engine's value-based predicates should
    correctly classify each shape.
    """

    def test_cash_dict_round_trip(self):
        from models.events import LifeEvent
        ev = LifeEvent(
            **{"year": 5, "amount": 25000, "description": "Inheritance"}
        )
        # Cash shape — `amount` set; downsizing fields fill from the
        # dataclass `= 0.0` defaults because the dict didn't carry them.
        self.assertEqual(ev.year, 5)
        self.assertEqual(ev.description, "Inheritance")
        self.assertEqual(ev.amount, 25000)
        self.assertEqual(ev.sell_property_value, 0.0)
        self.assertEqual(ev.new_property_value, 0.0)
        # Lock the engine's value-based dispatch predicate. A cash
        # event (sell=0) skips the downsizing branch.
        self.assertFalse(ev.sell_property_value > 0)
        self.assertNotEqual(ev.amount, 0)

    def test_downsizing_dict_round_trip(self):
        from models.events import LifeEvent
        ev = LifeEvent(
            **{
                "year": 10,
                "sell_property_value": 400000,
                "new_property_value": 250000,
                "description": "Downsizing",
            }
        )
        # Downsizing shape — `amount` is the dataclass default because
        # the saved dict didn't carry an `amount` key.
        self.assertEqual(ev.year, 10)
        self.assertEqual(ev.description, "Downsizing")
        self.assertEqual(ev.amount, 0.0)
        self.assertEqual(ev.sell_property_value, 400000)
        self.assertEqual(ev.new_property_value, 250000)
        # Lock the engine's value-based dispatch predicate. A real
        # downsizing (sell > 0) routes into the downsizing branch.
        self.assertTrue(ev.sell_property_value > 0)
        self.assertEqual(ev.amount, 0)

    def test_memo_dict_round_trip(self):
        """Edge case: a memo event has both `amount == 0` AND no
        `sell_property_value` key. After `LifeEvent(**d)` it should
        have amount=0 AND sell=0 so the engine falls through to the
        `triggered.append(event.description)` memo path."""
        from models.events import LifeEvent
        ev = LifeEvent(
            **{"year": 7, "description": "Note"}
        )
        self.assertEqual(ev.year, 7)
        self.assertEqual(ev.description, "Note")
        self.assertEqual(ev.amount, 0.0)
        self.assertEqual(ev.sell_property_value, 0.0)
        # Neither predicate fires — falls through to the memo branch.
        self.assertFalse(ev.sell_property_value > 0)
        self.assertEqual(ev.amount, 0)

    def test_legacy_cash_dict_does_not_silently_flip_to_downsizing(self):
        """Defensive: a legacy int-amount cash dict must NOT be
        misclassified as downsizing. Some early saved JSONs have
        integer `amount` (no `amount >= 0` check), but as long as
        `sell_property_value` is absent (and thus defaults to 0.0),
        the engine takes the cash branch — proven by the predicate
        assertions."""
        from models.events import LifeEvent
        ev = LifeEvent(
            **{"year": 3, "amount": 100, "description": "Cash only"}
        )
        self.assertEqual(ev.amount, 100)
        self.assertEqual(ev.sell_property_value, 0.0)
        self.assertFalse(ev.sell_property_value > 0)

    def test_downsizing_event_symbol_pruned(self):
        """Post-refactor the `DownsizingEvent` symbol is GONE from
        `models.events` — its presence would be a regression of the
        structural half of the consolidation (the dataclass was folded
        into `LifeEvent` so callers shouldn't be allowed to construct
        an instance of the old sibling type). Asserts the symbol is
        absent on the module surface."""
        import models.events as events_mod
        self.assertFalse(
            hasattr(events_mod, "DownsizingEvent"),
            "DownsizingEvent should have been pruned — its presence "
            "is a regression of the structural half of the consolidation.",
        )

    def test_build_event_dispatcher_is_pruned(self):
        """`build_event` was a sibling dataclass dispatcher; both
        concerns are gone now, so the function should not exist."""
        import models.events as events_mod
        self.assertFalse(
            hasattr(events_mod, "build_event"),
            "build_event should have been pruned — every callsite was "
            "rewritten to use LifeEvent(**e) directly.",
        )
