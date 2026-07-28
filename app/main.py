from __future__ import annotations

import argparse
import logging

from app.core.config import load_config
from app.core.engine import TradingEngine
from app.core.logging import configure_logging
from app.storage import AtomicStateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Toobit multi-symbol breakout bot")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    configure_logging(config.runtime.log_path)
    logger = logging.getLogger(__name__)
    store = AtomicStateStore(config.runtime.state_path)
    state = store.load()
    engine = TradingEngine(config, state)
    store.save(engine.state)
    logger.info(
        "bot state loaded",
        extra={"event": "startup", "symbol": ",".join(engine.symbols)},
    )
    logger.info(
        "configuration ready timezone=%s dry_run=%s",
        config.runtime.timezone,
        config.runtime.dry_run,
        extra={"event": "config_ready"},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
