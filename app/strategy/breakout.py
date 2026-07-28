from __future__ import annotations

from app.core.enums import PositionSide, SessionPhase
from app.core.state import Candle, SessionState
from app.strategy.signals import TradeSignal


class BreakoutStrategy:
    """Produces one close-confirmed breakout signal per session."""

    def evaluate(
        self,
        *,
        symbol: str,
        session_name: str,
        trading_date: str,
        candle: Candle,
        state: SessionState,
    ) -> TradeSignal | None:
        if state.expired or state.trade_committed:
            return None
        if state.range_high is None or state.range_low is None:
            return None
        if state.phase is not SessionPhase.WAITING_BREAKOUT:
            return None

        side: PositionSide | None = None
        if candle.close > state.range_high:
            side = PositionSide.LONG
        elif candle.close < state.range_low:
            side = PositionSide.SHORT
        if side is None:
            return None

        return TradeSignal(
            symbol=symbol,
            session_name=session_name,
            trading_date=trading_date,
            side=side,
            close_price=candle.close,
            range_high=state.range_high,
            range_low=state.range_low,
            candle_open_time=candle.open_time,
        )
