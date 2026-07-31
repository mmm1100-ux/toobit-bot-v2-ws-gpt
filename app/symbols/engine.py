from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.core.config import SymbolConfig
from app.core.scheduler import SessionEvent, session_clock
from app.core.state import Candle, SessionState, SymbolState
from app.orders.manager import OrderOutcomeUnknown
from app.strategy.breakout import BreakoutStrategy
from app.strategy.signals import TradeSignal


class SymbolEngine:
    """Owns independent session state and signal routing for one contract."""

    def __init__(
        self,
        config: SymbolConfig,
        state: SymbolState | None = None,
        *,
        strategy: BreakoutStrategy | None = None,
        on_signal: Callable[[TradeSignal], None] | None = None,
    ) -> None:
        self.config = config
        self.state = state or SymbolState(symbol=config.symbol)
        if self.state.symbol != config.symbol:
            raise ValueError("symbol state does not match symbol config")
        self.strategy = strategy or BreakoutStrategy()
        self.on_signal = on_signal

    def session_state(self, session_name: str, trading_date: str) -> SessionState:
        key = f"{trading_date}:{session_name}"
        state = self.state.sessions.get(key)
        if state is None:
            state = SessionState(session_date=trading_date)
            self.state.sessions[key] = state
        return state

    def on_closed_candle(self, candle: Candle, opened_at: datetime) -> list[TradeSignal]:
        signals: list[TradeSignal] = []
        for session in self.config.sessions:
            clock = session_clock(opened_at, session)
            state = self.session_state(session.name, clock.trading_date.isoformat())
            if state.expired:
                continue
            if clock.event is SessionEvent.COLLECT:
                state.add_range_candle(candle)
                continue
            if clock.event is not SessionEvent.WAIT_BREAKOUT:
                continue
            if state.range_high is None and not state.finalize_range():
                continue
            signal = self.strategy.evaluate(
                symbol=self.config.symbol,
                session_name=session.name,
                trading_date=clock.trading_date.isoformat(),
                candle=candle,
                state=state,
            )
            if signal is None:
                continue
            state.reserve_signal(signal.candle_open_time, signal.side, signal.close_price)
            signals.append(signal)
            if self.on_signal is not None:
                try:
                    self.on_signal(signal)
                except OrderOutcomeUnknown:
                    raise
                except Exception:
                    if state.signal_emitted and not state.trade_committed:
                        state.release_signal()
                    raise
        return signals

    def release_signal(self, signal: TradeSignal) -> None:
        state = self.state.sessions.get(signal.session_key)
        if state is None:
            raise KeyError(f"unknown session: {signal.session_key}")
        state.release_signal()

    def due_expirations(self, now: datetime) -> list[tuple[str, SessionState]]:
        due: list[tuple[str, SessionState]] = []
        for session in self.config.sessions:
            clock = session_clock(now, session)
            state = self.session_state(session.name, clock.trading_date.isoformat())
            if clock.event is SessionEvent.EXPIRE and not state.expired:
                due.append((session.name, state))
        return due
