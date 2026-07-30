from __future__ import annotations

import logging
import signal
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

from app.core.config import BotConfig, SessionConfig
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
        self.local_timezone = ZoneInfo(config.runtime.timezone)
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
        self.clock = clock or (lambda: datetime.now(self.local_timezone))
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._latest_prices: dict[str, tuple[Decimal, datetime]] = {}
        self._next_heartbeat_at: datetime | None = None

        rules = contract_rules or {}
        self.signal_executor = SignalExecutor(OrderManager(self.private, rules)) if rules else None
        self.expire = ExpireCoordinator(ExpireManager(self.private))
        for symbol_engine in self.engine.symbols.values():
            symbol_engine.on_signal = self._on_signal

        self.ws = ToobitMarketWebSocket(
            self.engine.symbols.keys(),
            config.runtime.timeframe,
            self._on_market_candle,
            url=config.exchange.ws_url,
            on_price=self._on_market_price,
        )

    def _as_local(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(self.local_timezone)

    def _persist(self) -> None:
        self.state_store.save(self.state)

    def _on_market_price(self, symbol: str, price: Decimal) -> None:
        with self._lock:
            self._latest_prices[symbol] = (price, self._as_local(self.clock()))

    @staticmethod
    def _session_is_active(session: SessionConfig, current: datetime) -> bool:
        minute = current.hour * 60 + current.minute
        if session.crosses_midnight:
            return minute >= session.collection_start_minute or minute < session.expire_minute
        return session.collection_start_minute <= minute < session.expire_minute

    @staticmethod
    def _session_key(session: SessionConfig, current: datetime) -> str:
        minute = current.hour * 60 + current.minute
        trading_date = current.date()
        if session.crosses_midnight and minute < session.expire_minute:
            trading_date -= timedelta(days=1)
        return f"{trading_date.isoformat()}:{session.name}"

    def log_market_status_once(self, now: datetime | None = None) -> None:
        current = self._as_local(now or self.clock())
        with self._lock:
            for symbol, engine in self.engine.symbols.items():
                price_row = self._latest_prices.get(symbol)
                price = price_row[0] if price_row else None
                received_at = price_row[1] if price_row else None
                price_age = (current - received_at).total_seconds() if received_at else None

                for session in engine.config.sessions:
                    if not self._session_is_active(session, current):
                        continue
                    session_key = self._session_key(session, current)
                    state = engine.state.sessions.get(session_key)
                    LOGGER.info(
                        "market_second_status",
                        extra={
                            "event": "market_second_status",
                            "timezone": self.config.runtime.timezone,
                            "local_time": current.isoformat(timespec="seconds"),
                            "symbol": symbol,
                            "session": session.name,
                            "session_key": session_key,
                            "phase": state.phase.value if state is not None else "IDLE",
                            "price": str(price) if price is not None else None,
                            "price_received_at": received_at.isoformat(timespec="seconds") if received_at else None,
                            "price_age_seconds": round(price_age, 3) if price_age is not None else None,
                        },
                    )

    def _heartbeat_due(self, current: datetime) -> bool:
        runtime = self.config.runtime
        if not runtime.heartbeat_log_enabled:
            return False
        if self._next_heartbeat_at is None or current >= self._next_heartbeat_at:
            self._next_heartbeat_at = current + timedelta(seconds=runtime.heartbeat_log_seconds)
            return True
        return False

    def _on_market_candle(self, candle: Candle) -> None:
        with self._lock:
            recovered = self.collector.ingest(candle)
            if recovered:
                LOGGER.warning(
                    "market_candles_recovered",
                    extra={
                        "event": "market_candles_recovered",
                        "symbol": candle.symbol,
                        "count": len(recovered),
                    },
                )
            for item in [*recovered, candle]:
                self._route_closed_candle(item)
            self._persist()

    def _route_closed_candle(self, candle: Candle) -> None:
        engine = self.engine.symbols.get(candle.symbol)
        if engine is None:
            LOGGER.warning("unknown_market_symbol", extra={"event": "unknown_market_symbol", "symbol": candle.symbol})
            return

        opened_utc = datetime.fromtimestamp(candle.open_time_ms / 1000, tz=timezone.utc)
        closed_utc = datetime.fromtimestamp(candle.close_time_ms / 1000, tz=timezone.utc)
        opened_local = opened_utc.astimezone(self.local_timezone)
        closed_local = closed_utc.astimezone(self.local_timezone)

        before = {
            key: (state.phase.value, len(state.range_candles), state.range_high, state.range_low)
            for key, state in engine.state.sessions.items()
        }
        signals = engine.on_closed_candle(
            StateCandle(
                open_time=candle.open_time_ms,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
            ),
            opened_local,
        )

        LOGGER.info(
            "closed_candle_routed",
            extra={
                "event": "closed_candle_routed",
                "symbol": candle.symbol,
                "interval": candle.interval,
                "timezone": self.config.runtime.timezone,
                "candle_open_time": opened_local.isoformat(),
                "candle_close_time": closed_local.isoformat(),
                "open": str(candle.open),
                "high": str(candle.high),
                "low": str(candle.low),
                "close": str(candle.close),
                "volume": str(candle.volume),
                "signal_count": len(signals),
            },
        )

        for key, state in engine.state.sessions.items():
            current = (state.phase.value, len(state.range_candles), state.range_high, state.range_low)
            if before.get(key) != current:
                LOGGER.info(
                    "session_state_changed",
                    extra={
                        "event": "session_state_changed",
                        "symbol": candle.symbol,
                        "session": key,
                        "phase": state.phase.value,
                        "range_candle_count": len(state.range_candles),
                        "range_high": str(state.range_high) if state.range_high is not None else None,
                        "range_low": str(state.range_low) if state.range_low is not None else None,
                        "signal_emitted": state.signal_emitted,
                        "expired": state.expired,
                    },
                )

    def _on_signal(self, signal: TradeSignal) -> None:
        symbol_engine = self.engine.symbols[signal.symbol]
        state = symbol_engine.state.sessions[signal.session_key]
        details = {
            "event": "dry_run_signal" if self.config.runtime.dry_run else "live_signal",
            "symbol": signal.symbol,
            "session": signal.session_name,
            "direction": signal.side.value,
            "signal_price": str(signal.close_price),
            "range_high": str(signal.range_high),
            "range_low": str(signal.range_low),
            "candle_open_time": signal.candle_open_time,
        }
        if self.config.runtime.dry_run:
            LOGGER.info("dry_run_signal", extra=details)
            self._persist()
            return
        if self.signal_executor is None:
            raise RuntimeError("live mode requires contract rules")
        LOGGER.info("live_signal", extra=details)
        wallet = self.private.total_balance()
        self.signal_executor.execute(signal, symbol_engine.config, state, wallet)
        self._persist()

    def run_expirations_once(self, now: datetime | None = None) -> None:
        with self._lock:
            current = self._as_local(now or self.clock())
            for engine in self.engine.symbols.values():
                due = engine.due_expirations(current)
                if not due:
                    continue
                if self.config.runtime.dry_run:
                    for session_name, state in due:
                        state.expire()
                        LOGGER.info(
                            "dry_run_session_expired",
                            extra={
                                "event": "dry_run_session_expired",
                                "symbol": engine.config.symbol,
                                "session": session_name,
                                "local_time": current.isoformat(),
                            },
                        )
                else:
                    self.expire.run_due(engine, current)
            self._persist()

    def run_forever(self) -> None:
        self._install_signal_handlers()
        self.ws.start()
        LOGGER.info(
            "bot_started",
            extra={
                "event": "bot_started",
                "timezone": self.config.runtime.timezone,
                "local_time": self.clock().astimezone(self.local_timezone).isoformat(),
                "dry_run": self.config.runtime.dry_run,
                "symbols": list(self.engine.symbols),
                "timeframe": self.config.runtime.timeframe,
                "runtime_poll_seconds": self.poll_seconds,
                "heartbeat_log_enabled": self.config.runtime.heartbeat_log_enabled,
                "heartbeat_log_seconds": self.config.runtime.heartbeat_log_seconds,
            },
        )
        try:
            while not self._stop.wait(self.poll_seconds):
                current = self._as_local(self.clock())
                self.run_expirations_once(current)
                if self._heartbeat_due(current):
                    self.log_market_status_once(current)
        finally:
            self.ws.stop()
            self._persist()
            LOGGER.info("bot_stopped", extra={"event": "bot_stopped", "local_time": datetime.now(self.local_timezone).isoformat()})

    def stop(self) -> None:
        self._stop.set()

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
