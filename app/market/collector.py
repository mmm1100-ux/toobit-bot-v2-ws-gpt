from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from app.market.candle import Candle, interval_to_milliseconds


class CandleCollector:
    def __init__(self, interval: str, recovery_fetcher: Callable[..., list[Candle]]) -> None:
        self.interval = interval
        self._interval_ms = interval_to_milliseconds(interval)
        self._fetch = recovery_fetcher
        self._candles: dict[tuple[str, int], Candle] = {}
        self._lock = RLock()

    def contains(self, symbol: str, open_time_ms: int) -> bool:
        with self._lock:
            return (symbol, open_time_ms) in self._candles

    def ingest(self, candle: Candle) -> list[Candle]:
        if candle.interval != self.interval:
            raise ValueError("candle interval does not match collector")
        recovered: list[Candle] = []
        with self._lock:
            previous = self._latest_for(candle.symbol)
            if previous and candle.open_time_ms > previous.open_time_ms + self._interval_ms:
                recovered = self.recover(
                    candle.symbol,
                    previous.open_time_ms + self._interval_ms,
                    candle.open_time_ms - 1,
                )
            self._candles[(candle.symbol, candle.open_time_ms)] = candle
        return recovered

    def recover(self, symbol: str, start_time_ms: int, end_time_ms: int) -> list[Candle]:
        if end_time_ms < start_time_ms:
            return []
        expected = ((end_time_ms - start_time_ms) // self._interval_ms) + 1
        rows = self._fetch(
            symbol=symbol,
            interval=self.interval,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=min(expected, 1000),
        )
        accepted: list[Candle] = []
        for candle in rows:
            if start_time_ms <= candle.open_time_ms <= end_time_ms:
                self._candles[(symbol, candle.open_time_ms)] = candle
                accepted.append(candle)
        return sorted(accepted, key=lambda item: item.open_time_ms)

    def range(self, symbol: str, start_time_ms: int, end_time_ms: int) -> list[Candle]:
        with self._lock:
            return sorted(
                (
                    candle
                    for (item_symbol, _), candle in self._candles.items()
                    if item_symbol == symbol and start_time_ms <= candle.open_time_ms < end_time_ms
                ),
                key=lambda item: item.open_time_ms,
            )

    def _latest_for(self, symbol: str) -> Candle | None:
        candidates = [c for (item_symbol, _), c in self._candles.items() if item_symbol == symbol]
        return max(candidates, key=lambda item: item.open_time_ms, default=None)
