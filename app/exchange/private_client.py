from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
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

    def balance(self) -> Any:
        return self._signed("GET", "/api/v1/futures/balance")

    def place_market_order(self, **params: Any) -> Any:
        return self._signed("POST", "/api/v1/futures/order", params)

    def query_order(self, client_order_id: str) -> Any:
        return self._signed("GET", "/api/v1/futures/order", {"origClientOrderId": client_order_id, "type": "LIMIT"})
