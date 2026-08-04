from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from app.core.config import SymbolConfig
from app.core.enums import PositionSide
from app.exchange.private_client import ToobitApiError, ToobitPrivateClient
from app.orders.models import ContractRules, EntryPlan
from app.strategy.signals import TradeSignal

LOGGER = logging.getLogger(__name__)


class OrderRejected(RuntimeError):
    pass


class OrderOutcomeUnknown(RuntimeError):
    pass


class PositionProtectionFailed(OrderOutcomeUnknown):
    """The entry filled, but exact fill-based protection could not be confirmed."""

    def __init__(self, message: str, plan: EntryPlan, *, flattened: bool) -> None:
        super().__init__(message)
        self.plan = plan
        self.flattened = flattened


class OrderManager:
    def __init__(
        self,
        client: ToobitPrivateClient,
        rules: dict[str, ContractRules],
        *,
        fill_query_attempts: int = 12,
        fill_query_delay_seconds: float = 0.2,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if fill_query_attempts < 1:
            raise ValueError("fill_query_attempts must be positive")
        self.client = client
        self.rules = rules
        self.fill_query_attempts = fill_query_attempts
        self.fill_query_delay_seconds = fill_query_delay_seconds
        self.sleeper = sleeper

    @staticmethod
    def _position_side(side: PositionSide) -> str:
        return "LONG" if side is PositionSide.LONG else "SHORT"

    @staticmethod
    def _order_row(payload: object) -> dict:
        if not isinstance(payload, dict):
            return {}
        row = payload
        for key in ("data", "result", "order"):
            nested = row.get(key)
            if isinstance(nested, dict):
                row = nested
        return row

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @classmethod
    def _extract_confirmed_fill(cls, payload: object) -> tuple[Decimal, Decimal] | None:
        row = cls._order_row(payload)
        status = str(row.get("status", "")).upper()
        if status and status not in {"FILLED", "ORDER_FILLED"}:
            return None
        average = cls._decimal(row.get("avgPrice"))
        executed = cls._decimal(row.get("executedQty", row.get("executeQty")))
        if average is None or average <= 0 or executed is None or executed <= 0:
            return None
        return average, executed

    @staticmethod
    def _payload_rows(payload: object) -> list[dict]:
        if isinstance(payload, dict):
            payload = payload.get("data", payload.get("result", payload))
        if isinstance(payload, dict):
            return [payload]
        if not isinstance(payload, list):
            return []
        return [row for row in payload if isinstance(row, dict)]

    def _side_is_flat(self, symbol: str, side: str) -> bool:
        payload = self.client.positions(symbol, side)
        for row in self._payload_rows(payload):
            row_symbol = str(row.get("symbol", symbol)).upper()
            row_side = str(row.get("side", side)).upper()
            position = self._decimal(row.get("position")) or Decimal("0")
            if row_symbol == symbol.upper() and row_side == side and position != 0:
                return False
        return True

    def _emergency_flatten(self, symbol: str, side: str) -> bool:
        client_id = f"safe_{symbol}_{side}_{uuid4().hex[:8]}"[:36]
        try:
            self.client.flash_close(symbol, side, client_id)
        except ToobitApiError:
            pass
        try:
            self.client.cancel_all_orders(symbol)
        except ToobitApiError:
            pass

        for attempt in range(3):
            try:
                if self._side_is_flat(symbol, side):
                    return True
            except ToobitApiError:
                pass
            if attempt < 2 and self.fill_query_delay_seconds > 0:
                self.sleeper(self.fill_query_delay_seconds)
        return False

    def _wait_for_fill(self, client_order_id: str, initial_response: object) -> tuple[Decimal, Decimal, object]:
        confirmed = self._extract_confirmed_fill(initial_response)
        if confirmed is not None:
            return confirmed[0], confirmed[1], initial_response

        last_response: object = initial_response
        last_error: ToobitApiError | None = None
        for attempt in range(self.fill_query_attempts):
            if attempt and self.fill_query_delay_seconds > 0:
                self.sleeper(self.fill_query_delay_seconds)
            try:
                last_response = self.client.query_order(client_order_id)
                last_error = None
            except ToobitApiError as exc:
                last_error = exc
                continue
            confirmed = self._extract_confirmed_fill(last_response)
            if confirmed is not None:
                return confirmed[0], confirmed[1], last_response

        detail = f": {last_error}" if last_error is not None else ""
        raise OrderOutcomeUnknown(f"could not confirm filled entry {client_order_id}{detail}")

    def _protection_prices(
        self,
        side: PositionSide,
        config: SymbolConfig,
        rules: ContractRules,
        base_price: Decimal,
    ) -> tuple[Decimal, Decimal]:
        change_tp = config.take_profit_percent / Decimal("100")
        change_sl = config.stop_loss_percent / Decimal("100")
        if side is PositionSide.LONG:
            take_profit = rules.floor_price(base_price * (Decimal("1") + change_tp))
            stop_loss = rules.ceil_price(base_price * (Decimal("1") - change_sl))
            valid = stop_loss < base_price < take_profit
        else:
            take_profit = rules.ceil_price(base_price * (Decimal("1") - change_tp))
            stop_loss = rules.floor_price(base_price * (Decimal("1") + change_sl))
            valid = take_profit < base_price < stop_loss
        if not valid:
            raise OrderRejected(
                f"tick size prevents valid TP/SL for {config.symbol} at fill price {base_price}"
            )
        return take_profit, stop_loss

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

        take_profit, stop_loss = self._protection_prices(
            signal.side,
            config,
            rules,
            signal.close_price,
        )
        side = "BUY_OPEN" if signal.side is PositionSide.LONG else "SELL_OPEN"
        client_id = f"tb2_{signal.symbol}_{signal.trading_date.replace('-', '')}_{uuid4().hex[:10]}"[:36]
        return EntryPlan(
            client_order_id=client_id,
            quantity=quantity,
            take_profit=take_profit,
            stop_loss=stop_loss,
            side=side,
        )

    @classmethod
    def _validate_trading_stop_response(
        cls,
        response: object,
        expected_take_profit: Decimal,
        expected_stop_loss: Decimal,
    ) -> None:
        row = cls._order_row(response)
        returned_tp = cls._decimal(row.get("takeProfit"))
        returned_sl = cls._decimal(row.get("stopLoss"))
        if returned_tp is not None and returned_tp != expected_take_profit:
            raise ToobitApiError(
                f"Toobit confirmed unexpected take profit {returned_tp}; expected {expected_take_profit}"
            )
        if returned_sl is not None and returned_sl != expected_stop_loss:
            raise ToobitApiError(
                f"Toobit confirmed unexpected stop loss {returned_sl}; expected {expected_stop_loss}"
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
        position_side = self._position_side(signal.side)
        try:
            entry_response = self.client.place_market_order(
                symbol=signal.symbol,
                side=plan.side,
                type="LIMIT",
                priceType="MARKET",
                quantity=plan.quantity,
                newClientOrderId=plan.client_order_id,
            )
        except ToobitApiError as exc:
            if exc.ambiguous:
                try:
                    entry_response = self.client.query_order(plan.client_order_id)
                except ToobitApiError as query_exc:
                    flattened = self._emergency_flatten(signal.symbol, position_side)
                    raise OrderOutcomeUnknown(
                        f"entry outcome unknown for {plan.client_order_id}; emergency_flattened={flattened}"
                    ) from query_exc
            else:
                raise OrderRejected(str(exc)) from exc

        try:
            fill_price, executed_quantity, filled_response = self._wait_for_fill(
                plan.client_order_id,
                entry_response,
            )
        except OrderOutcomeUnknown as exc:
            flattened = self._emergency_flatten(signal.symbol, position_side)
            raise OrderOutcomeUnknown(f"{exc}; emergency_flattened={flattened}") from exc

        try:
            take_profit, stop_loss = self._protection_prices(
                signal.side,
                config,
                self.rules[signal.symbol],
                fill_price,
            )
        except OrderRejected as exc:
            final_plan = replace(
                plan,
                fill_price=fill_price,
                executed_quantity=executed_quantity,
            )
            flattened = self._emergency_flatten(signal.symbol, position_side)
            raise PositionProtectionFailed(str(exc), final_plan, flattened=flattened) from exc

        final_plan = replace(
            plan,
            take_profit=take_profit,
            stop_loss=stop_loss,
            fill_price=fill_price,
            executed_quantity=executed_quantity,
        )

        try:
            protection_response = self.client.set_trading_stop(
                symbol=signal.symbol,
                side=position_side,
                take_profit=take_profit,
                stop_loss=stop_loss,
                quantity=executed_quantity,
                trigger_by=config.trigger_by.value,
            )
            self._validate_trading_stop_response(
                protection_response,
                take_profit,
                stop_loss,
            )
        except ToobitApiError as exc:
            flattened = self._emergency_flatten(signal.symbol, position_side)
            raise PositionProtectionFailed(
                f"failed to apply fill-based TP/SL for {signal.symbol}: {exc}",
                final_plan,
                flattened=flattened,
            ) from exc

        LOGGER.info(
            "entry_protection_set",
            extra={
                "event": "entry_protection_set",
                "symbol": signal.symbol,
                "side": position_side,
                "signal_price": str(signal.close_price),
                "fill_price": str(fill_price),
                "quantity": str(executed_quantity),
                "take_profit": str(take_profit),
                "stop_loss": str(stop_loss),
            },
        )
        return final_plan, {
            "entry_order": filled_response,
            "trading_stop": protection_response,
            "fill_price": str(fill_price),
            "executed_quantity": str(executed_quantity),
        }
