def uk_income_tax(earned_income, taxable_drawdown=0, tax_band_factor=1.0):
    """
    UK income tax model (2024/25).
    earned_income = salary + DB + state pension
    taxable_drawdown = taxable portion of DC withdrawals (UFPLS)

    ``tax_band_factor`` optionally indexes the monetary thresholds by the
    same cumulative inflation factor as a nominal projection. This keeps
    nominal Monte Carlo paths currency-consistent: pension income and
    spending rise with inflation, while the tax allowances and bands rise
    with it too. The default of 1.0 preserves the deterministic model and
    existing callers.
    """
    try:
        factor = max(0.0, float(tax_band_factor))
    except (TypeError, ValueError):
        factor = 1.0
    if factor == 0.0:
        factor = 1.0

    total_taxable_income = earned_income + taxable_drawdown

    personal_allowance = 12570 * factor
    basic_rate_limit = 50270 * factor
    higher_rate_limit = 125140 * factor
    personal_allowance_taper_start = 100000 * factor

    # Personal allowance tapering
    if total_taxable_income > personal_allowance_taper_start:
        reduction = (total_taxable_income - personal_allowance_taper_start) // 2
        personal_allowance = max(0, personal_allowance - reduction)

    taxable = max(0, total_taxable_income - personal_allowance)

    tax = 0

    # Basic rate
    if taxable > 0:
        band = min(taxable, basic_rate_limit - personal_allowance)
        tax += band * 0.20
        taxable -= band

    # Higher rate
    if taxable > 0:
        band = min(taxable, higher_rate_limit - basic_rate_limit)
        tax += band * 0.40
        taxable -= band

    # Additional rate
    if taxable > 0:
        tax += taxable * 0.45

    net = total_taxable_income - tax

    return {
        "gross": total_taxable_income,
        "tax": tax,
        "net": net,
        "effective_rate": tax / total_taxable_income if total_taxable_income > 0 else 0,
    }


def uk_national_insurance(earned_income):
    """
    UK employees' Class 1 National Insurance (2024/25 thresholds).

    Applies to EARNED income only — salary. Pension income (Defined
    Benefit, State Pension, UFPLS drawdowns) is NOT subject to NI,
    which is why the engine passes `_indexed_earned_income(person, y)`
    here rather than `p1_gross` (which mixes salary with pension).

    Tiered rates:
      - Below primary threshold (£12,570): 0% (employee pays nothing)
      - Between PT and UEL: 8% on the band (main rate)
      - Above UEL (£50,270): 2% on the remainder (upper rate)

    There is no upper NI cap — high earners pay 2% on every additional £.
    Note: these are 2024/25 EMPLOYEE rates only. Employers' NI (13.8%
    above £9,100) is NOT modelled because the household is the employee,
    not the employer. Class 4 self-employed NI is also out of scope.

    Single-taxpayer semantics: this function takes one person's earned
    income. The engine sums p1_ni + p2_ni for household-level figures,
    mirroring the per-spouse pattern used by `uk_income_tax`.
    """
    PT = 12_570   # Primary threshold
    UEL = 50_270  # Upper earnings limit

    if earned_income <= PT:
        return 0.0
    if earned_income <= UEL:
        return (earned_income - PT) * 0.08
    # Above UEL: cumulative of the main band (capped) plus upper rate on
    # the rest. No ceiling above UEL — high earners pay 2% on every £.
    return (UEL - PT) * 0.08 + (earned_income - UEL) * 0.02
