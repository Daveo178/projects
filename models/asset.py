from dataclasses import dataclass

@dataclass
class Asset:
    name: str
    value: float
    growth_rate: float
    asset_type: str  # "ISA", "GIA", "Cash", "Property", "DC"
    contribution_until_retirement: float = 0.0

    def grow(self):
        self.value *= (1 + self.growth_rate)
        return self.value
