from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import MarginType, SessionConfig, SymbolConfig, TriggerBy
from app.core.state import Candle
from app.symbols.engine import SymbolEngine


def config() -> SymbolConfig:
    return SymbolConfig(
        symbol="ADA-SWAP-USDT",
        enabled=True,
        margin_type=MarginType.CROSS,
        leverage=20,
        wallet_percent=Decimal("5"),
        take_profit_percent=Decimal("0.5"),
        stop_loss_percent=Decimal("0.5"),
        trigger_by=TriggerBy.CONTRACT_PRICE,
        sessions=(
            SessionConfig("morning", "05:45", "06:15", "09:00", 345, 375, 540),
        ),
    )


def candle(open_time: int, high: str, low: str, close: str = "1") -> Candle:
    return Candle(open_time, Decimal("1"), Decimal(high), Decimal(low), Decimal(close))


def test_range_uses_closed_candle_shadows() -> None:
    engine = SymbolEngine(config())
    engine.on_closed_candle(
        candle(1, "1.20", "0.90"),
        datetime(2026, 7, 28, 5, 45, tzinfo=timezone.utc),
    )
    engine.on_closed_candle(
        candle(2, "1.30", "0.80"),
        datetime(2026, 7, 28, 6, 10, tzinfo=timezone.utc),
    )
    engine.on_closed_candle(
        candle(3, "1.10", "1.00"),
        datetime(2026, 7, 28, 6, 15, tzinfo=timezone.utc),
    )
    state = engine.session_state("morning", "2026-07-28")
    assert state.range_high == Decimal("1.30")
    assert state.range_low == Decimal("0.80")


def test_failed_signal_callback_releases_reservation() -> None:
    engine = SymbolEngine(config(), on_signal=lambda _signal: (_ for _ in ()).throw(RuntimeError("entry failed")))
    engine.on_closed_candle(
        candle(1, "1.20", "0.90", "1.00"),
        datetime(2026, 7, 28, 5, 45, tzinfo=timezone.utc),
    )
    engine.on_closed_candle(
        candle(2, "1.30", "0.80", "1.00"),
        datetime(2026, 7, 28, 6, 10, tzinfo=timezone.utc),
    )

    with pytest.raises(RuntimeError, match="entry failed"):
        engine.on_closed_candle(
            candle(3, "1.40", "1.10", "1.40"),
            datetime(2026, 7, 28, 6, 15, tzinfo=timezone.utc),
        )

    state = engine.session_state("morning", "2026-07-28")
    assert state.signal_emitted is False
    assert state.signal_candle_open_time is None
    assert state.direction is None
    assert state.signal_price is None
    assert state.trade_committed is False


def test_expire_is_returned_once() -> None:
    engine = SymbolEngine(config())
    now = datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
    due = engine.due_expirations(now)
    assert len(due) == 1
    due[0][1].expire()
    assert engine.due_expirations(now) == []
