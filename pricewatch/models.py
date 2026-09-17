from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Observation:
    """One look at one product at one moment. This is the unit the whole swarm passes around.

    `price_cents` is always the price of the *pack* actually being sold (not the per-unit
    price) for the default / selected variant, in minor units of `currency`.
    """

    store: str
    product_id: str
    url: str
    name: str
    price_cents: Optional[int]
    currency: str
    compare_at_cents: Optional[int] = None
    availability: str = "unknown"  # in_stock | out_of_stock | unknown
    pack_size: int = 1
    unit_price_cents: Optional[int] = None
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "rules"  # rules | llm
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Observation":
        known = {k: d.get(k) for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


@dataclass
class Alert:
    store: str
    product_id: str
    rule: str
    message: str
    previous_cents: Optional[int]
    current_cents: Optional[int]
    observed_at: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
