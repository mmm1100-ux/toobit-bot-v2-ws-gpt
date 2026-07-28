from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    symbol: str
    side: str
    position: Decimal
    available: Decimal

    @property
    def is_open(self) -> bool:
        return self.position.copy_abs() > 0


@dataclass(slots=True)
class ExpireReport:
    symbol: str
    canceled_orders: bool = False
    positions_before: list[PositionSnapshot] = field(default_factory=list)
    close_order_ids: list[str] = field(default_factory=list)
    positions_after: list[PositionSnapshot] = field(default_factory=list)
    verified_flat: bool = False
    attempts: int = 0
    notes: list[str] = field(default_factory=list)
