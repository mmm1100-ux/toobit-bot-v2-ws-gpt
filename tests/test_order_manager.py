from decimal import Decimal

import pytest

from app.core.config import SessionConfig, SymbolConfig
from app.core.enums import MarginType, PositionSide, TriggerBy
from app.core.state import SessionState
from app.exchange.private_client import ToobitApiError
from app.orders.execution import SignalExecutor
from app.orders.manager import (
    OrderManager,
    OrderOutcomeUnknown,
    OrderRejected,
    PositionProtectionFailed,
)
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
    def __init__(
        self,
        error=None,
        query_error=None,
        configuration_error=None,
        protection_error=None,
        place_response=None,
        query_response=None,
    ):
        self.error = error
        self.query_error = query_error
        self.configuration_error = configuration_error
        self.protection_error = protection_error
        self.place_response = place_response or {
            "orderId": "1",
            "clientOrderId": "entry",
            "status": "FILLED",
            "avgPrice": "100000",
            "executedQty": "10",
        }
        self.query_response = query_response or self.place_response
        self.params = None
        self.configuration = None
        self.protection = None
        self.position_open = False
        self.flash_closed = False
        self.cancelled = False

    def ensure_symbol_configuration(self, symbol, margin_type, leverage):
        self.configuration = (symbol, margin_type, leverage)
        if self.configuration_error:
            raise self.configuration_error
        return {"symbolId": symbol, "marginType": margin_type, "leverage": str(leverage)}

    def place_market_order(self, **params):
        self.params = params
        if self.error:
            raise self.error
        self.position_open = True
        return self.place_response

    def query_order(self, client_order_id):
        if self.query_error:
            raise self.query_error
        self.position_open = True
        return self.query_response

    def set_trading_stop(self, **params):
        self.protection = params
        if self.protection_error:
            raise self.protection_error
        return {
            "symbol": params["symbol"],
            "side": params["side"],
            "takeProfit": str(params["take_profit"]),
            "stopLoss": str(params["stop_loss"]),
            "tpSize": str(params["quantity"]),
            "slSize": str(params["quantity"]),
        }

    def flash_close(self, symbol, side, client_order_id=None):
        self.position_open = False
        self.flash_closed = True
        return {"orderId": "close-1"}

    def cancel_all_orders(self, symbol):
        self.cancelled = True
        return []

    def positions(self, symbol, side=None):
        if not self.position_open:
            return []
        return [{"symbol": symbol, "side": side or "LONG", "position": "10"}]


def manager(client):
    rules = ContractRules(
        step_size=Decimal("0.001"),
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("10"),
        tick_size=Decimal("0.1"),
        contract_multiplier=Decimal("0.001"),
    )
    return OrderManager(
        client,
        {"BTC-SWAP-USDT": rules},
        fill_query_attempts=2,
        fill_query_delay_seconds=0,
    )


def test_long_plan_uses_wallet_percent_leverage_and_contract_multiplier():
    client = Client()
    plan, _ = manager(client).submit(signal(), config(), Decimal("1000"))
    assert plan.quantity == Decimal("10")
    assert plan.fill_price == Decimal("100000")
    assert plan.executed_quantity == Decimal("10")
    assert plan.take_profit == Decimal("100500.0")
    assert plan.stop_loss == Decimal("99500.0")
    assert client.configuration == ("BTC-SWAP-USDT", "CROSS", 20)
    assert client.params["side"] == "BUY_OPEN"
    assert client.params["priceType"] == "MARKET"
    assert client.params["quantity"] == Decimal("10")
    assert "takeProfit" not in client.params
    assert "stopLoss" not in client.params
    assert client.protection["take_profit"] == Decimal("100500.0")
    assert client.protection["stop_loss"] == Decimal("99500.0")


def test_protection_is_rebased_on_real_average_fill_price():
    client = Client(
        place_response={
            "orderId": "1",
            "status": "FILLED",
            "avgPrice": "100400",
            "executedQty": "10",
        }
    )

    plan, _ = manager(client).submit(signal(), config(), Decimal("1000"))

    assert plan.fill_price == Decimal("100400")
    assert plan.take_profit == Decimal("100902.0")
    assert plan.stop_loss == Decimal("99898.0")
    assert client.protection["take_profit"] == Decimal("100902.0")
    assert client.protection["stop_loss"] == Decimal("99898.0")


def test_order_is_queried_until_average_fill_is_confirmed():
    client = Client(
        place_response={
            "orderId": "1",
            "status": "NEW",
            "avgPrice": "0",
            "executedQty": "0",
        },
        query_response={
            "orderId": "1",
            "status": "FILLED",
            "avgPrice": "100250",
            "executedQty": "10",
        },
    )

    plan, _ = manager(client).submit(signal(), config(), Decimal("1000"))

    assert plan.fill_price == Decimal("100250")
    assert plan.take_profit == Decimal("100751.2")
    assert plan.stop_loss == Decimal("99748.8")


def test_short_tp_and_sl_are_reversed():
    plan = manager(Client()).build_plan(signal(PositionSide.SHORT), config(), Decimal("1000"))
    assert plan.side == "SELL_OPEN"
    assert plan.take_profit == Decimal("99500.0")
    assert plan.stop_loss == Decimal("100500.0")


def test_configuration_mismatch_blocks_order_submission():
    client = Client(configuration_error=ToobitApiError("exchange still reports 50x"))
    with pytest.raises(OrderRejected, match="50x"):
        manager(client).submit(signal(), config(), Decimal("1000"))
    assert client.params is None


def test_explicit_rejection_releases_session():
    state = SessionState("2026-07-28")
    state.reserve_signal(1, PositionSide.LONG, Decimal("100000"))
    executor = SignalExecutor(manager(Client(error=ToobitApiError("insufficient balance"))))
    with pytest.raises(OrderRejected):
        executor.execute(signal(), config(), state, Decimal("1000"))
    assert state.signal_emitted is False


def test_unknown_entry_outcome_keeps_session_consumed():
    state = SessionState("2026-07-28")
    state.reserve_signal(1, PositionSide.LONG, Decimal("100000"))
    timeout = ToobitApiError("timeout", ambiguous=True)
    query_failure = ToobitApiError("query failed")
    executor = SignalExecutor(manager(Client(error=timeout, query_error=query_failure)))
    with pytest.raises(OrderOutcomeUnknown):
        executor.execute(signal(), config(), state, Decimal("1000"))
    assert state.signal_emitted is True
    assert state.trade_committed is False


def test_protection_failure_emergency_closes_and_consumes_session():
    state = SessionState("2026-07-28")
    state.reserve_signal(1, PositionSide.LONG, Decimal("100000"))
    client = Client(protection_error=ToobitApiError("trading stop rejected"))
    executor = SignalExecutor(manager(client))

    with pytest.raises(PositionProtectionFailed) as exc_info:
        executor.execute(signal(), config(), state, Decimal("1000"))

    assert exc_info.value.flattened is True
    assert client.flash_closed is True
    assert client.cancelled is True
    assert state.signal_emitted is True
    assert state.trade_committed is True


def test_success_commits_trade():
    state = SessionState("2026-07-28")
    state.reserve_signal(1, PositionSide.LONG, Decimal("100000"))
    SignalExecutor(manager(Client())).execute(signal(), config(), state, Decimal("1000"))
    assert state.trade_committed is True
    assert state.quantity == Decimal("10")
