from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from app.core.enums import PositionSide, SessionPhase


@dataclass(slots=True)
class Candle:
    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(slots=True)
class SessionState:
    session_date: str
    phase: SessionPhase = SessionPhase.IDLE
    range_high: Decimal | None = None
    range_low: Decimal | None = None
    range_candles: dict[int, Candle] = field(default_factory=dict)
    trade_committed: bool = False
    expired: bool = False
    direction: PositionSide | None = None
    entry_client_id: str | None = None
    quantity: Decimal | None = None
    signal_price: Decimal | None = None

    def add_range_candle(self, candle: Candle) -> None:
        self.range_candles[candle.open_time] = candle
        self.phase = SessionPhase.COLLECTING

    def finalize_range(self) -> bool:
        if not self.range_candles:
            return False
        self.range_high = max(candle.high for candle in self.range_candles.values())
        self.range_low = min(candle.low for candle in self.range_candles.values())
        self.phase = SessionPhase.WAITING_BREAKOUT
        return True

    def commit_trade(
        self,
        direction: PositionSide,
        client_id: str,
        quantity: Decimal,
        signal_price: Decimal,
    ) -> None:
        if self.trade_committed:
            raise RuntimeError("session already consumed")
        self.trade_committed = True
        self.phase = SessionPhase.TRADE_COMMITTED
        self.direction = direction
        self.entry_client_id = client_id
        self.quantity = quantity
        self.signal_price = signal_price

    def expire(self) -> None:
        self.expired = True
        self.phase = SessionPhase.EXPIRED


@dataclass(slots=True)
class SymbolState:
    symbol: str
    sessions: dict[str, SessionState] = field(default_factory=dict)


@dataclass(slots=True)
class BotState:
    version: int = 1
    symbols: dict[str, SymbolState] = field(default_factory=dict)


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (SessionPhase, PositionSide)):
        return value.value
    if isinstance(value, Candle):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, SessionState):
        data = asdict(value)
        data["range_candles"] = {
            str(key): _serialize(candle) for key, candle in value.range_candles.items()
        }
        return {key: _serialize(item) for key, item in data.items()}
    if isinstance(value, SymbolState):
        return {
            "symbol": value.symbol,
            "sessions": {key: _serialize(item) for key, item in value.sessions.items()},
        }
    if isinstance(value, BotState):
        return {
            "version": value.version,
            "symbols": {key: _serialize(item) for key, item in value.symbols.items()},
        }
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    return value


def state_to_dict(state: BotState) -> dict[str, Any]:
    return _serialize(state)
