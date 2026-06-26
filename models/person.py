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
    monthly_contrib: float = 0.0
    income_until_retirement: float = 0.0

    # Flexible PCLS (UFPLS-style)
    pcls_percent: int = 0          # 0–25% chosen by user
    pcls_taken: float = 0.0        # how much tax-free has been used
    pcls_available: float = 0.0    # total tax-free allowance (set at retirement)

    life_events: List[LifeEvent] = field(default_factory=list)

    def years_to_retirement(self):
        return max(0, self.retirement_age - self.age)

    def is_retired(self, year_offset: int):
        return (self.age + year_offset) >= self.retirement_age
