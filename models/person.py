from dataclasses import dataclass, field
from typing import List
from .events import LifeEvent

@dataclass
class Person:
    name: str
    age: int
    retirement_age: int
    state_pension_age: int
    dc_pot: float
    db_income: float = 0.0
    draw_age: int = 60               # age at which DB pension begins paying
    monthly_contrib: float = 0.0
    income_until_retirement: float = 0.0

    # Flexible PCLS (UFPLS-style)
    pcls_percent: int = 0          # 0–25% chosen by user
    pcls_taken: float = 0.0        # how much tax-free has been used
    pcls_available: float = 0.0    # total tax-free allowance (set at retirement)

    # Market growth assumptions. Defaults keep legacy `household_data.json`
    # files (saved before these fields existed) constructing cleanly without
    # explicitly serialised keys. Mean values are nominal:
    #   - DC: 5% (long-run balanced portfolio nominal return)
    #   - DB: 2.5% (typical RPI / CPI indexation)
    #   - State Pension: 2.5% (typical triple-lock-rate approximate)
    dc_growth_rate: float = 0.05
    db_growth_rate: float = 0.025
    state_pension_growth_rate: float = 0.025

    # Wage-inflation indexation applied to `income_until_retirement` from today
    # until the partner reaches `retirement_age`. Default 2.5% — typical UK
    # wage inflation. Compounds annually on the base figure, stops at retirement.
    income_growth_rate: float = 0.025

    # Monthly DC contribution as a percentage of (income-indexed) annual
    # earnings. The Pensions page exposes this as a slider (default 15% — a
    # realistic combined employee + employer total pension contribution). When
    # 0.0, the engine falls back to the legacy `monthly_contrib` £ figure so
    # saved plans targeting a £ amount continue to work unchanged. The
    # Pensions page performs a soft migration that auto-derives a % from a
    # legacy £ month figure the first time a user with stored data opens it.
    monthly_contrib_pct: float = 0.0

    life_events: List[LifeEvent] = field(default_factory=list)

    def years_to_retirement(self):
        return max(0, self.retirement_age - self.age)

    def is_retired(self, year_offset: int):
        return (self.age + year_offset) >= self.retirement_age

    def is_db_active(self, year_offset: int):
        """True once this person has reached their DB pension draw age."""
        return (self.age + year_offset) >= self.draw_age
