from __future__ import annotations

import argparse
import logging

from app.core.config import load_config
from app.core.logging import configure_logging
from app.exchange.private_client import ToobitPrivateClient
from app.exchange.toobit_rest import ToobitRestClient
from app.runtime import BotRuntime
from app.storage.state_store import AtomicStateStore

LOGGER = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Toobit multi-symbol breakout bot")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--check", action="store_true", help="validate configuration and persisted state, then exit")
    args = parser.parse_args()

    config = load_config(args.config)
    configure_logging(
        config.runtime.log_path,
        timezone_name=config.runtime.timezone,
    )
    store = AtomicStateStore(config.runtime.state_path)
    rest_client = ToobitRestClient(config.exchange.base_url)
    private_client = ToobitPrivateClient(
        config.exchange.api_key,
        config.exchange.api_secret,
        config.exchange.base_url,
        config.exchange.recv_window,
    )

    rules = None
    if not config.runtime.dry_run:
        live_symbols = [item.symbol for item in config.enabled_symbols]
        rules = rest_client.fetch_contract_rules(live_symbols)
        for item in config.enabled_symbols:
            verified = private_client.ensure_symbol_configuration(
                item.symbol,
                item.margin_type.value,
                item.leverage,
            )
            LOGGER.info(
                "live_symbol_configuration_verified",
                extra={
                    "event": "live_symbol_configuration_verified",
                    "symbol": item.symbol,
                    "margin_type": str(verified.get("marginType", item.margin_type.value)),
                    "leverage": str(verified.get("leverage", item.leverage)),
                },
            )

    runtime = BotRuntime(
        config,
        state_store=store,
        rest_client=rest_client,
        private_client=private_client,
        contract_rules=rules,
    )

    if args.check:
        store.save(runtime.state)
        return 0

    runtime.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
