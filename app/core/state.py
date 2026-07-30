from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from app.core.enums import PositionSide, SessionPhase

CURRENT_STATE_VERSION = 2


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
    signal_emitted: bool = False
    signal_candle_open_time: int | None = None
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
        self.range_high = max(c.high for c in self.range_candles.values())
        self.range_low = min(c.low for c in self.range_candles.values())
        self.phase = SessionPhase.WAITING_BREAKOUT
        return True

    def reserve_signal(self, candle_open_time: int, direction: PositionSide, signal_price: Decimal) -> None:
        if self.signal_emitted or self.trade_committed:
            raise RuntimeError("session signal already consumed")
        self.signal_emitted = True
        self.signal_candle_open_time = candle_open_time
        self.direction = direction
        self.signal_price = signal_price

    def release_signal(self) -> None:
        if self.trade_committed:
            raise RuntimeError("cannot release a committed trade")
        self.signal_emitted = False
        self.signal_candle_open_time = None
        self.direction = None
        self.signal_price = None

    def commit_trade(self, direction: PositionSide, client_id: str, quantity: Decimal, signal_price: Decimal) -> None:
        if self.trade_committed:
            raise RuntimeError("session already consumed")
        self.signal_emitted = True
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
    version: int = CURRENT_STATE_VERSION
    symbols: dict[str, SymbolState] = field(default_factory=dict)


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (SessionPhase, PositionSide)):
        return value.value
    if isinstance(value, Candle):
        return {k: _serialize(v) for k, v in asdict(value).items()}
    if isinstance(value, SessionState):
        data = asdict(value)
        data["range_candles"] = {str(k): _serialize(v) for k, v in value.range_candles.items()}
        return {k: _serialize(v) for k, v in data.items()}
    if isinstance(value, SymbolState):
        return {"symbol": value.symbol, "sessions": {k: _serialize(v) for k, v in value.sessions.items()}}
    if isinstance(value, BotState):
        return {"version": CURRENT_STATE_VERSION, "symbols": {k: _serialize(v) for k, v in value.symbols.items()}}
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    return value


def state_to_dict(state: BotState) -> dict[str, Any]:
    return _serialize(state)


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    version = int(raw.get("version", 1))
    if version > CURRENT_STATE_VERSION:
        raise ValueError(f"state version {version} is newer than supported {CURRENT_STATE_VERSION}")
    migrated = dict(raw)
    if version == 1:
        migrated["version"] = 2
    return migrated


def state_from_dict(raw: dict[str, Any]) -> BotState:
    data = _migrate(raw)
    symbols: dict[str, SymbolState] = {}
    for symbol_key, symbol_raw in data.get("symbols", {}).items():
        sessions: dict[str, SessionState] = {}
        for session_key, item in symbol_raw.get("sessions", {}).items():
            candles = {
                int(key): Candle(
                    open_time=int(value["open_time"]),
                    open=Decimal(str(value["open"])),
                    high=Decimal(str(value["high"])),
                    low=Decimal(str(value["low"])),
                    close=Decimal(str(value["close"])),
                )
                for key, value in item.get("range_candles", {}).items()
            }
            sessions[session_key] = SessionState(
                session_date=str(item["session_date"]),
                phase=SessionPhase(item.get("phase", SessionPhase.IDLE.value)),
                range_high=_decimal(item.get("range_high")),
                range_low=_decimal(item.get("range_low")),
                range_candles=candles,
                signal_emitted=bool(item.get("signal_emitted", False)),
                signal_candle_open_time=item.get("signal_candle_open_time"),
                trade_committed=bool(item.get("trade_committed", False)),
                expired=bool(item.get("expired", False)),
                direction=PositionSide(item["direction"]) if item.get("direction") else None,
                entry_client_id=item.get("entry_client_id"),
                quantity=_decimal(item.get("quantity")),
                signal_price=_decimal(item.get("signal_price")),
            )
        symbol = str(symbol_raw.get("symbol", symbol_key))
        symbols[symbol_key] = SymbolState(symbol=symbol, sessions=sessions)
    return BotState(version=CURRENT_STATE_VERSION, symbols=symbols)
