from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal

import requests

from app.market.candle import Candle
from app.orders.models import ContractRules


class ToobitRestClient:
    def __init__(self, base_url: str = "https://api.toobit.com", timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._session = requests.Session()

    def fetch_exchange_info(self) -> dict:
        response = self._session.get(
            f"{self._base_url}/api/v1/exchangeInfo",
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("unexpected Toobit exchangeInfo response")
        return payload

    def fetch_contract_rules(self, symbols: Iterable[str]) -> dict[str, ContractRules]:
        requested = {str(symbol).upper() for symbol in symbols}
        if not requested:
            return {}

        payload = self.fetch_exchange_info()
        contracts = payload.get("contracts")
        if not isinstance(contracts, list):
            raise ValueError("Toobit exchangeInfo response is missing contracts")

        rules: dict[str, ContractRules] = {}
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            symbol = str(contract.get("symbol", "")).upper()
            if symbol not in requested:
                continue
            status = str(contract.get("status", "")).upper()
            if status != "TRADING":
                raise ValueError(f"Toobit contract {symbol} is not tradable: {status or 'UNKNOWN'}")

            filters = contract.get("filters")
            if not isinstance(filters, list):
                raise ValueError(f"Toobit contract {symbol} is missing filters")
            by_type = {
                str(item.get("filterType", "")): item
                for item in filters
                if isinstance(item, dict)
            }
            price_filter = by_type.get("PRICE_FILTER")
            lot_filter = by_type.get("LOT_SIZE")
            notional_filter = by_type.get("MIN_NOTIONAL")
            if not isinstance(price_filter, dict) or not isinstance(lot_filter, dict) or not isinstance(notional_filter, dict):
                raise ValueError(f"Toobit contract {symbol} has incomplete trading filters")

            try:
                parsed = ContractRules(
                    step_size=Decimal(str(lot_filter["stepSize"])),
                    min_quantity=Decimal(str(lot_filter["minQty"])),
                    min_notional=Decimal(str(notional_filter["minNotional"])),
                    tick_size=Decimal(str(price_filter["tickSize"])),
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Toobit contract {symbol} has invalid trading filters") from exc
            if min(parsed.step_size, parsed.min_quantity, parsed.min_notional, parsed.tick_size) <= 0:
                raise ValueError(f"Toobit contract {symbol} has non-positive trading filters")
            rules[symbol] = parsed

        missing = sorted(requested - rules.keys())
        if missing:
            raise ValueError(f"Toobit exchangeInfo did not return contract rules for: {', '.join(missing)}")
        return rules

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
