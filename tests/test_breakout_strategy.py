from datetime import datetime, timezone
from decimal import Decimal

from app.core.config import SessionConfig, SymbolConfig
from app.core.enums import MarginType, PositionSide, TriggerBy
from app.core.state import Candle
from app.symbols.engine import SymbolEngine


def symbol_config() -> SymbolConfig:
    session = SessionConfig("london", "05:45", "06:15", "09:00", 345, 375, 540)
    return SymbolConfig(
        symbol="BTCUSDT",
        enabled=True,
        margin_type=MarginType.CROSS,
        leverage=20,
        wallet_percent=Decimal("5"),
        take_profit_percent=Decimal("0.5"),
        stop_loss_percent=Decimal("0.5"),
        trigger_by=TriggerBy.CONTRACT_PRICE,
        sessions=(session,),
    )


def candle(open_time: int, high: str, low: str, close: str) -> Candle:
    return Candle(open_time, Decimal(close), Decimal(high), Decimal(low), Decimal(close))


def test_first_close_above_range_emits_one_long_signal() -> None:
    routed = []
    engine = SymbolEngine(symbol_config(), on_signal=routed.append)
    engine.on_closed_candle(candle(1, "101", "99", "100"), datetime(2026, 7, 28, 5, 50, tzinfo=timezone.utc))
    engine.on_closed_candle(candle(2, "103", "98", "102"), datetime(2026, 7, 28, 6, 0, tzinfo=timezone.utc))

    first = engine.on_closed_candle(candle(3, "105", "102", "104"), datetime(2026, 7, 28, 6, 20, tzinfo=timezone.utc))
    second = engine.on_closed_candle(candle(4, "106", "103", "105"), datetime(2026, 7, 28, 6, 25, tzinfo=timezone.utc))

    assert len(first) == 1
    assert first[0].side is PositionSide.LONG
    assert first[0].range_high == Decimal("103")
    assert second == []
    assert routed == first


def test_wick_without_close_outside_range_does_not_signal() -> None:
    engine = SymbolEngine(symbol_config())
    engine.on_closed_candle(candle(1, "101", "99", "100"), datetime(2026, 7, 28, 5, 50, tzinfo=timezone.utc))
    signals = engine.on_closed_candle(candle(2, "105", "100", "101"), datetime(2026, 7, 28, 6, 20, tzinfo=timezone.utc))
    assert signals == []


def test_close_below_range_emits_short_signal() -> None:
    engine = SymbolEngine(symbol_config())
    engine.on_closed_candle(candle(1, "101", "99", "100"), datetime(2026, 7, 28, 5, 50, tzinfo=timezone.utc))
    signals = engine.on_closed_candle(candle(2, "99", "97", "98"), datetime(2026, 7, 28, 6, 20, tzinfo=timezone.utc))
    assert signals[0].side is PositionSide.SHORT
