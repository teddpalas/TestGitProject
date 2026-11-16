from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal


@dataclass
class Listing:
    text: str
    rooms: int | None = None
    area_m2: float | None = None
    price_usd: float | None = None
    commissioned_on: date | None = None
    commissioned_year: int | None = None
    previously_occupied: bool | None = None
    is_new_building: bool | None = None
    is_long_term: bool | None = None
    is_rental: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    walking_minutes: float | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    tier: Literal["loud", "quiet", "reject"]
    reasons: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    deviations: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)
