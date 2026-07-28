from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.core.enums import PositionSide, SessionPhase
from app.core.errors import StateError
from app.core.state import BotState, Candle, SessionState, SymbolState
from app.storage import AtomicStateStore


def test_round_trip_preserves_consumed_session(tmp_path):
    session = SessionState(session_date="2026-07-28", phase=SessionPhase.TRADE_COMMITTED)
    session.range_high = Decimal("101.5")
    session.range_low = Decimal("99.5")
    session.range_candles[1] = Candle(1, Decimal("100"), Decimal("101.5"), Decimal("99.5"), Decimal("101"))
    session.commit_trade(PositionSide.LONG, "client-1", Decimal("0.01"), Decimal("101"))
    state = BotState(symbols={"BTCUSDT": SymbolState("BTCUSDT", {"2026-07-28:asia": session})})
    store = AtomicStateStore(tmp_path / "state.json")

    store.save(state)
    restored = store.load()

    loaded = restored.symbols["BTCUSDT"].sessions["2026-07-28:asia"]
    assert loaded.trade_committed is True
    assert loaded.direction is PositionSide.LONG
    assert loaded.quantity == Decimal("0.01")
    assert loaded.range_candles[1].high == Decimal("101.5")


def test_version_one_state_is_migrated(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 1, "symbols": {}}), encoding="utf-8")
    assert AtomicStateStore(path).load().version == 2


def test_corrupt_state_fails_closed(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(StateError):
        AtomicStateStore(path).load()


def test_failed_replace_does_not_delete_existing_state(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"version":2,"symbols":{}}', encoding="utf-8")
    store = AtomicStateStore(path)

    def fail_replace(*_args):
        raise OSError("disk failure")

    monkeypatch.setattr("app.storage.state_store.os.replace", fail_replace)
    with pytest.raises(StateError):
        store.save(BotState())
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2
