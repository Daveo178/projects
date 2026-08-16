"""
Shared Years+Months helpers.

Used by `pages/3_Assets.py` (mortgage term form), `pages/2_Pensions.py`
(retirement-age, current-age, state-pension-age, DB-draw-age) to keep the
math, English pluralisation, and the two-column Streamlit widget in one
place. Each page passes its own action verb ("ends", "retires", "is")
so the caption reads naturally:

    _split_years_into_years_and_months(9.5)
        -> (9, 6)
    _format_years_months_caption(verb="ends", noun="Mortgage",
                                 years=9, months=6)
        -> "Mortgage ends in 9 years and 6 months."
    years_and_months_input(label_years="Years", label_months="Months",
                           default_years_float=55.5, key_prefix="d_age",
                           max_years=100)
        -> 55.5  # two number_input columns + a refreshable caption

The mathematical helper is intentionally verbatim-equal to the version
that previously lived inside `pages/3_Assets.py` (same `max(0.0, ...)`
clamp, same `int()` truncation, same `round(*12)` for the months
component, same `months == 12` promotion corner case). Pulling it out
here is purely a DRY refactor — no behavioural change.
"""

from datetime import date
from typing import Tuple

import streamlit as st


def _split_years_into_years_and_months(years_float: float) -> Tuple[int, int]:
    """Decompose a (possibly-fractional) `years_float` into whole years +
    leftover months in [0, 11]. Used by the Mortgage and Retirement-age
    forms to pre-fill the two-field UI from data that may have been
    saved with a single float (current scheme) or an integer (legacy
    scheme — older plans still round-trip cleanly because integer 10
    -> (10, 0)).

    Months are rounded to the nearest whole month; the `months == 12`
    promotion corner case (e.g. 8.99999 due to FP rounding) bumps a
    full extra year so the form never displays a disallowed 12-month
    value.

    Defensive `max(0.0, years_float)` clamp at the top: the forms'
    `min_value=0` already prevents negatives, but a future caller could
    pass a value from a different path. Silently mapping a negative
    input to (0, 0) is safer than showing a misleading "−2 years and
    −3 months" caption.

    >>> _split_years_into_years_and_months(9.5)
    (9, 6)
    >>> _split_years_into_years_and_months(10)
    (10, 0)
    >>> _split_years_into_years_and_months(9.99999)  # FP round-up edge case
    (10, 0)
    """
    years_float = max(0.0, float(years_float))
    whole_years = int(years_float)
    months = round((years_float - whole_years) * 12)
    if months == 12:
        whole_years += 1
        months = 0
    return whole_years, months


def get_p1_current_age(
    household_data: "dict | None",
    *,
    default: float = 55.0,
) -> float:
    """Return Person 1's current age from `household_data`, with a
    Reset-Plan fallback.

    Centralises the duplicated `try: float(household_data["person1"]
    ["age"]) except (...)` block that used to live inline on
    pages 1 / 6 / 8 / 10 / 11 / 12 / 13. The fallback `default=55.0`
    mirrors the Person-1-as-anchor convention used across the app.

    Defensive exception list — these three cover every realistic
    failure mode of the dict access:
      * `KeyError` — `household_data` is `None`, the dict doesn't have
        `"person1"`, or the inner dict doesn't have `"age"`. Fires on
        the "Reset Plan" path on the Home page, which wipes
        `st.session_state.household_data = {}` mid-session.
      * `TypeError` — dict is malformed (e.g. a future refactor
        accidentally replaced the inner dict with a non-dict, or
        `household_data["person1"]` is a `None`).
      * `ValueError` — the saved JSON has `age=null` (or a
        non-numeric string), which `float(...)` rejects.

    Why `float(...)` and not duck-typing int/float separately?
      `years_and_months_input` (Page 2 widget) writes back as
      `years + months/12.0`, which is always a float. Legacy
      `int`-saved JSONs coerce cleanly at the assignment boundary,
      so a single `float(...)` cast covers both code paths without
      a separate int-vs-float dispatch.

    Returns:
      * `float(household_data["person1"]["age"])` on the happy path —
        typically a `years + months/12.0` value like `55.8333…` for a
        a saved-plan-aged Person 1 at 55y10m, OR a whole-number `55.0` for a
        legacy int-saved JSON.
      * `default` (55.0) on any failure mode above. Deliberately
        NOT `None` so callers can use the return value in arithmetic
        (`p1_current_age + len(results["years"]) - 1`) without a
        `None` guard.

    Bool-coercion footgun guard:
      In Python `bool` is a subclass of `int` so `float(True) == 1.0`
      and `float(False) == 0.0`. A JSON `age: true` would silently
      be treated as a 1-year-old infant by a naive `float(...)`. The
      `isinstance(age, bool)` short-circuit maps `True`/`False` to
      `default` so a future caller can't trip on the implicit
      int-float promotion path.

    Negative-clamp + NaN-clamp:
      Defensive `age >= 0.0` predicate at the bottom — a manual
      JSON-edit setting `age=-1` would otherwise render "Age -1 → ..."
      on the chart axis label. As a side effect `float("nan")`
      (`nan >= 0.0` evaluates to False via IEEE-754 NaN semantics)
      is also clamped to `default` — a JSON `age: nan` therefore
      falls back to 55 rather than rendering a "NaN" axis label.
      The negative clamp applies ONLY to the parsed-age path, NOT
      to `default`: a caller passing `default=-1.0` will see `default`
      preserved (caller's responsibility to choose a sensible default).

    >>> get_p1_current_age({"person1": {"age": 55.5}})
    55.5
    >>> get_p1_current_age({"person1": {"age": 55}})  # legacy int JSON
    55.0
    >>> get_p1_current_age(None)
    55.0
    >>> get_p1_current_age({})  # Reset-Plan empty dict
    55.0
    >>> get_p1_current_age({"person1": {"age": -1.0}})  # negative clamp
    55.0
    >>> get_p1_current_age({"person1": {"age": True}})  # bool footgun
    55.0
    """
    if household_data is None:
        return default
    try:
        age = household_data["person1"]["age"]
    except (KeyError, TypeError):
        return default
    # Bool-coercion footgun — see docstring. `isinstance(True, int)`
    # is True (bool is a subclass of int) so this guard must run
    # BEFORE the float() conversion; otherwise True → 1.0 would
    # silently be treated as a 1-year-old infant.
    if isinstance(age, bool):
        return default
    try:
        age = float(age)
    except (TypeError, ValueError):
        return default
    return age if age >= 0.0 else default


def format_age_label(age_float: float) -> str:
    """Compact 'Xy Ym' age label for chart titles and tick labels.

    Example outputs::

        format_age_label(55)            -> "55y"
        format_age_label(55.5)          -> "55y 6m"
        format_age_label(55 + 10 / 12)  -> "55y 10m"
        format_age_label(60.0)          -> "60y"

    Months are rounded to the nearest whole month; the
    ``months == 12`` FP-rounding promotion corner case (e.g. 9.9999
    → 10y 0m) is handled by reusing `_split_years_into_years_and_months`.

    Used in chart titles like `"Asset Allocation Over Time (Age 55y 10m
    → 99y 10m)"` and in the `AgeLabel` column that drives Altair chart
    x-axis tick text. Without it, the legacy `:g` formatter truncates
    a fractional display to 4-6 significant figures ("Age 55.8333 →
    99.8333") which reads as raw numerical noise on a chart header.

    Compact `"Xy Ym"` format (vs the verbose English caption from
    `_format_years_months_caption`) because chart titles and tick labels
    are tight on horizontal space — the verbose form is reserved for
    form-caption copy where verbosity reads naturally (e.g. "Retires in
    55 years and 10 months.").
    """
    years_i, months_i = _split_years_into_years_and_months(age_float)
    if months_i == 0:
        return f"{years_i}y"
    return f"{years_i}y {months_i}m"


def add_age_label_column(
    frame: "pd.DataFrame",
    age_column: str = "Age",
    label_column: str = "AgeLabel",
) -> "pd.DataFrame":
    """Return a copy of `frame` with `label_column` derived from a (likely
    fractional) `age_column` via `format_age_label`.

    Used by Altair chart pages (`pages/11_Timeline.py`,
    `pages/12_Asset_Allocation.py`) so the chart's x-axis ticks
    render `"55y 10m"` instead of `"55.8333…"`. The float `age_column`
    is preserved unchanged so `tooltip` can still show a numeric Age
    alongside the human-readable label, and downstream `.iloc[…,
    Age]` indexers (e.g. `pages/12_Asset_Allocation.py`'s slider
    lookup) still get an exact row.
    """
    out = frame.copy()
    out[label_column] = out[age_column].apply(format_age_label)
    return out


def attach_age_columns(
    frame: "pd.DataFrame",
    p1_current_age: float,
    *,
    year_column: str = "Year",
    age_column: str = "Age",
    label_column: str = "AgeLabel",
) -> "pd.DataFrame":
    """Year → Age (float) → AgeLabel (string) pipeline in a single call.

    Returns a fresh copy of `frame` with TWO new columns appended —
    `Age` (the float `year + p1_current_age`, used for numerics,
    tooltips, the data table, and any `.iloc[…, Age]` indexer that
    wants a numeric age) and `AgeLabel` (the compact `"55y 10m"`
    string used to bind Altair chart x-axes via `AgeLabel:O` so
    tick text renders cleanly without the float's decimal expansion).

    Consolidates the two near-identical inline helpers that used to
    live on `pages/1_Home.py` (`_attach_age_column(df)` — `Age`
    only) and `pages/11_Timeline.py` (`_add_age_column(frame)` —
    `Age` + `AgeLabel`). The unified helper always produces both
    columns: any caller that only needs one (e.g. `st.line_chart`
    which binds to the float `Age`) pays the trivial cost of a
    `format_age_label.apply()` on ≤ ~200 rows.

    Why both columns rather than a flag:
      * `st.line_chart(df, x="Age", y=...)` is happy with the extra
        `AgeLabel` column — it's just ignored.
      * Altair `x=alt.X("AgeLabel:O", ...)` is happy with the extra
        `Age` column — used in tooltips alongside the label.
      * A flag-style `produce_label=False` would force each caller
        to declare intent, and the conditional `.apply` path would
        add a branch on every render for no real perf gain.

    Defensive:
      * `frame` missing `year_column` raises `KeyError` — the caller
        wrote `Annual Funding Sources` (which starts from `{"Age":…}`
        not `Year`) and should call `add_age_label_column` on the
        already-`Age`-bearing frame, NOT this helper. Native
        `KeyError` is the right noise here so a future caller reading
        the docstring doesn't silently produce blank tick labels.
      * NaN in `year_column` propagates to NaN in `Age` (NaN + finite
        = NaN via IEEE-754) and then `format_age_label` raises
        `TypeError` because `split_years_into_years_and_months` does
        an `int(float(NaN))` which raises. The chart pages convert
        all engine output through `to_int_pounds` first (which
        preserves NaN via the `pd.isna` guard), so NaN realistically
        shouldn't reach this helper from engine data. A defensive
        test in `tests/test_months_precision.py` confirms the
        contract for the Year-only path.

    >>> attach_age_columns(pd.DataFrame({"Year": [0, 5]}), 55.5)
       Year    Age AgeLabel
    0     0  55.5    55y 6m
    1     5  60.5    60y 6m
    """
    out = frame.copy()
    out[age_column] = out[year_column] + float(p1_current_age)
    out[label_column] = out[age_column].apply(format_age_label)
    return out


def _compute_years_months_delta(
    target_years: int,
    target_months: int,
    current_age_float: float,
) -> Tuple[int, int, bool]:
    """Compute the years + months gap from `current_age_float` to a
    target declared as whole `target_years` + `target_months`.

    Returns a 3-tuple `(delta_years, delta_months, is_past_or_now)`:

      * `delta_years` — whole years remaining. Always 0 when the
        caller passed `is_past_or_now=True`.
      * `delta_months` — leftover months in [0, 11].
      * `is_past_or_now` — True when the target is at or BEFORE the
        current age (delta is zeroed and the caller renders an
        "already retired" / "today" message instead of the normal
        time-to-target caption).

    Used by `pages/2_Pensions.py` retirement-age caption so the
    rendered line is the *time-until-retirement* (e.g. 4y 10m) rather
    than the literal retirement-age input (e.g. 60y 8m). The pension
    age and current-age partner values are independent widgets, so the
    delta is computed fresh on every render rather than persisted.

    Implementation details — floating-point handling:

      Naive `int(current_age_float * 12)` would *almost* work: when
      `current_age_float` came out of `years_and_months_input`, its
      internal `float(years_i) + float(months_i)/12` shape makes the
      `* 12` cancellation exact for `years_i ∈ ℤ`, `months_i ∈ 0..11`.
      BUT `10/12` in IEEE-754 is not exactly representable, so
      `(55 + 10/12) * 12` evaluates to `669.99999…` (NOT 670), and a
      bare `int(...)` would silently off-by-one the user's reported
      case (55y10m → 4y9m instead of 4y10m).

      Avoiding the FP drift: round-trip `current_age_float` back
      through `_split_years_into_years_and_months`, which already
      handles the months-rounding edge case (e.g. `8.99999 → 9y 0m`)
      and returns a clean `(int, int)` pair. Multiplying those by 12
      gives an exact integer month count.

    Edge cases:

      * `current_age_float` is a legacy int saved JSON (e.g. 55):
        `_split_years_into_years_and_months(55)` → `(55, 0)` →
        total = 660 months. Clean.
      * `target_years`+`target_months` ≤ current age: returns
        `(0, 0, True)` so the caller renders the empty-message form.
      * Negative `current_age_float` (defensive — widget bounded to
        `min_years≥18`, but a future caller could pass anything):
        clamped to 0 by `_split_years_into_years_and_months`.

    >>> _compute_years_months_delta(60, 8, 55 + 10/12)
    (4, 10, False)
    >>> _compute_years_months_delta(60, 0, 55)
    (5, 0, False)
    >>> _compute_years_months_delta(60, 0, 60)
    (0, 0, True)
    """
    age_years_i, age_months_i = _split_years_into_years_and_months(
        current_age_float
    )
    target_total_months = int(target_years) * 12 + int(target_months)
    age_total_months = age_years_i * 12 + age_months_i
    delta_total_months = target_total_months - age_total_months
    if delta_total_months <= 0:
        return (0, 0, True)
    return (
        delta_total_months // 12,
        delta_total_months % 12,
        False,
    )


def _format_years_months_caption(
    verb: str,
    noun: str,
    years: int,
    months: int,
    empty_message: str = "",
) -> str:
    """Friendly English caption for both forms.

    Reads naturally as e.g. `"Mortgage ends in 9 years and 6 months."` or
    `"Retires in 60 years and 6 months."`, with sensible singular
    pluralisation on the noun + unit ("1 year" vs "2 years", "1 month"
    vs "2 months"). When both years and months are zero, falls back to
    a caller-supplied `empty_message` (e.g. `"Mortgage ends immediately
    (no remaining term)."` or `"Already retired today (no remaining
    working period)."`).
    """
    if years == 0 and months == 0:
        return empty_message
    # Conditional subject prefix so the noun-less retirement form reads
    # "Retires in 60 years..." without a leading-space cosmetic
    # (`{noun} {verb}` would render as a leading " retires" when
    # noun="" — visible in copy-paste and unfriendly to text-search).
    subject = f"{noun} " if noun else ""
    if years == 0:
        return f"{subject}{verb} in {months} month{'s' if months != 1 else ''}."
    if months == 0:
        return f"{subject}{verb} in {years} year{'s' if years != 1 else ''}."
    return (
        f"{subject}{verb} in {years} year{'s' if years != 1 else ''} and "
        f"{months} month{'s' if months != 1 else ''}."
    )


def years_and_months_input(
    *,
    label_years: str,
    label_months: str,
    default_years_float: float,
    key_prefix: str,
    min_years: int = 0,
    max_years: int = 99,
    max_months: int = 11,
    help_months=None,
    caption_verb: str = "",
    caption_noun: str = "",
    caption_empty_message: str = "",
) -> float:
    """Two-column years+months Streamlit widget. Returns a `float`.

    Used wherever the app needs a single float value that the user enters
    in two halves (whole years + 0..11 months). Renders one row containing
    `st.columns(2)` with `st.number_input(label_years)` and
    `st.number_input(label_months)`, followed (optionally) by a friendly
    English caption via `_format_years_months_caption`. Returns the
    float `years + months / 12.0` so the caller can persist it as one
    canonical value (mirrors the existing `Mortgage.end_year` /
    `retirement_age` storage shape).

    Param semantics:
      * `label_years` / `label_months` — Visible labels on the two
        `number_input` boxes. Pass short labels ("Years", "Months")
        when the surrounding form already has a header that gives
        semantic context; pass full labels ("Retirement age (years)",
        "Retirement age (months)") when standing alone.
      * `default_years_float` — The user's saved value. Owned helpers
        and pages must pass whatever shape the saved JSON has — `int`
        is auto-floated via `float(...)`.
      * `key_prefix` — Streamlit widget key prefix; `_years` and
        `_months` are appended internally. E.g. `key_prefix="d_age"`
        renders keys `d_age_years` and `d_age_months`. Pages that own
        N widgets under the same logical control MUST pass distinct
        `key_prefix` values to avoid Streamlit's
        `StreamlitDuplicateWidgetKey` error on render.
      * `min_years` / `max_years` — Whole-year bounds. Pass realistic
        per-field values (e.g. `min_years=18, max_years=100` for
        current_age; `max_years=80` for retirement_age / draw_age).
      * `max_months` — Currently always 11 (year-from-12 corner case
        is folded into `_split_years_into_years_and_months` via the
        `months == 12` promotion). Exposed as a parameter so a future
        caller with a non-calendar bound could reuse the widget.
      * `help_months` — Tooltip text on the months input.
        `None` (default) omits the help icon entirely rather than
        rendering an empty tooltip. Streamlit's `number_input` rejects
        an explicit `help=None` in some versions — only forward the
        argument when it's a non-None string.
      * `caption_verb` / `caption_noun` / `caption_empty_message` —
        Wired straight into `_format_years_months_caption`. Pass
        `caption_verb="retires"`, `caption_noun=""` for the retirement
        form so the caption reads "Retires in 60 years and 6 months.".
        Pass `caption_verb="is"`, `caption_noun="Current age"` for a
        current-age form so it reads "Current age is 55 years and 6
        months.". The empty-`caption_verb` short-circuit suppresses
        a noisy "." cosmetic when a caller wants no caption narrative
        from this widget.

    Return type: `float` so consumers can store it directly under any
    key the saved JSON accepts — `_split_years_into_years_and_months`
    folds it back into (years, months) on the read side.

    Why use the helper instead of two bare `number_input`s?
      * Single source of truth for the widget contract — change the
        cap range, the step, or the caption format in one file and
        every page benefits.
      * Eliminates duplicated boilerplate (two-column block, caption
        block, pre-fill, multiple Streamlit keys) that was being
        duplicated 8+ times across the app.
      * Locks the legacy `int` -> `(int_years, 0)` preload path so
        older saved JSONs (with bare ints in `age`,
        `state_pension_age`, etc.) round-trip cleanly through the
        float-typed storage model that Person now uses.
    """
    # Coerce to float up-front so int-saved legacy JSONs don't crash
    # `_split_years_into_years_and_months` (which divides by 12 and
    # would silently promote the int to float anyway, but doing it
    # here signals intent).
    default_years_float = float(default_years_float)
    default_years_i, default_months_i = _split_years_into_years_and_months(
        default_years_float
    )
    col_years, col_months = st.columns(2)
    with col_years:
        years_value = st.number_input(
            label=label_years,
            min_value=min_years,
            max_value=max_years,
            value=default_years_i,
            key=f"{key_prefix}_years",
        )
    with col_months:
        # Build kwargs so a `None` `help_months` doesn't get forwarded
        # (some Streamlit versions reject explicit `help=None`). The
        # conditional keeps the months-input rendering consistent with
        # the years-input above.
        month_kwargs = dict(
            min_value=0,
            max_value=max_months,
            value=default_months_i,
            key=f"{key_prefix}_months",
        )
        if help_months is not None:
            month_kwargs["help"] = help_months
        months_value = st.number_input(
            label=label_months,
            **month_kwargs,
        )

    # Empty-`caption_verb` short-circuit — a caller wanting the widget
    # WITHOUT a caption narrative doesn't see a leading '.' cosmetic
    # when the verb is empty. The caption_noun pass-through still
    # supports a bare "is" form ("is 55 years and 6 months.") which
    # reads naturally even without a noun.
    if caption_verb:
        st.caption(
            _format_years_months_caption(
                verb=caption_verb,
                noun=caption_noun,
                years=years_value, months=months_value,
                empty_message=caption_empty_message,
            )
        )

    return float(years_value) + float(months_value) / 12.0


# ---------------------------------------------------------------------------
# Date-of-birth helpers — compute floating-point ages from date inputs.
# ---------------------------------------------------------------------------
# Replaces the old "Current age" years+months widget on the Pensions page
# (and the number_input on Quick Estimate) so the user enters a DOB once
# and the age auto-advances without manual re-entry every month. The engine
# still sees float `age` and float `retirement_age` — these helpers just
# compute those floats from date pickers on the UI layer.

_DAYS_PER_YEAR = 365.25


def _compute_age_from_dob(dob_str: str, as_of: date | None = None) -> float:
    """Return current age in fractional years from a DOB string.

    Args:
        dob_str: ISO-format date string ("1970-03-15").
        as_of: the reference date (defaults to today).

    Returns:
        `(as_of - dob).days / 365.25` — a float like 55.83 (≈55y10m).
        Returns 18.0 as a floor for any future DOB (defensive — a user
        fat-fingering a DOB as "2070" shouldn't produce a negative age).

    >>> _compute_age_from_dob("1970-01-01", as_of=date(2025, 7, 1))
    55.504...
    """
    dob = date.fromisoformat(dob_str)
    ref = as_of if as_of is not None else date.today()
    delta_days = (ref - dob).days
    if delta_days <= 0:
        return 18.0
    return delta_days / _DAYS_PER_YEAR


def _years_from_dates(start_str: str, end_str: str) -> float:
    """Return fractional years between two ISO date strings.

    Used to compute retirement_age from DOB and retirement_date:
        retirement_age = _compute_age_from_dob(dob) + _years_from_dates(today, retirement_date)

    Returns 0.0 if end <= start (defensive — a retirement date in the
    past just means already retired; the page's delta caption handles
    that case with an "Already retired" message).

    >>> _years_from_dates("2025-01-01", "2030-01-01")
    5.0
    """
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)
    delta_days = (end - start).days
    if delta_days <= 0:
        return 0.0
    return delta_days / _DAYS_PER_YEAR
