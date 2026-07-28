from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

from app.exchange.private_client import ToobitApiError, ToobitPrivateClient
from app.expire.models import ExpireReport, PositionSnapshot


class ExpireFailed(RuntimeError):
    pass


class ExpireOutcomeUnknown(RuntimeError):
    pass


class ExpireManager:
    """Safely expires one symbol by canceling orders, closing every side, and verifying flat state."""

    def __init__(
        self,
        client: ToobitPrivateClient,
        *,
        max_attempts: int = 3,
        verify_delay_seconds: float = 0.5,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.client = client
        self.max_attempts = max_attempts
        self.verify_delay_seconds = verify_delay_seconds
        self.sleeper = sleeper

    @staticmethod
    def _rows(payload: object) -> list[dict]:
        if isinstance(payload, dict):
            payload = payload.get("data", payload.get("result", payload))
        if payload is None:
            return []
        if isinstance(payload, dict):
            return [payload]
        if not isinstance(payload, list):
            raise ExpireFailed("unexpected Toobit positions response")
        return [row for row in payload if isinstance(row, dict)]

    @classmethod
    def parse_positions(cls, symbol: str, payload: object) -> list[PositionSnapshot]:
        result: list[PositionSnapshot] = []
        for row in cls._rows(payload):
            row_symbol = str(row.get("symbol", ""))
            if row_symbol and row_symbol != symbol:
                continue
            position = Decimal(str(row.get("position", "0")))
            available = Decimal(str(row.get("available", position.copy_abs())))
            side = str(row.get("side", "")).upper()
            if side not in {"LONG", "SHORT"}:
                if position > 0:
                    side = "LONG"
                elif position < 0:
                    side = "SHORT"
                else:
                    continue
            snapshot = PositionSnapshot(symbol=symbol, side=side, position=position, available=available)
            if snapshot.is_open:
                result.append(snapshot)
        return result

    def _cancel_all(self, symbol: str, report: ExpireReport) -> None:
        try:
            self.client.cancel_all_orders(symbol)
            report.canceled_orders = True
        except ToobitApiError as exc:
            if exc.code in {-2011, -2013, -3145}:
                report.canceled_orders = True
                report.notes.append(f"cancel treated as already clean: {exc}")
                return
            if exc.ambiguous:
                open_orders = self.client.open_orders(symbol)
                if self._rows(open_orders):
                    raise ExpireOutcomeUnknown(f"cancel outcome unknown for {symbol}") from exc
                report.canceled_orders = True
                report.notes.append("cancel timed out but open-order verification is empty")
                return
            raise ExpireFailed(f"failed to cancel open orders for {symbol}: {exc}") from exc

    def _close_position(self, position: PositionSnapshot, report: ExpireReport) -> None:
        client_id = f"exp_{position.symbol}_{position.side}_{uuid4().hex[:10]}"[:36]
        try:
            response = self.client.flash_close(position.symbol, position.side, client_id)
        except ToobitApiError as exc:
            if exc.code == -3145:
                report.notes.append(f"{position.side} already flat")
                return
            if exc.ambiguous:
                after = self.parse_positions(position.symbol, self.client.positions(position.symbol, position.side))
                if not after:
                    report.notes.append(f"{position.side} close timed out but side is flat")
                    return
                raise ExpireOutcomeUnknown(
                    f"close outcome unknown for {position.symbol} {position.side}"
                ) from exc
            raise ExpireFailed(f"failed to close {position.symbol} {position.side}: {exc}") from exc
        if isinstance(response, dict):
            order_id = response.get("orderId") or response.get("data", {}).get("orderId")
            if order_id is not None:
                report.close_order_ids.append(str(order_id))

    def expire_symbol(self, symbol: str) -> ExpireReport:
        report = ExpireReport(symbol=symbol)
        self._cancel_all(symbol, report)

        for attempt in range(1, self.max_attempts + 1):
            report.attempts = attempt
            positions = self.parse_positions(symbol, self.client.positions(symbol))
            if attempt == 1:
                report.positions_before = positions.copy()
            if not positions:
                report.positions_after = []
                report.verified_flat = True
                return report

            for position in positions:
                self._close_position(position, report)

            if self.verify_delay_seconds:
                self.sleeper(self.verify_delay_seconds)
            remaining = self.parse_positions(symbol, self.client.positions(symbol))
            report.positions_after = remaining
            if not remaining:
                report.verified_flat = True
                return report

            # TP/SL or pending close orders may have reappeared during a race. Clean them before retrying.
            self._cancel_all(symbol, report)

        sides = ", ".join(f"{item.side}:{item.position}" for item in report.positions_after)
        raise ExpireFailed(f"{symbol} is not flat after {self.max_attempts} attempts ({sides})")
