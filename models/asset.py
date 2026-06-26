from dataclasses import dataclass

@dataclass
class Asset:
    name: str
    value: float
    growth_rate: float
    asset_type: str  # "ISA", "GIA", "Cash", "Property", "DC"

    def grow(self):
        self.value *= (1 + self.growth_rate)
        return self.value
