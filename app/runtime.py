from __future__ import annotations

import logging
import signal
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from app.core.config import BotConfig
from app.core.engine import TradingEngine
from app.core.state import Candle as StateCandle
from app.exchange.private_client import ToobitPrivateClient
from app.exchange.toobit_rest import ToobitRestClient
from app.exchange.toobit_ws import ToobitMarketWebSocket
from app.expire.coordinator import ExpireCoordinator
from app.expire.manager import ExpireManager
from app.market.candle import Candle
from app.market.collector import CandleCollector
from app.orders.execution import SignalExecutor
from app.orders.manager import OrderManager
from app.orders.models import ContractRules
from app.storage.state_store import AtomicStateStore
from app.strategy.signals import TradeSignal

LOGGER = logging.getLogger(__name__)


class BotRuntime:
    """Coordinates market data, strategy, orders, expiration, and persistence."""

    def __init__(
        self,
        config: BotConfig,
        *,
        state_store: AtomicStateStore,
        rest_client: ToobitRestClient | None = None,
        private_client: ToobitPrivateClient | None = None,
        contract_rules: dict[str, ContractRules] | None = None,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 1.0,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.state = state_store.load()
        self.engine = TradingEngine(config, self.state)
        self.rest = rest_client or ToobitRestClient(config.exchange.base_url)
        self.private = private_client or ToobitPrivateClient(
            config.exchange.api_key,
            config.exchange.api_secret,
            config.exchange.base_url,
            config.exchange.recv_window,
        )
        self.collector = CandleCollector(config.runtime.timeframe, self.rest.fetch_klines)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._lock = threading.RLock()

        rules = contract_rules or {}
        self.signal_executor = SignalExecutor(OrderManager(self.private, rules)) if rules else None
        self.expire = ExpireCoordinator(ExpireManager(self.private))
        for symbol, symbol_engine in self.engine.symbols.items():
            symbol_engine.on_signal = self._on_signal

        self.ws = ToobitMarketWebSocket(
            self.engine.symbols.keys(),
            config.runtime.timeframe,
            self._on_market_candle,
            url=config.exchange.ws_url,
        )

    def _persist(self) -> None:
        self.state_store.save(self.state)

    def _on_market_candle(self, candle: Candle) -> None:
        with self._lock:
            recovered = self.collector.ingest(candle)
            for item in [*recovered, candle]:
                self._route_closed_candle(item)
            self._persist()

    def _route_closed_candle(self, candle: Candle) -> None:
        engine = self.engine.symbols.get(candle.symbol)
        if engine is None:
            return
        opened_at = datetime.fromtimestamp(candle.open_time_ms / 1000, tz=timezone.utc)
        engine.on_closed_candle(
            StateCandle(
                open_time=candle.open_time_ms,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
            ),
            opened_at,
        )

    def _on_signal(self, signal: TradeSignal) -> None:
        symbol_engine = self.engine.symbols[signal.symbol]
        state = symbol_engine.state.sessions[signal.session_key]
        if self.config.runtime.dry_run:
            LOGGER.info("dry_run_signal", extra={"event": "dry_run_signal", "symbol": signal.symbol, "session": signal.session_name})
            self._persist()
            return
        if self.signal_executor is None:
            raise RuntimeError("live mode requires contract rules")
        wallet = self.private.total_balance()
        self.signal_executor.execute(signal, symbol_engine.config, state, wallet)
        self._persist()

    def run_expirations_once(self, now: datetime | None = None) -> None:
        with self._lock:
            current = now or self.clock()
            for engine in self.engine.symbols.values():
                if self.config.runtime.dry_run:
                    for _, state in engine.due_expirations(current):
                        state.expire()
                else:
                    self.expire.run_due(engine, current)
            self._persist()

    def run_forever(self) -> None:
        self._install_signal_handlers()
        self.ws.start()
        LOGGER.info("bot_started", extra={"event": "bot_started"})
        try:
            while not self._stop.wait(self.poll_seconds):
                self.run_expirations_once()
        finally:
            self.ws.stop()
            self._persist()
            LOGGER.info("bot_stopped", extra={"event": "bot_stopped"})

    def stop(self) -> None:
        self._stop.set()

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
