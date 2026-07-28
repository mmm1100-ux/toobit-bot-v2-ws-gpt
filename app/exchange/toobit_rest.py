from __future__ import annotations

from collections.abc import Sequence

import requests

from app.market.candle import Candle


class ToobitRestClient:
    def __init__(self, base_url: str = "https://api.toobit.com", timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._session = requests.Session()

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 1000,
    ) -> list[Candle]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        params: dict[str, object] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        response = self._session.get(
            f"{self._base_url}/quote/v1/klines",
            params=params,
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes, dict)):
            raise ValueError("unexpected Toobit klines response")
        candles = [Candle.from_rest(symbol, interval, list(row)) for row in payload]
        return sorted(candles, key=lambda candle: candle.open_time_ms)
