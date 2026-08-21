from dataclasses import dataclass, field
from typing import List

@dataclass
class Asset:
    name: str
    value: float
    growth_rate: float
    asset_type: str  # "ISA", "GIA", "Cash", "Property", "DC"
    contribution_until_retirement: float = 0.0

    # Monte Carlo per-year growth path. When NON-EMPTY, the engine uses
    # `growth_path[year]` instead of the scalar `growth_rate` for that
    # year's appreciation, so each simulation year gets its own sampled
    # return (sequence-of-returns risk). Deterministic runs and legacy
    # plans leave this empty and keep using `growth_rate`. Simulation-
    # internal only — never serialised into saved plans.
    growth_path: List[float] = field(default_factory=list)

    def grow(self):
        self.value *= (1 + self.growth_rate)
        return self.value
