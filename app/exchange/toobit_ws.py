from __future__ import annotations

import json
import logging
import random
import threading
from collections.abc import Callable, Iterable
from decimal import Decimal

import websocket

from app.market.candle import Candle

LOGGER = logging.getLogger(__name__)


class ToobitMarketWebSocket:
    def __init__(
        self,
        symbols: Iterable[str],
        interval: str,
        on_candle: Callable[[Candle], None],
        url: str = "wss://stream.toobit.com/quote/ws/v1",
        max_backoff_seconds: float = 30.0,
        on_price: Callable[[str, Decimal], None] | None = None,
    ) -> None:
        self.symbols = tuple(dict.fromkeys(symbols))
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        self.interval = interval
        self.on_candle = on_candle
        self.on_price = on_price
        self.url = url
        self.max_backoff_seconds = max_backoff_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._app: websocket.WebSocketApp | None = None
        self._pending: dict[str, Candle] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="toobit-market-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._app:
            self._app.close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            opened = False

            def on_open(ws: websocket.WebSocketApp) -> None:
                nonlocal opened
                opened = True
                request = {
                    "symbol": ",".join(self.symbols),
                    "topic": f"kline_{self.interval}",
                    "event": "sub",
                    "params": {"binary": False},
                }
                ws.send(json.dumps(request))
                LOGGER.info(
                    "market_websocket_subscribed",
                    extra={
                        "event": "market_websocket_subscribed",
                        "symbols": list(self.symbols),
                        "interval": self.interval,
                        "topic": request["topic"],
                    },
                )

            self._app = websocket.WebSocketApp(
                self.url,
                on_open=on_open,
                on_message=lambda _ws, message: self._handle_message(message),
                on_error=lambda _ws, error: LOGGER.warning("market websocket error: %s", error),
                on_close=lambda _ws, code, reason: LOGGER.info("market websocket closed: %s %s", code, reason),
            )
            try:
                self._app.run_forever(ping_interval=120, ping_timeout=20)
            except Exception:
                LOGGER.exception("market websocket loop failed")
            if self._stop.is_set():
                break
            failures = 0 if opened else failures + 1
            delay = min(self.max_backoff_seconds, 2 ** min(failures, 5)) + random.random()
            LOGGER.warning(
                "market_websocket_reconnect_scheduled",
                extra={"event": "market_websocket_reconnect_scheduled", "delay_seconds": round(delay, 3)},
            )
            self._stop.wait(delay)

    def _handle_message(self, raw: str | bytes) -> None:
        message = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        if "ping" in message:
            if self._app:
                self._app.send(json.dumps({"pong": message["ping"]}))
            return
        if message.get("event") or message.get("code") is not None:
            LOGGER.info("market_websocket_response", extra={"event": "market_websocket_response", "response": message})
        data = message.get("data")
        if not isinstance(data, list):
            return
        for item in data:
            if not isinstance(item, dict) or not {"t", "s", "o", "h", "l", "c"} <= item.keys():
                continue
            candle = Candle.from_ws(self.interval, item)
            if self.on_price is not None:
                self.on_price(candle.symbol, candle.close)
            previous = self._pending.get(candle.symbol)
            if previous is not None and candle.open_time_ms > previous.open_time_ms:
                LOGGER.info(
                    "market_candle_closed",
                    extra={
                        "event": "market_candle_closed",
                        "symbol": previous.symbol,
                        "interval": previous.interval,
                        "open_time_ms": previous.open_time_ms,
                        "close_time_ms": previous.close_time_ms,
                        "open": str(previous.open),
                        "high": str(previous.high),
                        "low": str(previous.low),
                        "close": str(previous.close),
                        "volume": str(previous.volume),
                    },
                )
                self.on_candle(previous)
            if previous is None or candle.open_time_ms >= previous.open_time_ms:
                self._pending[candle.symbol] = candle
