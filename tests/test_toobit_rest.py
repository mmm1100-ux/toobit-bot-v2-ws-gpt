from decimal import Decimal

import pytest

from app.exchange.toobit_rest import ToobitRestClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def contract(symbol="ADA-SWAP-USDT", status="TRADING"):
    return {
        "symbol": symbol,
        "status": status,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.0001"},
            {"filterType": "LOT_SIZE", "minQty": "1", "stepSize": "1"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
        ],
    }


def test_fetch_contract_rules_uses_exchange_info_contract_filters():
    client = ToobitRestClient("https://api.toobit.com")
    client._session = FakeSession({"contracts": [contract()]})

    rules = client.fetch_contract_rules(["ADA-SWAP-USDT"])

    assert client._session.calls[0][0] == "https://api.toobit.com/api/v1/exchangeInfo"
    assert rules["ADA-SWAP-USDT"].step_size == Decimal("1")
    assert rules["ADA-SWAP-USDT"].min_quantity == Decimal("1")
    assert rules["ADA-SWAP-USDT"].min_notional == Decimal("5")
    assert rules["ADA-SWAP-USDT"].tick_size == Decimal("0.0001")


def test_fetch_contract_rules_fails_fast_when_symbol_is_missing():
    client = ToobitRestClient("https://api.toobit.com")
    client._session = FakeSession({"contracts": [contract("BTC-SWAP-USDT")]})

    with pytest.raises(ValueError, match="ADA-SWAP-USDT"):
        client.fetch_contract_rules(["ADA-SWAP-USDT"])


def test_fetch_contract_rules_rejects_non_trading_contract():
    client = ToobitRestClient("https://api.toobit.com")
    client._session = FakeSession({"contracts": [contract(status="OPEN_FORBIDDEN")]})

    with pytest.raises(ValueError, match="not tradable"):
        client.fetch_contract_rules(["ADA-SWAP-USDT"])
