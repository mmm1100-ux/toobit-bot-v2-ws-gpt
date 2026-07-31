from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import requests


class ToobitApiError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, ambiguous: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.ambiguous = ambiguous


class ToobitPrivateClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str, recv_window: int = 5000, timeout: float = 10.0) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.timeout = timeout
        self.session = requests.Session()

    def _signed(self, method: str, path: str, params: Mapping[str, Any] | None = None) -> Any:
        ordered = dict(params or {})
        ordered["timestamp"] = int(time.time() * 1000)
        ordered["recvWindow"] = self.recv_window
        payload = urlencode([(key, str(value)) for key, value in ordered.items()])
        signature = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        body = f"{payload}&signature={signature}"
        headers = {"X-BB-APIKEY": self.api_key, "Content-Type": "application/x-www-form-urlencoded"}
        try:
            if method == "GET":
                response = self.session.get(f"{self.base_url}{path}?{body}", headers=headers, timeout=self.timeout)
            else:
                response = self.session.request(method, f"{self.base_url}{path}", data=body, headers=headers, timeout=self.timeout)
        except requests.Timeout as exc:
            raise ToobitApiError("Toobit request timed out", ambiguous=method != "GET") from exc
        except requests.RequestException as exc:
            raise ToobitApiError(f"Toobit transport error: {exc}", ambiguous=method != "GET") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise ToobitApiError(f"Toobit returned HTTP {response.status_code} with invalid JSON", ambiguous=method != "GET") from exc
        if response.status_code >= 400 or (isinstance(data, dict) and data.get("code") not in (None, 0, 200)):
            code = data.get("code") if isinstance(data, dict) else None
            message = data.get("msg") or data.get("message") or str(data)
            raise ToobitApiError(str(message), code=code, ambiguous=False)
        return data

    @staticmethod
    def _rows(response: Any) -> list[dict[str, Any]]:
        rows = response.get("data", response) if isinstance(response, dict) else response
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise ToobitApiError("unexpected Toobit account response")
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _normalise_margin_type(value: Any) -> str:
        margin_type = str(value or "").upper()
        if margin_type == "CROSSED":
            return "CROSS"
        return margin_type

    def balance(self) -> Any:
        return self._signed("GET", "/api/v1/futures/balance")

    def total_balance(self, coin: str = "USDT") -> Decimal:
        for row in self._rows(self.balance()):
            if str(row.get("coin", "")).upper() == coin.upper():
                return Decimal(str(row["balance"]))
        raise ToobitApiError(f"{coin} futures balance not found")

    def set_margin_type(self, symbol: str, margin_type: str) -> Any:
        return self._signed("POST", "/api/v1/futures/marginType", {"symbol": symbol, "marginType": margin_type})

    def set_leverage(self, symbol: str, leverage: int) -> Any:
        return self._signed("POST", "/api/v1/futures/leverage", {"symbol": symbol, "leverage": leverage})

    def account_leverage(self, symbol: str) -> dict[str, Any]:
        response = self._signed("GET", "/api/v1/futures/accountLeverage", {"symbol": symbol})
        requested = symbol.upper()
        for row in self._rows(response):
            row_symbol = str(row.get("symbolId", row.get("symbol", ""))).upper()
            if row_symbol == requested:
                return row
        raise ToobitApiError(f"Toobit account leverage settings not found for {symbol}")

    def ensure_symbol_configuration(
        self,
        symbol: str,
        margin_type: str,
        leverage: int,
        *,
        verification_attempts: int = 3,
        verification_delay_seconds: float = 0.25,
    ) -> dict[str, Any]:
        """Apply margin mode/leverage only when needed, then read back and verify.

        No opening order should be submitted unless this method returns successfully.
        Ambiguous POST timeouts are reconciled through the signed read endpoint.
        """
        expected_margin = self._normalise_margin_type(margin_type)
        expected_leverage = int(leverage)
        if expected_margin not in {"CROSS", "ISOLATED"}:
            raise ToobitApiError(f"unsupported margin type for {symbol}: {margin_type}")
        if expected_leverage <= 0:
            raise ToobitApiError(f"invalid leverage for {symbol}: {leverage}")

        current = self.account_leverage(symbol)
        current_margin = self._normalise_margin_type(current.get("marginType"))
        try:
            current_leverage = int(str(current.get("leverage")))
        except (TypeError, ValueError) as exc:
            raise ToobitApiError(f"invalid leverage returned by Toobit for {symbol}") from exc

        if current_margin != expected_margin:
            try:
                self.set_margin_type(symbol, expected_margin)
            except ToobitApiError as exc:
                if not exc.ambiguous:
                    raise

        if current_leverage != expected_leverage:
            try:
                self.set_leverage(symbol, expected_leverage)
            except ToobitApiError as exc:
                if not exc.ambiguous:
                    raise

        attempts = max(1, int(verification_attempts))
        last: dict[str, Any] | None = None
        for attempt in range(attempts):
            if attempt and verification_delay_seconds > 0:
                time.sleep(verification_delay_seconds)
            last = self.account_leverage(symbol)
            actual_margin = self._normalise_margin_type(last.get("marginType"))
            try:
                actual_leverage = int(str(last.get("leverage")))
            except (TypeError, ValueError):
                actual_leverage = -1
            if actual_margin == expected_margin and actual_leverage == expected_leverage:
                return last

        actual_margin = self._normalise_margin_type((last or {}).get("marginType")) or "UNKNOWN"
        actual_leverage = (last or {}).get("leverage", "UNKNOWN")
        raise ToobitApiError(
            f"refusing to trade {symbol}: requested margin/leverage "
            f"{expected_margin}/{expected_leverage}x but Toobit reports "
            f"{actual_margin}/{actual_leverage}x"
        )

    def configure_symbol(self, symbol: str, margin_type: str, leverage: int) -> None:
        self.ensure_symbol_configuration(symbol, margin_type, leverage)

    def place_market_order(self, **params: Any) -> Any:
        return self._signed("POST", "/api/v1/futures/order", params)

    def query_order(self, client_order_id: str) -> Any:
        return self._signed("GET", "/api/v1/futures/order", {"origClientOrderId": client_order_id, "type": "LIMIT"})

    def open_orders(self, symbol: str, order_type: str | None = None) -> Any:
        params: dict[str, Any] = {"symbol": symbol, "limit": 1000}
        if order_type:
            params["type"] = order_type
        return self._signed("GET", "/api/v1/futures/openOrders", params)

    def cancel_all_orders(self, symbol: str) -> Any:
        # Toobit requires BUY/SELL. Cancel both directions so entry, close, stop and TP/SL orders are covered.
        results = []
        errors: list[ToobitApiError] = []
        benign_codes = {-2011, -2013, -3145}
        for side in ("BUY", "SELL"):
            try:
                results.append(self._signed("DELETE", "/api/v1/futures/batchOrders", {"symbol": symbol, "side": side}))
            except ToobitApiError as exc:
                if exc.code not in benign_codes:
                    errors.append(exc)
        if errors:
            ambiguous = any(error.ambiguous for error in errors)
            code = errors[0].code if all(error.code == errors[0].code for error in errors) else None
            raise ToobitApiError("; ".join(str(error) for error in errors), code=code, ambiguous=ambiguous)
        return results

    def positions(self, symbol: str, side: str | None = None) -> Any:
        params: dict[str, Any] = {"symbol": symbol}
        if side:
            params["side"] = side
        return self._signed("GET", "/api/v1/futures/positions", params)

    def flash_close(self, symbol: str, side: str, client_order_id: str | None = None) -> Any:
        params: dict[str, Any] = {"symbol": symbol, "side": side}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        return self._signed("POST", "/api/v1/futures/flashClose", params)
