from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP


@dataclass(frozen=True, slots=True)
class ContractRules:
    step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    tick_size: Decimal

    def floor_quantity(self, value: Decimal) -> Decimal:
        units = (value / self.step_size).to_integral_value(rounding=ROUND_DOWN)
        return units * self.step_size

    def round_price(self, value: Decimal) -> Decimal:
        units = (value / self.tick_size).to_integral_value(rounding=ROUND_HALF_UP)
        return units * self.tick_size


@dataclass(frozen=True, slots=True)
class EntryPlan:
    client_order_id: str
    quantity: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    side: str
