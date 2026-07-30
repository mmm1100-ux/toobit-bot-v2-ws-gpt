import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.core.config import BotConfig, ExchangeConfig, RuntimeConfig, SessionConfig, SymbolConfig
from app.core.enums import MarginType, TriggerBy
from app.market.candle import Candle
from app.runtime import BotRuntime
from app.storage.state_store import AtomicStateStore


class FakeRest:
    def fetch_klines(self, **kwargs):
        return []


class FakePrivate:
    def total_balance(self):
        return Decimal("100")


class FakeWS:
    def start(self):
        pass

    def stop(self):
        pass


def make_config(tmp_path):
    session = SessionConfig("s1", "00:00", "00:10", "00:20", 0, 10, 20)
    symbol = SymbolConfig(
        symbol="BTCUSDT",
        enabled=True,
        margin_type=MarginType.CROSS,
        leverage=2,
        wallet_percent=Decimal("10"),
        take_profit_percent=Decimal("1"),
        stop_loss_percent=Decimal("1"),
        trigger_by=TriggerBy.CONTRACT_PRICE,
        sessions=(session,),
    )
    return BotConfig(
        exchange=ExchangeConfig("", ""),
        runtime=RuntimeConfig(timezone="UTC", timeframe="5m", dry_run=True, state_path=str(tmp_path / "state.json"), log_path=str(tmp_path / "bot.log")),
        symbols=(symbol,),
    )


def test_runtime_routes_candles_persists_and_expires(tmp_path):
    config = make_config(tmp_path)
    store = AtomicStateStore(config.runtime.state_path)
    runtime = BotRuntime(config, state_store=store, rest_client=FakeRest(), private_client=FakePrivate())
    runtime.ws = FakeWS()

    runtime._on_market_candle(Candle("BTCUSDT", "5m", 0, 299999, Decimal("100"), Decimal("110"), Decimal("90"), Decimal("105"), Decimal("1")))
    runtime._on_market_candle(Candle("BTCUSDT", "5m", 300000, 599999, Decimal("105"), Decimal("112"), Decimal("95"), Decimal("108"), Decimal("1")))

    state = runtime.engine.symbols["BTCUSDT"].state.sessions["1970-01-01:s1"]
    assert len(state.range_candles) == 2
    assert store.load().symbols["BTCUSDT"].sessions["1970-01-01:s1"].range_candles

    runtime.run_expirations_once(datetime(1970, 1, 1, 0, 20, tzinfo=timezone.utc))
    assert state.expired is True


def test_runtime_routes_utc_candle_by_tehran_session_time(tmp_path):
    session = SessionConfig("tehran", "15:20", "15:30", "15:40", 920, 930, 940)
    symbol = SymbolConfig(
        symbol="ADA-SWAP-USDT",
        enabled=True,
        margin_type=MarginType.CROSS,
        leverage=20,
        wallet_percent=Decimal("5"),
        take_profit_percent=Decimal("0.5"),
        stop_loss_percent=Decimal("0.5"),
        trigger_by=TriggerBy.CONTRACT_PRICE,
        sessions=(session,),
    )
    config = BotConfig(
        exchange=ExchangeConfig("", ""),
        runtime=RuntimeConfig(timezone="Asia/Tehran", timeframe="5m", dry_run=True, state_path=str(tmp_path / "state.json"), log_path=str(tmp_path / "bot.log")),
        symbols=(symbol,),
    )
    runtime = BotRuntime(config, state_store=AtomicStateStore(config.runtime.state_path), rest_client=FakeRest(), private_client=FakePrivate())

    open_ms = int(datetime(2026, 7, 28, 11, 50, tzinfo=timezone.utc).timestamp() * 1000)
    runtime._on_market_candle(Candle("ADA-SWAP-USDT", "5m", open_ms, open_ms + 299999, Decimal("0.75"), Decimal("0.76"), Decimal("0.74"), Decimal("0.755"), Decimal("100")))

    state = runtime.engine.symbols["ADA-SWAP-USDT"].state.sessions["2026-07-28:tehran"]
    assert state.phase.value == "COLLECTING"
    assert len(state.range_candles) == 1


def test_restart_restores_consumed_session(tmp_path):
    config = make_config(tmp_path)
    store = AtomicStateStore(config.runtime.state_path)
    first = BotRuntime(config, state_store=store, rest_client=FakeRest(), private_client=FakePrivate())
    first._on_market_candle(Candle("BTCUSDT", "5m", 0, 299999, Decimal("100"), Decimal("110"), Decimal("90"), Decimal("105"), Decimal("1")))
    state = first.engine.symbols["BTCUSDT"].state.sessions["1970-01-01:s1"]
    state.signal_emitted = True
    store.save(first.state)

    second = BotRuntime(config, state_store=store, rest_client=FakeRest(), private_client=FakePrivate())
    assert second.engine.symbols["BTCUSDT"].state.sessions["1970-01-01:s1"].signal_emitted is True


def test_market_status_logs_configured_time_symbol_session_and_live_price(tmp_path, caplog):
    session = SessionConfig("ada_live", "16:00", "16:30", "17:00", 960, 990, 1020)
    symbol = SymbolConfig(
        symbol="ADA-SWAP-USDT",
        enabled=True,
        margin_type=MarginType.CROSS,
        leverage=20,
        wallet_percent=Decimal("5"),
        take_profit_percent=Decimal("0.5"),
        stop_loss_percent=Decimal("0.5"),
        trigger_by=TriggerBy.CONTRACT_PRICE,
        sessions=(session,),
    )
    config = BotConfig(
        exchange=ExchangeConfig("", ""),
        runtime=RuntimeConfig(timezone="Asia/Tehran", timeframe="5m", dry_run=True, state_path=str(tmp_path / "state.json"), log_path=str(tmp_path / "bot.log")),
        symbols=(symbol,),
    )
    now = datetime(2026, 7, 30, 16, 10, 5, tzinfo=runtime_tz := __import__("zoneinfo").ZoneInfo("Asia/Tehran"))
    runtime = BotRuntime(
        config,
        state_store=AtomicStateStore(config.runtime.state_path),
        rest_client=FakeRest(),
        private_client=FakePrivate(),
        clock=lambda: now,
    )

    runtime._on_market_price("ADA-SWAP-USDT", Decimal("0.15742"))
    with caplog.at_level(logging.INFO, logger="app.runtime"):
        runtime.log_market_status_once(now)

    record = next(item for item in caplog.records if getattr(item, "event", None) == "market_second_status")
    assert record.timezone == "Asia/Tehran"
    assert record.local_time == "2026-07-30T16:10:05+03:30"
    assert record.symbol == "ADA-SWAP-USDT"
    assert record.session == "ada_live"
    assert record.price == "0.15742"
