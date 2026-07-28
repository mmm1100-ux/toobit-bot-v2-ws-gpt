from __future__ import annotations

from decimal import Decimal

from app.core.config import SymbolConfig
from app.core.state import SessionState
from app.orders.manager import OrderManager, OrderOutcomeUnknown, OrderRejected
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
        except OrderOutcomeUnknown:
            # Keep signal_emitted=True: the exchange may have accepted the order.
            raise
        state.commit_trade(signal.side, plan.client_order_id, plan.quantity, signal.close_price)
        return response
