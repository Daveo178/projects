from dataclasses import dataclass, field
from typing import List, Union
from .person import Person
from .asset import Asset
from .mortgage import Mortgage
from .events import LifeEvent, DownsizingEvent

@dataclass
class Household:
    person1: Person
    person2: Person
    assets: List[Asset] = field(default_factory=list)
    mortgage: Mortgage = None
    spending_target: float = 0.0
    drawdown_amount: float = 0.0
    drawdown_strategy: str = "Fixed"

    # This list now supports BOTH LifeEvent and DownsizingEvent
    events: List[Union[LifeEvent, DownsizingEvent]] = field(default_factory=list)

    def total_assets(self):
        return sum(a.value for a in self.assets)

    def ages_in_year(self, year_offset: int):
        return {
            self.person1.name: self.person1.age + year_offset,
            self.person2.name: self.person2.age + year_offset
        }
