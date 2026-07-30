import json
from decimal import Decimal

from app.exchange.toobit_ws import ToobitMarketWebSocket
from app.market.candle import Candle
from app.market.collector import CandleCollector


def candle(open_time: int, close: str = "100") -> Candle:
    return Candle(
        symbol="BTC-SWAP-USDT",
        interval="5m",
        open_time_ms=open_time,
        close_time_ms=open_time + 300_000 - 1,
        open=Decimal("99"),
        high=Decimal("101"),
        low=Decimal("98"),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def test_websocket_emits_previous_candle_when_next_bucket_arrives() -> None:
    emitted: list[Candle] = []
    stream = ToobitMarketWebSocket(["BTC-SWAP-USDT"], "5m", emitted.append)

    first = {"t": 0, "s": "BTC-SWAP-USDT", "o": "99", "h": "101", "l": "98", "c": "100", "v": "1"}
    first_update = {**first, "c": "100.5"}
    second = {**first, "t": 300_000, "c": "102"}

    stream._handle_message(json.dumps({"data": [first]}))
    stream._handle_message(json.dumps({"data": [first_update]}))
    assert emitted == []

    stream._handle_message(json.dumps({"data": [second]}))
    assert len(emitted) == 1
    assert emitted[0].open_time_ms == 0
    assert emitted[0].close == Decimal("100.5")


def test_collector_recovers_missing_bucket_before_ingest() -> None:
    calls: list[dict[str, object]] = []

    def fetcher(**kwargs: object) -> list[Candle]:
        calls.append(kwargs)
        return [candle(300_000, "101")]

    collector = CandleCollector("5m", fetcher)
    collector.ingest(candle(0))
    recovered = collector.ingest(candle(600_000, "102"))

    assert [item.open_time_ms for item in recovered] == [300_000]
    assert calls[0]["start_time_ms"] == 300_000
    assert calls[0]["end_time_ms"] == 599_999
    assert [item.open_time_ms for item in collector.range("BTC-SWAP-USDT", 0, 900_000)] == [0, 300_000, 600_000]
