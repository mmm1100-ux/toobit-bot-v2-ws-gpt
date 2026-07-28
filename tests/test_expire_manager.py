from __future__ import annotations

from app.exchange.private_client import ToobitApiError
from app.expire.manager import ExpireFailed, ExpireManager, ExpireOutcomeUnknown


class FakeClient:
    def __init__(self) -> None:
        self.cancel_calls = 0
        self.position_calls = 0
        self.flash_calls: list[tuple[str, str]] = []
        self.position_responses: list[object] = [[]]
        self.cancel_error: ToobitApiError | None = None
        self.flash_errors: dict[str, ToobitApiError] = {}
        self.open_orders_response: object = []

    def cancel_all_orders(self, symbol: str):
        self.cancel_calls += 1
        if self.cancel_error:
            raise self.cancel_error
        return {"code": 200}

    def open_orders(self, symbol: str):
        return self.open_orders_response

    def positions(self, symbol: str, side: str | None = None):
        self.position_calls += 1
        if self.position_responses:
            response = self.position_responses.pop(0)
        else:
            response = []
        if side and isinstance(response, list):
            return [row for row in response if row.get("side") == side]
        return response

    def flash_close(self, symbol: str, side: str, client_order_id: str):
        self.flash_calls.append((symbol, side))
        error = self.flash_errors.get(side)
        if error:
            raise error
        return {"code": 200, "orderId": f"close-{side}"}


def pos(side: str, quantity: str = "2") -> dict:
    return {"symbol": "BTC-SWAP-USDT", "side": side, "position": quantity, "available": quantity}


def manager(client: FakeClient, attempts: int = 3) -> ExpireManager:
    return ExpireManager(client, max_attempts=attempts, verify_delay_seconds=0, sleeper=lambda _: None)


def test_no_position_still_cancels_orders_and_finishes_flat():
    client = FakeClient()
    report = manager(client).expire_symbol("BTC-SWAP-USDT")
    assert report.canceled_orders is True
    assert report.verified_flat is True
    assert client.cancel_calls == 1
    assert client.flash_calls == []


def test_closes_long_and_verifies_flat():
    client = FakeClient()
    client.position_responses = [[pos("LONG")], []]
    report = manager(client).expire_symbol("BTC-SWAP-USDT")
    assert client.flash_calls == [("BTC-SWAP-USDT", "LONG")]
    assert report.close_order_ids == ["close-LONG"]
    assert report.verified_flat is True


def test_closes_both_hedge_sides():
    client = FakeClient()
    client.position_responses = [[pos("LONG"), pos("SHORT", "3")], []]
    report = manager(client).expire_symbol("BTC-SWAP-USDT")
    assert set(client.flash_calls) == {
        ("BTC-SWAP-USDT", "LONG"),
        ("BTC-SWAP-USDT", "SHORT"),
    }
    assert report.verified_flat is True


def test_retries_partial_close_and_recancels_racing_orders():
    client = FakeClient()
    client.position_responses = [
        [pos("LONG", "4")],
        [pos("LONG", "1")],
        [pos("LONG", "1")],
        [],
    ]
    report = manager(client).expire_symbol("BTC-SWAP-USDT")
    assert client.flash_calls == [
        ("BTC-SWAP-USDT", "LONG"),
        ("BTC-SWAP-USDT", "LONG"),
    ]
    assert client.cancel_calls == 2
    assert report.attempts == 2
    assert report.verified_flat is True


def test_cancel_timeout_verified_by_empty_open_orders_is_safe():
    client = FakeClient()
    client.cancel_error = ToobitApiError("timeout", ambiguous=True)
    client.open_orders_response = []
    report = manager(client).expire_symbol("BTC-SWAP-USDT")
    assert report.verified_flat is True
    assert "verification is empty" in report.notes[0]


def test_cancel_timeout_with_remaining_orders_is_unknown():
    client = FakeClient()
    client.cancel_error = ToobitApiError("timeout", ambiguous=True)
    client.open_orders_response = [{"orderId": "still-open"}]
    try:
        manager(client).expire_symbol("BTC-SWAP-USDT")
    except ExpireOutcomeUnknown:
        pass
    else:
        raise AssertionError("expected ExpireOutcomeUnknown")


def test_ambiguous_close_verified_flat_is_safe():
    client = FakeClient()
    client.position_responses = [[pos("LONG")], [], []]
    client.flash_errors["LONG"] = ToobitApiError("timeout", ambiguous=True)
    report = manager(client).expire_symbol("BTC-SWAP-USDT")
    assert report.verified_flat is True
    assert "timed out but side is flat" in report.notes[0]


def test_ambiguous_close_with_position_remaining_is_unknown():
    client = FakeClient()
    client.position_responses = [[pos("LONG")], [pos("LONG")]]
    client.flash_errors["LONG"] = ToobitApiError("timeout", ambiguous=True)
    try:
        manager(client).expire_symbol("BTC-SWAP-USDT")
    except ExpireOutcomeUnknown:
        pass
    else:
        raise AssertionError("expected ExpireOutcomeUnknown")


def test_no_position_error_during_flash_close_is_idempotent():
    client = FakeClient()
    client.position_responses = [[pos("SHORT")], []]
    client.flash_errors["SHORT"] = ToobitApiError("no position", code=-3145)
    report = manager(client).expire_symbol("BTC-SWAP-USDT")
    assert report.verified_flat is True
    assert "already flat" in report.notes[0]


def test_fails_when_position_never_becomes_flat():
    client = FakeClient()
    client.position_responses = [
        [pos("LONG")], [pos("LONG")],
        [pos("LONG")], [pos("LONG")],
    ]
    try:
        manager(client, attempts=2).expire_symbol("BTC-SWAP-USDT")
    except ExpireFailed as exc:
        assert "not flat" in str(exc)
    else:
        raise AssertionError("expected ExpireFailed")
