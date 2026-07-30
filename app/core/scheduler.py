from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from app.core.config import SessionConfig


class SessionEvent(StrEnum):
    IDLE = "IDLE"
    COLLECT = "COLLECT"
    WAIT_BREAKOUT = "WAIT_BREAKOUT"
    EXPIRE = "EXPIRE"


@dataclass(frozen=True, slots=True)
class SessionClock:
    trading_date: date
    minute: int
    event: SessionEvent


def session_clock(now: datetime, session: SessionConfig) -> SessionClock:
    minute = now.hour * 60 + now.minute
    trading_date = now.date()
    if session.crosses_midnight and minute < session.expire_minute:
        trading_date -= timedelta(days=1)

    if session.collection_start_minute <= minute < session.collection_end_minute:
        event = SessionEvent.COLLECT
    elif session.crosses_midnight:
        if minute >= session.collection_end_minute or minute < session.expire_minute:
            event = SessionEvent.WAIT_BREAKOUT
        elif session.expire_minute <= minute < session.collection_start_minute:
            event = SessionEvent.EXPIRE
        else:
            event = SessionEvent.IDLE
    elif session.collection_end_minute <= minute < session.expire_minute:
        event = SessionEvent.WAIT_BREAKOUT
    elif minute >= session.expire_minute:
        event = SessionEvent.EXPIRE
    else:
        event = SessionEvent.IDLE

    return SessionClock(trading_date=trading_date, minute=minute, event=event)
