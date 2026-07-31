import pytest

from app.exchange.private_client import ToobitApiError, ToobitPrivateClient


class Client(ToobitPrivateClient):
    def __init__(self, rows, margin_error=None, leverage_error=None):
        super().__init__("key", "secret", "https://api.toobit.com")
        self.rows = list(rows)
        self.margin_error = margin_error
        self.leverage_error = leverage_error
        self.calls = []

    def account_leverage(self, symbol):
        self.calls.append(("get", symbol))
        if len(self.rows) > 1:
            return self.rows.pop(0)
        return self.rows[0]

    def set_margin_type(self, symbol, margin_type):
        self.calls.append(("margin", symbol, margin_type))
        if self.margin_error:
            raise self.margin_error
        return {"code": 200}

    def set_leverage(self, symbol, leverage):
        self.calls.append(("leverage", symbol, leverage))
        if self.leverage_error:
            raise self.leverage_error
        return {"code": 200}


def row(leverage="20", margin_type="CROSS"):
    return {
        "symbolId": "DOGE-SWAP-USDT",
        "leverage": leverage,
        "marginType": margin_type,
    }


def test_matching_configuration_is_only_verified():
    client = Client([row("10", "CROSS")])

    result = client.ensure_symbol_configuration(
        "DOGE-SWAP-USDT", "CROSS", 10, verification_delay_seconds=0
    )

    assert result["leverage"] == "10"
    assert client.calls == [("get", "DOGE-SWAP-USDT"), ("get", "DOGE-SWAP-USDT")]


def test_mismatched_leverage_is_changed_and_read_back():
    client = Client([row("50"), row("10")])

    result = client.ensure_symbol_configuration(
        "DOGE-SWAP-USDT", "CROSS", 10, verification_delay_seconds=0
    )

    assert result["leverage"] == "10"
    assert ("leverage", "DOGE-SWAP-USDT", 10) in client.calls


def test_margin_and_leverage_are_both_enforced():
    client = Client([row("50", "ISOLATED"), row("10", "CROSS")])

    client.ensure_symbol_configuration(
        "DOGE-SWAP-USDT", "CROSS", 10, verification_delay_seconds=0
    )

    assert ("margin", "DOGE-SWAP-USDT", "CROSS") in client.calls
    assert ("leverage", "DOGE-SWAP-USDT", 10) in client.calls


def test_ambiguous_change_timeout_is_reconciled_by_readback():
    client = Client(
        [row("50"), row("10")],
        leverage_error=ToobitApiError("timeout", ambiguous=True),
    )

    result = client.ensure_symbol_configuration(
        "DOGE-SWAP-USDT", "CROSS", 10, verification_delay_seconds=0
    )

    assert result["leverage"] == "10"


def test_unverified_mismatch_refuses_to_trade():
    client = Client([row("50")])

    with pytest.raises(ToobitApiError, match="refusing to trade DOGE-SWAP-USDT"):
        client.ensure_symbol_configuration(
            "DOGE-SWAP-USDT",
            "CROSS",
            10,
            verification_attempts=2,
            verification_delay_seconds=0,
        )
