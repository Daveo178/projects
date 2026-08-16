"""UK Pension Annual Allowance (AA) — pure-function module.

The Annual Allowance caps the total employee + employer contributions each
person can make to a defined-contribution pension in a single tax year while
still receiving tax relief. Anything above the AA becomes taxable as income
(the "annual allowance charge").

**Modelled rules (HMRC, 2023/24 onwards)**

  - Standard AA: £60,000
  - Minimum (taper floor): £10,000
  - Taper threshold (threshold income): £200,000
  - Taper formula:
        AA = max(MIN_TAPERED_AA,
                 STANDARD_AA - (threshold_income - TAPER_THRESHOLD_INCOME) / 2)

So an income of £200,000 keeps the full £60,000 AA; £250,000 tapers to
£35,000; £300,000 floor at £10,000.

**Not modelled** (out of scope for this app — surfaced as a disclaimer on the
Pensions page):

  - Adjusted-income rules (HMRC also requires adjusted income > £260,000
    before the taper activates; we approximate by collapsing the two-stage
    test into a single threshold-income check)
  - Carry-forward from under-utilised AA in the previous three tax years
  - Defined-benefit scheme accrual values (not modelled at all in this app)

**Per-spouse independence**

Each partner has their own AA envelope — Person 1 and Person 2's contributions do
not share one pot. So `effective_aa(income_person1)` and `effective_aa(income_person2)`
are computed separately, and the household AA exposure is the sum of the two
partner statuses (each partner's annual contribution vs each partner's own
effective AA). The page-side panel surfaces it that way, mirroring the
per-spouse tax/NI slice.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# HMRC-published constants (2023/24 / 2024/25 — stable across recent years).
# Single source of truth — the page side and tests all import from here.
# ---------------------------------------------------------------------------
STANDARD_AA = 60_000.0          # full AA before taper
TAPER_THRESHOLD_INCOME = 200_000.0  # threshold income above which the taper starts
MIN_TAPERED_AA = 10_000.0       # floor — even at very high incomes the AA never falls below this


def effective_aa(threshold_income: float) -> float:
    """Return the effective Annual Allowance given a `threshold_income`.

    `threshold_income` is the user's total income before pension contributions
    (employment + rental + investment; broadly HMRC's definition). Our app
    uses `income_until_retirement` as a single-source proxy.

    Returns a positive `float` in pounds, never below `MIN_TAPERED_AA`.
    Negative or non-numeric inputs return `STANDARD_AA` (defensive — the UI
    shows £0 income in some edge cases and we shouldn't refuse to display a
    number in that path).
    """
    try:
        income = float(threshold_income)
    except (TypeError, ValueError):
        return STANDARD_AA
    if income <= TAPER_THRESHOLD_INCOME:
        return STANDARD_AA
    tapered = STANDARD_AA - (income - TAPER_THRESHOLD_INCOME) / 2.0
    return max(MIN_TAPERED_AA, tapered)


def project_annual_contribution(person_dict: dict) -> float:
    """Return the expected TOTAL annual pension contribution £ figure
    (employee + employer).

    HMRC's Annual Allowance caps TOTAL pension contributions —
    employee AND employer combined — so the projection here must
    include the employer percentage contribution once the
    Quick-Estimate-style split is in play.

    Projection rules (mirrors the Pensions page + engine precedence):

      1. New split model (Quick Estimate + any user with the new
         fields set). When ANY of the three new fields is set —
             personal_contrib_pct > 0
             personal_contrib_flat_monthly > 0
             employer_contrib_pct > 0
         — the projection sums the personal AND the employer
         contributions and IGNORES the legacy fields entirely.

         Precedence within the personal side: `% > £`. Same
         contract as the engine `_monthly_dc_contrib` helper so a
         bad input that bumps both fields at once still resolves
         deterministically.

         Returns:
             personal_annual = (pct > 0)
                 ? income * personal_contrib_pct
                 : personal_contrib_flat_monthly * 12
             employer_annual = income * employer_contrib_pct
             total = personal_annual + employer_annual

      2. Legacy model (saved plans predating the Quick Estimate
         split). When ALL THREE new fields are zero, fall back to
         the existing logic:
           * `monthly_contrib_pct > 0` → `income * monthly_contrib_pct`
           * otherwise → `monthly_contrib * 12`
           * if neither is present, return 0.0.

    Missing or non-numeric input fields coerce to 0.0 so the helper is safe
    to call with partial session_state dicts (e.g. on first-page load).
    """
    personal_pct = _safe_float(person_dict.get("personal_contrib_pct", 0.0))
    personal_flat = _safe_float(person_dict.get("personal_contrib_flat_monthly", 0.0))
    employer_pct = _safe_float(person_dict.get("employer_contrib_pct", 0.0))
    if (personal_pct > 0.0) or (personal_flat > 0.0) or (employer_pct > 0.0):
        income = _safe_float(person_dict.get("income_until_retirement", 0.0))
        personal_annual = (
            income * personal_pct
            if personal_pct > 0.0
            else personal_flat * 12.0
        )
        employer_annual = income * employer_pct
        return personal_annual + employer_annual
    pct = _safe_float(person_dict.get("monthly_contrib_pct", 0.0))
    if pct > 0.0:
        return _safe_float(person_dict.get("income_until_retirement", 0.0)) * pct
    return _safe_float(person_dict.get("monthly_contrib", 0.0)) * 12.0


# ---------------------------------------------------------------------------
# Status token — pure, dependency-free, page-side `_show_aa_status` calls into
# this so the comparison direction can be unit-tested directly. Returns one
# of two stable tokens; the page is responsible for picking the visual
# treatment (warning vs caption). Adding a new state (e.g. "approaching")
# would surface here first.
# ---------------------------------------------------------------------------
STATUS_WITHIN = "within"
STATUS_EXCEEDED = "exceeded"


def aa_status(projected_contribution: float, effective_aa_amount: float) -> str:
    """Return the AA status for a `(contribution, allowance)` pair.

    Convention: strictly above the AA counts as exceeded (i.e. the
    user has contributed at least one pound over their cap). Equal-to
    the AA is considered "within" — the user has used their allowance
    exactly, no excess, no HMRC AA charge. Negative / non-numeric inputs
    are coerced to 0.0 so the helper never raises.
    """
    try:
        return STATUS_EXCEEDED if float(projected_contribution) > float(effective_aa_amount) else STATUS_WITHIN
    except (TypeError, ValueError):
        return STATUS_WITHIN


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
