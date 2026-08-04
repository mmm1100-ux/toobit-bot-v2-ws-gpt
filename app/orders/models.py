from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP


@dataclass(frozen=True, slots=True)
class ContractRules:
    step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    tick_size: Decimal
    contract_multiplier: Decimal = Decimal("1")

    def floor_underlying_quantity(self, value: Decimal) -> Decimal:
        """Floor token quantity using exchange LOT_SIZE rules."""
        units = (value / self.step_size).to_integral_value(rounding=ROUND_DOWN)
        return units * self.step_size

    def order_quantity_for_underlying(self, value: Decimal) -> Decimal:
        """Convert token quantity to the integer contract count expected by Toobit."""
        underlying = self.floor_underlying_quantity(value)
        contracts = (underlying / self.contract_multiplier).to_integral_value(rounding=ROUND_DOWN)
        return contracts

    def underlying_quantity_for_order(self, contracts: Decimal) -> Decimal:
        return contracts * self.contract_multiplier

    def floor_quantity(self, value: Decimal) -> Decimal:
        """Backward-compatible alias for flooring token quantity."""
        return self.floor_underlying_quantity(value)

    def floor_price(self, value: Decimal) -> Decimal:
        units = (value / self.tick_size).to_integral_value(rounding=ROUND_FLOOR)
        return units * self.tick_size

    def ceil_price(self, value: Decimal) -> Decimal:
        units = (value / self.tick_size).to_integral_value(rounding=ROUND_CEILING)
        return units * self.tick_size

    def round_price(self, value: Decimal) -> Decimal:
        """Backward-compatible nearest-tick rounding."""
        units = (value / self.tick_size).to_integral_value(rounding=ROUND_HALF_UP)
        return units * self.tick_size


@dataclass(frozen=True, slots=True)
class EntryPlan:
    client_order_id: str
    quantity: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    side: str
    fill_price: Decimal | None = None
    executed_quantity: Decimal | None = None
