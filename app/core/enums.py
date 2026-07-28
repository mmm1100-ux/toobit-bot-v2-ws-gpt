from __future__ import annotations

from enum import StrEnum


class SessionPhase(StrEnum):
    IDLE = "IDLE"
    COLLECTING = "COLLECTING"
    WAITING_BREAKOUT = "WAITING_BREAKOUT"
    TRADE_COMMITTED = "TRADE_COMMITTED"
    EXPIRED = "EXPIRED"


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class MarginType(StrEnum):
    CROSS = "CROSS"
    ISOLATED = "ISOLATED"


class TriggerBy(StrEnum):
    CONTRACT_PRICE = "CONTRACT_PRICE"
    MARK_PRICE = "MARK_PRICE"
