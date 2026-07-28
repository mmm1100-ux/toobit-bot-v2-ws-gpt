from __future__ import annotations

from datetime import datetime

from app.core.config import SymbolConfig
from app.core.scheduler import SessionEvent, session_clock
from app.core.state import Candle, SessionState, SymbolState


class SymbolEngine:
    """Owns independent session state for one configured Toobit contract."""

    def __init__(self, config: SymbolConfig, state: SymbolState | None = None) -> None:
        self.config = config
        self.state = state or SymbolState(symbol=config.symbol)
        if self.state.symbol != config.symbol:
            raise ValueError("symbol state does not match symbol config")

    def session_state(self, session_name: str, trading_date: str) -> SessionState:
        key = f"{trading_date}:{session_name}"
        state = self.state.sessions.get(key)
        if state is None:
            state = SessionState(session_date=trading_date)
            self.state.sessions[key] = state
        return state

    def on_closed_candle(self, candle: Candle, opened_at: datetime) -> None:
        for session in self.config.sessions:
            clock = session_clock(opened_at, session)
            state = self.session_state(session.name, clock.trading_date.isoformat())
            if state.expired:
                continue
            if clock.event is SessionEvent.COLLECT:
                state.add_range_candle(candle)
            elif clock.event is SessionEvent.WAIT_BREAKOUT and state.range_high is None:
                state.finalize_range()

    def due_expirations(self, now: datetime) -> list[tuple[str, SessionState]]:
        due: list[tuple[str, SessionState]] = []
        for session in self.config.sessions:
            clock = session_clock(now, session)
            state = self.session_state(session.name, clock.trading_date.isoformat())
            if clock.event is SessionEvent.EXPIRE and not state.expired:
                due.append((session.name, state))
        return due
