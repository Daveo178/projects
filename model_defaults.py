"""Default-valued partner / asset / mortgage dicts for blank-slate seeding.

WHY THIS MODULE EXISTS
======================
Previously, default values were scattered across several pages:

* `pages/2_Pensions.py` had hard-coded defaults buried in
  `_migrate_contrib_pct(p_dict, default_if_empty=0.15)` and the
  inline `p1.get("dc_pot", 0)` reads.
* `pages/3_Assets.py` had no defaults — a brand-new user saw
  zeros everywhere.
* The Quick Estimate page needs to seed a full household on
  first visit so the form isn't 5 different "0" prompts.

Centralising the defaults here means:

* Every entry-point agrees on the same starting point (no
  drift between Quick Estimate's "0 ISA / 0 GIA / 0 Cash /
  0 Property" and a future re-introduction in another page).
* Test code can import these defaults and build a baseline
  `household_data` dict without copy-pasting the literals.
* Migration / branding changes (e.g. defaulting to 5% DC growth
  instead of 7%) edit a single file rather than dozens.

USAGE
=====

    from model_defaults import (
        default_partner_dict,
        default_asset_dict,
        default_mortgage_dict,
    )

    data = {}
    data["person1"] = default_partner_dict("Person 1", p1=True)
    data["person2"] = default_partner_dict("Person 2", p1=False)
    data["assets"] = [
        default_asset_dict("ISA", "ISA"),
        default_asset_dict("Cash", "Cash"),
        default_asset_dict("GIA", "GIA"),
        default_asset_dict("Property", "Property"),
    ]
    data["mortgage"] = default_mortgage_dict()

DEFAULTS RATIONALE
==================
* `dc_growth_rate = 0.05` — 5%/yr nominal is the long-run
  UK balanced-portfolio estimate. Matches the Pensions-page
  slider default byte-for-byte so a Quick-Estimate user who
  flips into Detailed mode sees the same starting value.
* `db_growth_rate = 0.025` — 2.5%/yr indexation matches
  typical UK RPI/CPI; same as Pensions page default.
* `state_pension_growth_rate = 0.025` — 2.5%/yr matches the
  UK triple-lock approximation; same as Pensions page default.
* `income_growth_rate = 0.025` — same wage-inflation default
  the Pensions page slider lands on first open.
* `monthly_contrib_pct = 0.15` — 15% is a sensible middle for
  a UK worker's total pension contribution (employer +
  employee). The Pensions page's `_migrate_contrib_pct` helper
  also defaults to this value when a legacy saved plan lacks
  the field, so the two defaults agree.
* `personal_contrib_pct = 0.05` — 5% employee contribution is
  a sensible default for the Quick Estimate page's NEW
  personal-vs-employer split. Pairs with the 3% employer
  default below to give a realistic private-sector total of
  ~8% (historically the legacy `monthly_contrib_pct=0.15` was a
  "generous all-in" estimate that over-funded DC pots for
  casual users).
* `personal_contrib_flat_monthly = 0.0` — flat £-amount
  contribution ENTERED AS A SECOND MODE on the Quick Estimate
  page (for self-employed / irregular-income users who can't
  cleanly express their contribution as a % of salary). Default
  0 — the personal contribution uses the `% of income` mode by
  default.
* `employer_contrib_pct = 0.03` — 3% employer contribution is
  the typical UK private-sector minimum-match baseline
  (post-2012 auto-enrolment). Quick Estimate sets both
  partners' employer contribution to this value so the
  household's "what we're putting in" narrative reads
  intuitively: "5% you, 3% your employer".
* `draw_age = 60.0` — matches the Pensions-page default. Note
  that some DB schemes start at 65; a user can override via
  the Pensions page.
"""
from __future__ import annotations


# Per-partner defaults. The QUICK_ESTIMATE constants below are the
# canonical sources; helper functions below produce a copy. Two
# distinct constants (PERSON 1 / PERSON 2) is overkill — they share every
# field except `name` — but having two distinct dicts keeps the
# old named-partner historic split obvious to anyone who's
# reading the file looking for the partner-specific bits.
_PERSON1_BASE: dict = {
    "name": "Person 1",
    "dob": "",
    "age": 55.0,
    "retirement_date": "",
    "retirement_age": 60.0,
    "state_pension_age": 67.0,
    "dc_pot": 0.0,
    "db_income": 0.0,
    "pcls_percent": 0,
    "draw_age": 60.0,
    "income_until_retirement": 0.0,
    "income_growth_rate": 0.025,
    "monthly_contrib": 0.0,
    # Legacy combined-contribution % kept at 0.15 so the
    # detailed Pensions page's existing slider still renders a
    # sensible starting value for users who have never visited
    # Quick Estimate. The new fields below are the canonical
    # source for Quick-Estimate-driven simulations:
    "monthly_contrib_pct": 0.15,
    "personal_contrib_pct": 0.05,
    "personal_contrib_flat_monthly": 0.0,
    "employer_contrib_pct": 0.03,
    "dc_growth_rate": 0.05,
    "db_growth_rate": 0.025,
    "state_pension_growth_rate": 0.025,
}

_PERSON2_BASE: dict = {
    "name": "Person 2",
    "dob": "",
    "age": 55.0,
    "retirement_date": "",
    "retirement_age": 60.0,
    "state_pension_age": 67.0,
    "dc_pot": 0.0,
    "db_income": 0.0,
    "pcls_percent": 0,
    "draw_age": 60.0,
    "income_until_retirement": 0.0,
    "income_growth_rate": 0.025,
    "monthly_contrib": 0.0,
    # Same BC + new-fields rationale as `_PERSON1_BASE` above.
    "monthly_contrib_pct": 0.15,
    "personal_contrib_pct": 0.05,
    "personal_contrib_flat_monthly": 0.0,
    "employer_contrib_pct": 0.03,
    "dc_growth_rate": 0.05,
    "db_growth_rate": 0.025,
    "state_pension_growth_rate": 0.025,
}


def default_partner_dict(name: str, p1: bool = True) -> dict:
    """Return a fresh dict for a blank-slate partner.

    Args:
        name: the partner's display name (normally "Person 1" / "Person 2").
        p1: True for Person 1, False for Person 2
            The flag currently only selects which
            base dict to copy — both partners can carry any
            `name` value in practice.

    Returns:
        A new dict with every Partner field populated to a
        sensible default. The returned dict is a SHALLOW COPY
        of the base — modifications to it do not affect the
        module-level defaults, and a subsequent
        `default_partner_dict(...)` call also returns a fresh
        copy. The `name` key is overwritten with the supplied
        value (so callers don't have to remember to also set
        `data["person1"]["name"] = "Person 1"`).
    """
    base = _PERSON1_BASE if p1 else _PERSON2_BASE
    return {**base, "name": name}


def default_asset_dict(name: str, asset_type: str) -> dict:
    """Return a fresh dict for a blank-slate asset.

    Args:
        name: display name (e.g. "ISA" / "Cash").
        asset_type: one of "ISA", "Cash", "GIA", "Property".
            Used by the engine to look up the right tax
            treatment and to gate today's-value-mode growth
            overrides (Property gets `growth_rate = 0`, others
            get deflated by inflation).

    Returns:
        A new dict. `value = 0.0` so a brand-new user sees an
        honest "£0" rather than a misleading placeholder
        figure they'd mistake for their real balance.
        `growth_rate = 0.05` (5%/yr nominal) for ISA / Cash /
        GIA; `growth_rate = 0.0` for Property (matches the
        today's-value property-zeroing convention; the
        detailed Property slider lets the user override).
        `contribution_until_retirement = 0.0` — the detailed
        Assets page can override per-asset later.
    """
    if asset_type == "Property":
        return {
            "name": name,
            "value": 0.0,
            "growth_rate": 0.0,
            "contribution_until_retirement": 0.0,
            "asset_type": asset_type,
        }
    return {
        "name": name,
        "value": 0.0,
        "growth_rate": 0.05,
        "contribution_until_retirement": 0.0,
        "asset_type": asset_type,
    }


def default_mortgage_dict() -> dict:
    """Return a fresh dict for a blank-slate mortgage.

    Returns:
        A new dict. `outstanding = 0.0` so a mortgage-free
        household doesn't show a placeholder balance. `rate =
        0.04` matches the historical Assets-page slider
        default (4% is a plausible UK interest rate for a
        recent mortgage). `end_year = 10.0` (10 years) is
        the historical slider default. `annual_payment /
        annual_overpayment = 0.0` so a user with no payment
        pre-entered sees honest zeros. `include_in_spending
        = False` (the default: spending is lifestyle-only, the
        mortgage is funded on top, and the two are charted
        separately on the Home page).
    """
    return {
        "outstanding": 0.0,
        "rate": 0.04,
        "end_year": 10.0,
        "annual_payment": 0.0,
        "annual_overpayment": 0.0,
        "include_in_spending": False,
    }


__all__ = [
    "default_partner_dict",
    "default_asset_dict",
    "default_mortgage_dict",
]
