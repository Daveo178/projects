def uk_income_tax(earned_income, taxable_drawdown=0):
    """
    UK income tax model (2024/25).
    earned_income = salary + DB + state pension
    taxable_drawdown = taxable portion of DC withdrawals (UFPLS)
    """

    total_taxable_income = earned_income + taxable_drawdown

    personal_allowance = 12570
    basic_rate_limit = 50270
    higher_rate_limit = 125140

    # Personal allowance tapering
    if total_taxable_income > 100000:
        reduction = (total_taxable_income - 100000) // 2
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
