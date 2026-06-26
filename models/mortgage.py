from dataclasses import dataclass

@dataclass
class Mortgage:
    outstanding: float
    rate: float
    end_year: int

    def apply_interest(self):
        self.outstanding *= (1 + self.rate)
        return self.outstanding

    def is_active(self, current_year: int):
        return current_year < self.end_year
