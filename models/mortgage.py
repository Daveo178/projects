from dataclasses import dataclass

@dataclass
class Mortgage:
    outstanding: float
    rate: float
    end_year: int
    # Back-compat defaults: legacy saved plans without these keys still construct
    # and behave like a payment-free, interest-only mortgage (current behaviour).
    annual_payment: float = 0.0
    annual_overpayment: float = 0.0

    def apply_interest(self):
        self.outstanding *= (1 + self.rate)
        return self.outstanding

    def is_active(self, current_year: int):
        # Stops accruing interest once the term is up OR the debt has been
        # cleared (e.g., by overpaying, downsizing, or starting at 0).
        return current_year < self.end_year and self.outstanding > 0
