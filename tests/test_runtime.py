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
