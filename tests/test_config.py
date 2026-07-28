import json
from pathlib import Path

import pytest

from app.core.config import ConfigError, load_config


def write_config(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def valid_config() -> dict:
    return {
        "runtime": {"timezone": "UTC", "dry_run": True},
        "symbols": [
            {
                "symbol": "ADA-SWAP-USDT",
                "leverage": 20,
                "wallet_percent": 5,
                "take_profit_percent": 0.5,
                "stop_loss_percent": 0.5,
                "sessions": [
                    {
                        "name": "morning",
                        "collection_start": "05:45",
                        "collection_end": "06:15",
                        "expire_time": "09:00"
                    }
                ]
            }
        ]
    }


def test_loads_multi_symbol_config(tmp_path: Path) -> None:
    data = valid_config()
    data["symbols"].append({**data["symbols"][0], "symbol": "BTC-SWAP-USDT", "leverage": 10})
    config = load_config(write_config(tmp_path, data))
    assert [item.symbol for item in config.enabled_symbols] == ["ADA-SWAP-USDT", "BTC-SWAP-USDT"]
    assert config.enabled_symbols[1].leverage == 10


def test_rejects_duplicate_symbols(tmp_path: Path) -> None:
    data = valid_config()
    data["symbols"].append(dict(data["symbols"][0]))
    with pytest.raises(ConfigError, match="unique"):
        load_config(write_config(tmp_path, data))


def test_live_mode_requires_environment_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = valid_config()
    data["runtime"]["dry_run"] = False
    monkeypatch.delenv("TOOBIT_API_KEY", raising=False)
    monkeypatch.delenv("TOOBIT_API_SECRET", raising=False)
    with pytest.raises(ConfigError, match="TOOBIT_API_KEY"):
        load_config(write_config(tmp_path, data))
