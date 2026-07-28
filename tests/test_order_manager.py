from decimal import Decimal

import pytest

from app.core.config import SessionConfig, SymbolConfig
from app.core.enums import MarginType, PositionSide, TriggerBy
from app.core.state import SessionState
from app.exchange.private_client import ToobitApiError
from app.orders.execution import SignalExecutor
from app.orders.manager import OrderManager, OrderOutcomeUnknown, OrderRejected
from app.orders.models import ContractRules
from app.strategy.signals import TradeSignal


def config() -> SymbolConfig:
    session = SessionConfig("s1", "05:45", "06:15", "09:00", 345, 375, 540)
    return SymbolConfig(
        symbol="BTC-SWAP-USDT",
        enabled=True,
        margin_type=MarginType.CROSS,
        leverage=20,
        wallet_percent=Decimal("5"),
        take_profit_percent=Decimal("0.5"),
        stop_loss_percent=Decimal("0.5"),
        trigger_by=TriggerBy.CONTRACT_PRICE,
        sessions=(session,),
    )


def signal(side: PositionSide = PositionSide.LONG) -> TradeSignal:
    return TradeSignal("BTC-SWAP-USDT", "s1", "2026-07-28", side, Decimal("100000"), Decimal("99000"), Decimal("98000"), 1)


class Client:
    def __init__(self, error=None, query_error=None):
        self.error = error
        self.query_error = query_error
        self.params = None

    def place_market_order(self, **params):
        self.params = params
        if self.error:
            raise self.error
        return {"orderId": "1"}

    def query_order(self, client_order_id):
        if self.query_error:
            raise self.query_error
        return {"clientOrderId": client_order_id, "status": "FILLED"}


def manager(client):
    rules = ContractRules(Decimal("0.001"), Decimal("0.001"), Decimal("10"), Decimal("0.1"))
    return OrderManager(client, {"BTC-SWAP-USDT": rules})


def test_long_plan_uses_wallet_percent_and_leverage():
    client = Client()
    plan, _ = manager(client).submit(signal(), config(), Decimal("1000"))
    assert plan.quantity == Decimal("0.010")
    assert plan.take_profit == Decimal("100500.0")
    assert plan.stop_loss == Decimal("99500.0")
    assert client.params["side"] == "BUY_OPEN"
    assert client.params["priceType"] == "MARKET"


def test_short_tp_and_sl_are_reversed():
    plan = manager(Client()).build_plan(signal(PositionSide.SHORT), config(), Decimal("1000"))
    assert plan.side == "SELL_OPEN"
    assert plan.take_profit == Decimal("99500.0")
    assert plan.stop_loss == Decimal("100500.0")


def test_explicit_rejection_releases_session():
    state = SessionState("2026-07-28")
    state.reserve_signal(1, PositionSide.LONG, Decimal("100000"))
    executor = SignalExecutor(manager(Client(ToobitApiError("insufficient balance"))))
    with pytest.raises(OrderRejected):
        executor.execute(signal(), config(), state, Decimal("1000"))
    assert state.signal_emitted is False


def test_unknown_outcome_keeps_session_consumed():
    state = SessionState("2026-07-28")
    state.reserve_signal(1, PositionSide.LONG, Decimal("100000"))
    timeout = ToobitApiError("timeout", ambiguous=True)
    query_failure = ToobitApiError("query failed")
    executor = SignalExecutor(manager(Client(timeout, query_failure)))
    with pytest.raises(OrderOutcomeUnknown):
        executor.execute(signal(), config(), state, Decimal("1000"))
    assert state.signal_emitted is True
    assert state.trade_committed is False


def test_success_commits_trade():
    state = SessionState("2026-07-28")
    state.reserve_signal(1, PositionSide.LONG, Decimal("100000"))
    SignalExecutor(manager(Client())).execute(signal(), config(), state, Decimal("1000"))
    assert state.trade_committed is True
    assert state.quantity == Decimal("0.010")
