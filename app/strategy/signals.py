from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.enums import PositionSide


@dataclass(frozen=True, slots=True)
class TradeSignal:
    symbol: str
    session_name: str
    trading_date: str
    side: PositionSide
    close_price: Decimal
    range_high: Decimal
    range_low: Decimal
    candle_open_time: int

    @property
    def session_key(self) -> str:
        return f"{self.trading_date}:{self.session_name}"
