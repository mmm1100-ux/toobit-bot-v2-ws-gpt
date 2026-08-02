from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.core.config import SymbolConfig
from app.core.enums import PositionSide
from app.exchange.private_client import ToobitApiError, ToobitPrivateClient
from app.orders.models import ContractRules, EntryPlan
from app.strategy.signals import TradeSignal


class OrderRejected(RuntimeError):
    pass


class OrderOutcomeUnknown(RuntimeError):
    pass


class OrderManager:
    def __init__(self, client: ToobitPrivateClient, rules: dict[str, ContractRules]) -> None:
        self.client = client
        self.rules = rules

    def build_plan(self, signal: TradeSignal, config: SymbolConfig, wallet_balance: Decimal) -> EntryPlan:
        rules = self.rules[signal.symbol]
        margin = wallet_balance * config.wallet_percent / Decimal("100")
        notional = margin * Decimal(config.leverage)

        target_underlying = notional / signal.close_price
        quantity = rules.order_quantity_for_underlying(target_underlying)
        actual_underlying = rules.underlying_quantity_for_order(quantity)
        actual_notional = actual_underlying * signal.close_price

        if quantity <= 0:
            raise OrderRejected(f"calculated contract quantity for {signal.symbol} is zero")
        if actual_underlying < rules.min_quantity or actual_notional < rules.min_notional:
            raise OrderRejected(
                f"calculated quantity for {signal.symbol} is below exchange minimum "
                f"(contracts={quantity}, underlying={actual_underlying}, notional={actual_notional})"
            )

        change_tp = config.take_profit_percent / Decimal("100")
        change_sl = config.stop_loss_percent / Decimal("100")
        if signal.side is PositionSide.LONG:
            side = "BUY_OPEN"
            take_profit = signal.close_price * (Decimal("1") + change_tp)
            stop_loss = signal.close_price * (Decimal("1") - change_sl)
        else:
            side = "SELL_OPEN"
            take_profit = signal.close_price * (Decimal("1") - change_tp)
            stop_loss = signal.close_price * (Decimal("1") + change_sl)
        client_id = f"tb2_{signal.symbol}_{signal.trading_date.replace('-', '')}_{uuid4().hex[:10]}"[:36]
        return EntryPlan(
            client_order_id=client_id,
            quantity=quantity,
            take_profit=rules.round_price(take_profit),
            stop_loss=rules.round_price(stop_loss),
            side=side,
        )

    def submit(self, signal: TradeSignal, config: SymbolConfig, wallet_balance: Decimal) -> tuple[EntryPlan, dict]:
        try:
            self.client.ensure_symbol_configuration(
                signal.symbol,
                config.margin_type.value,
                config.leverage,
            )
        except ToobitApiError as exc:
            raise OrderRejected(str(exc)) from exc

        plan = self.build_plan(signal, config, wallet_balance)
        try:
            response = self.client.place_market_order(
                symbol=signal.symbol,
                side=plan.side,
                type="LIMIT",
                priceType="MARKET",
                quantity=plan.quantity,
                newClientOrderId=plan.client_order_id,
                takeProfit=plan.take_profit,
                stopLoss=plan.stop_loss,
                tpTriggerBy=config.trigger_by.value,
                slTriggerBy=config.trigger_by.value,
                tpOrderType="MARKET",
                slOrderType="MARKET",
            )
        except ToobitApiError as exc:
            if exc.ambiguous:
                try:
                    response = self.client.query_order(plan.client_order_id)
                except ToobitApiError as query_exc:
                    raise OrderOutcomeUnknown(plan.client_order_id) from query_exc
            else:
                raise OrderRejected(str(exc)) from exc
        return plan, response
