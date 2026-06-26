from dataclasses import dataclass

@dataclass
class LifeEvent:
    year: int
    description: str
    amount: float  # positive = money in, negative = money out

@dataclass
class DownsizingEvent:
    year: int
    sell_property_value: float
    new_property_value: float
    description: str = "Downsizing"