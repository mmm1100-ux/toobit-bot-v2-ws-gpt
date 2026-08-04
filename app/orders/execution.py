from __future__ import annotations

from decimal import Decimal

from app.core.config import SymbolConfig
from app.core.state import SessionState
from app.orders.manager import (
    OrderManager,
    OrderOutcomeUnknown,
    OrderRejected,
    PositionProtectionFailed,
)
from app.strategy.signals import TradeSignal


class SignalExecutor:
    """Applies the one-trade-per-session failure policy around order submission."""

    def __init__(self, manager: OrderManager) -> None:
        self.manager = manager

    def execute(
        self,
        signal: TradeSignal,
        config: SymbolConfig,
        state: SessionState,
        wallet_balance: Decimal,
    ) -> dict:
        try:
            plan, response = self.manager.submit(signal, config, wallet_balance)
        except OrderRejected:
            state.release_signal()
            raise
        except PositionProtectionFailed as exc:
            # The entry was confirmed filled. Even if the emergency flatten worked,
            # the session must remain consumed so the same breakout cannot re-enter.
            state.commit_trade(
                signal.side,
                exc.plan.client_order_id,
                exc.plan.executed_quantity or exc.plan.quantity,
                exc.plan.fill_price or signal.close_price,
            )
            raise
        except OrderOutcomeUnknown:
            # Keep signal_emitted=True: the exchange may have accepted the order.
            raise
        state.commit_trade(
            signal.side,
            plan.client_order_id,
            plan.executed_quantity or plan.quantity,
            plan.fill_price or signal.close_price,
        )
        return response
