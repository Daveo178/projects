from dataclasses import dataclass


@dataclass
class Mortgage:
    """UK-style repayment mortgage for the household.

    Field semantics
    ---------------
    `outstanding`        : £ remaining on the loan at the start of the next
                            simulation step. Reassigned in-place as the engine
                            amortises the loan (interest accrual then payment).
    `rate`               : quoted annual interest rate, decimal (e.g. 0.0458
                            for 4.58%).
    `end_year`           : simulator-year at which the LOAN ENDS. Now a
                            `float` so the Assets page can enter fractional
                            terms (e.g. `9 years 6 months` → `9.5`). Engine
                            amortises a partial-year slice in the closing
                            year. Integer values still work (legacy data
                            loads unchanged).
    `annual_payment`     : £-per-year regular payment the household pays
                            toward this mortgage. Today the Assets page
                            form is monthly; the page multiplies by 12 on
                            save so the storage + dataclass + engine all
                            stay in annual cadence.
    `annual_overpayment` : £-per-year voluntary overpayment on top of the
                            regular payment. Same monthly→annual cadence
                            via the Assets page form.

    `include_in_spending` : spending-figure flag. When True the user's
                            `Household.spending_target` figure ALREADY
                            covers the mortgage payment — the engine's
                            `total_need = spending` (the mortgage is paid
                            out of the spending figure, NOT on top of it),
                            and the Income/Spending chart helper shows the
                            single combined Spending series. When False
                            (default) spending is lifestyle-only, the
                            engine funds `total_need = spending +
                            mortgage_paid`, and the chart shows Spending
                            + a separate Mortgage Payment line. The flag
                            therefore drives BOTH the engine's drawdown
                            target and the chart display — flip it and
                            the income bars move to match the new target.
    """
    outstanding: float
    rate: float
    end_year: float
    # Back-compat defaults: legacy saved plans without these keys still
    # construct and behave like a payment-free, interest-only mortgage.
    # NOTE: `include_in_spending` is added AFTER the existing annual_*
    # defaults so Python's "non-default after default" rule is honoured
    # for `Mortgage(**data)` unpacking anywhere in the codebase.
    annual_payment: float = 0.0
    annual_overpayment: float = 0.0
    include_in_spending: bool = False

    def apply_interest(self, fraction: float = 1.0):
        """Apply `rate` × `fraction` years of interest to `outstanding`.

        `fraction` defaults to `1.0` for a full-year amortisation step.
        The engine passes `min(1.0, end_year - current_year)` so a
        closing-year slice (e.g. 0.5 for a 9y6m mortgage in year 9)
        accrues `(1 + rate * 0.5)` rather than `(1 + rate)**0.5` — the
        simple-interest slice is what `min(planned, outstanding)` was
        already designed around, and it's exact for the linear UK
        repayment-mortgage cadence. Returning the post-interest balance
        keeps the existing call-site API unchanged.
        """
        self.outstanding *= (1 + self.rate * fraction)
        return self.outstanding

    def is_active(self, current_year: int):
        # Stops accruing interest once the term is up OR the debt has been
        # cleared (e.g., by overpaying, downsizing, or starting at 0).
        # `end_year` may be fractional; `current_year` is always an int,
        # so the strict `<` comparison naturally handles partial-year
        # terms (year < 9.5 is True when year=9, False when year=10).
        return current_year < self.end_year and self.outstanding > 0
