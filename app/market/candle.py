from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @classmethod
    def from_rest(cls, symbol: str, interval: str, row: list[object]) -> "Candle":
        if len(row) < 7:
            raise ValueError("invalid Toobit kline row")
        return cls(
            symbol=symbol,
            interval=interval,
            open_time_ms=int(row[0]),
            close_time_ms=int(row[6]),
            open=Decimal(str(row[1])),
            high=Decimal(str(row[2])),
            low=Decimal(str(row[3])),
            close=Decimal(str(row[4])),
            volume=Decimal(str(row[5])),
        )

    @classmethod
    def from_ws(cls, interval: str, payload: dict[str, object]) -> "Candle":
        open_time = int(payload["t"])
        interval_ms = interval_to_milliseconds(interval)
        return cls(
            symbol=str(payload["s"]),
            interval=interval,
            open_time_ms=open_time,
            close_time_ms=open_time + interval_ms - 1,
            open=Decimal(str(payload["o"])),
            high=Decimal(str(payload["h"])),
            low=Decimal(str(payload["l"])),
            close=Decimal(str(payload["c"])),
            volume=Decimal(str(payload.get("v", "0"))),
        )


def interval_to_milliseconds(interval: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    if len(interval) < 2 or interval[-1] not in units:
        raise ValueError(f"unsupported interval: {interval}")
    value = int(interval[:-1])
    if value <= 0:
        raise ValueError("interval must be positive")
    return value * units[interval[-1]]
