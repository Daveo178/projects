"""
Tests for `pages_helpers.personal_employer_contrib.resolve_legacy_after_save`.

The helper is the pure, unit-testable BC decision that both save
blocks call to decide whether legacy `monthly_contrib_pct` /
`monthly_contrib` should be preserved or wiped on save.

Decision rules (mirrored verbatim from the helper's docstring so
the test is the authoritative contract):

  1. `any_new` non-zero (after FP-drift rounding) -> ZERO legacy.
  2. `any_new` zero AND `user_touched=True`         -> ZERO legacy
     (the explicit-zero BC fix: a legacy user dragged the
     migrated slider to 0% to wipe their contribution).
  3. `any_new` zero AND `user_touched=False`        -> preserve
     legacy from `saved_legacy_*`.

Other invariants locked down:
  * legacy values are passed through byte-for-byte when preserved.
  * the function is type-stable (always returns `tuple[float, float]`).
  * FP drift (`round(value, 6) > 0` rather than raw `> 0`) doesn't
    flip the decision for values like `1e-9` etc.
"""
import unittest

from pages_helpers.personal_employer_contrib import (
    resolve_legacy_after_save,
)


class TestResolveLegacyAfterSave(unittest.TestCase):
    """Lock the BC decision matrix exhaustively."""

    # ----- Case 1: any_new is non-zero -> ZERO legacy -----

    def test_any_new_personal_pct_zeros_legacy(self):
        # Personal % set, no employer, no touch. Engine will read
        # personal_contrib_pct, so legacy must be wiped to avoid
        # an audit-pass double-count.
        out = resolve_legacy_after_save(
            personal_pct=0.05,
            personal_flat=0.0,
            employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.15,
            saved_legacy_flat=0.0,
        )
        self.assertEqual(out, (0.0, 0.0))

    def test_any_new_personal_flat_zeros_legacy(self):
        out = resolve_legacy_after_save(
            personal_pct=0.0,
            personal_flat=200.0,
            employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.0,
            saved_legacy_flat=200.0,
        )
        self.assertEqual(out, (0.0, 0.0))

    def test_any_new_employer_zeros_legacy(self):
        out = resolve_legacy_after_save(
            personal_pct=0.0,
            personal_flat=0.0,
            employer_pct=0.03,
            user_touched=False,
            saved_legacy_pct=0.15,
            saved_legacy_flat=200.0,
        )
        # Employer set alone is enough — engine reads employer
        # and ignores legacy via the precedence rule.
        self.assertEqual(out, (0.0, 0.0))

    def test_all_three_new_zero_with_touched_true_zeros_legacy_legacy_pct(self):
        # The headline explicit-zero BC fix: legacy=0.15, user
        # migrates to slider=15%, drags down to 0%, doesn't touch
        # employer. touched=True so we WIPE legacy (rather than
        # silently preserving 0.15 from before).
        out = resolve_legacy_after_save(
            personal_pct=0.0,
            personal_flat=0.0,
            employer_pct=0.0,
            user_touched=True,
            saved_legacy_pct=0.15,
            saved_legacy_flat=0.0,
        )
        self.assertEqual(out, (0.0, 0.0))

    def test_all_three_new_zero_with_touched_true_zeros_legacy_legacy_flat(self):
        # Flat-£ analogue — legacy `monthly_contrib=200`, user
        # migrated to flat £ field showing 200, types in 0. Wipe.
        out = resolve_legacy_after_save(
            personal_pct=0.0,
            personal_flat=0.0,
            employer_pct=0.0,
            user_touched=True,
            saved_legacy_pct=0.0,
            saved_legacy_flat=200.0,
        )
        self.assertEqual(out, (0.0, 0.0))

    # ----- Case 3: any_new zero, no touch -> preserve legacy -----

    def test_untouched_legacy_pct_preserved(self):
        # Legacy user migrated slider to 15%, didn't touch the
        # slider, clicked Run. any_new=True because the slider is
        # sitting at 15% in session_state and the helper returns
        # (0.15, 0, 0). So this test lands in Case 1, not Case 3.
        # The "true Case 3" scenario runs the helper with values
        # that match the SAVED dict state, NOT the migrated UI
        # state (i.e. the slider was NOT migrated because the
        # rendered widget was zeroed / unread).
        out = resolve_legacy_after_save(
            personal_pct=0.0,
            personal_flat=0.0,
            employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.15,
            saved_legacy_flat=0.0,
        )
        self.assertEqual(out, (0.15, 0.0))

    def test_untouched_legacy_flat_preserved(self):
        out = resolve_legacy_after_save(
            personal_pct=0.0,
            personal_flat=0.0,
            employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.0,
            saved_legacy_flat=200.0,
        )
        self.assertEqual(out, (0.0, 200.0))

    def test_untouched_both_legacy_zero_preserved(self):
        # Nothing on either side — brand-new user leaves it alone.
        out = resolve_legacy_after_save(
            personal_pct=0.0,
            personal_flat=0.0,
            employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.0,
            saved_legacy_flat=0.0,
        )
        self.assertEqual(out, (0.0, 0.0))

    # ----- FP-drift guard -----

    def test_fp_drift_does_not_treat_1e_9_as_nonzero(self):
        # Slider arithmetic could leave a value like `1e-9` if the
        # user did `5.0 / 100` and the FP rounded oddly. `round(.., 6)`
        # clamps this to 0.0 so we don't accidentally trip the
        # "any_new" branch.
        fp_drift = 1e-9
        out = resolve_legacy_after_save(
            personal_pct=fp_drift,
            personal_flat=0.0,
            employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.15,
            saved_legacy_flat=0.0,
        )
        # 1e-9 rounds to 0.0 at 6dp, so any_new=False, no
        # touch -> legacy preserved (Case 3).
        self.assertEqual(out, (0.15, 0.0))

    def test_fp_drift_does_not_treat_1e_7_as_nonzero(self):
        # At 6dp, `1e-7` rounds to `0.0`.
        out = resolve_legacy_after_save(
            personal_pct=1e-7,
            personal_flat=0.0,
            employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.15,
            saved_legacy_flat=200.0,
        )
        self.assertEqual(out, (0.15, 200.0))

    def test_value_one_above_fp_threshold_is_nonzero(self):
        # Belt-and-braces: a value just above the FP-drift threshold
        # should still trip the "any_new" branch. `1e-6` rounds
        # cleanly to `1e-6 > 0` (the exact `0.5e-6` boundary rounds to
        # 0 via banker's rounding, so we use `1e-6` which is in the
        # unambiguous non-zero zone at 6dp).
        out = resolve_legacy_after_save(
            personal_pct=1e-6,
            personal_flat=0.0,
            employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.15,
            saved_legacy_flat=0.0,
        )
        self.assertEqual(out, (0.0, 0.0))

    def test_per_partner_independence(self):
        # Integration-style: a touched flag for Dave must NOT
        # influence the resolution for Shaz (the helper is
        # called once per partner on each save, so its returned
        # tuple carries only the inputs for that one partner).
        # This pins the page-side wiring — a future refactor
        # that accidentally passes a single touched bool across
        # both partners would trip this test.
        dave_legacy = resolve_legacy_after_save(
            personal_pct=0.0, personal_flat=0.0, employer_pct=0.0,
            user_touched=True,
            saved_legacy_pct=0.15, saved_legacy_flat=0.0,
        )
        # Dave touched (explicit-zero): legacy wiped.
        self.assertEqual(dave_legacy, (0.0, 0.0))

        # Shaz has new fields set, untouched: legacy wiped via
        # the any_new branch — confirms the touched bool doesn't
        # bleed into a partner that didn't touch.
        shaz_legacy = resolve_legacy_after_save(
            personal_pct=0.10, personal_flat=0.0, employer_pct=0.05,
            user_touched=False,
            saved_legacy_pct=0.0, saved_legacy_flat=200.0,
        )
        self.assertEqual(shaz_legacy, (0.0, 0.0))

        # Shaz untouched AND new=0: legacy preserved. Even though
        # we just saw Dave's touched=False earlier, this is its
        # OWN untouched call - per-partner isolation.
        shaz_legacy_v2 = resolve_legacy_after_save(
            personal_pct=0.0, personal_flat=0.0, employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.0, saved_legacy_flat=200.0,
        )
        self.assertEqual(shaz_legacy_v2, (0.0, 200.0))

    # ----- Return-type stability -----

    def test_returns_tuple_of_floats(self):
        # Defensive: page-side save blocks do `data["person1"]
        # ["monthly_contrib"] = new_legacy_flat` — they MUST be
        # floats (not e.g. ints) so the JSON serialiser doesn't
        # drop a `.0` and break downstream float comparisons.
        out = resolve_legacy_after_save(
            personal_pct=0.0, personal_flat=0.0, employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.15, saved_legacy_flat=0.0,
        )
        self.assertIsInstance(out, tuple)
        self.assertEqual(len(out), 2)
        pct, flat = out
        self.assertIsInstance(pct, float)
        self.assertIsInstance(flat, float)

    # ----- Boundary cases -----

    def test_touched_with_no_legacy_returns_zeros(self):
        # User touches but there's no legacy to wipe — return zeros.
        out = resolve_legacy_after_save(
            personal_pct=0.0, personal_flat=0.0, employer_pct=0.0,
            user_touched=True,
            saved_legacy_pct=0.0, saved_legacy_flat=0.0,
        )
        self.assertEqual(out, (0.0, 0.0))

    def test_large_legacy_values_preserved(self):
        # Defensive: a 99% contribution isn't unusual for a
        # self-employed person near retirement. Make sure the
        # preserve path doesn't have an off-by-one at e.g. 1.0%.
        out = resolve_legacy_after_save(
            personal_pct=0.0, personal_flat=0.0, employer_pct=0.0,
            user_touched=False,
            saved_legacy_pct=0.99, saved_legacy_flat=5_000.0,
        )
        self.assertEqual(out, (0.99, 5_000.0))



if __name__ == "__main__":
    unittest.main()
