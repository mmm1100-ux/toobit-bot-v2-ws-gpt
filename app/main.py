from __future__ import annotations

import argparse

from app.core.config import load_config
from app.core.logging import configure_logging
from app.runtime import BotRuntime
from app.storage.state_store import AtomicStateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Toobit multi-symbol breakout bot")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--check", action="store_true", help="validate configuration and persisted state, then exit")
    args = parser.parse_args()

    config = load_config(args.config)
    configure_logging(config.runtime.log_path)
    store = AtomicStateStore(config.runtime.state_path)
    runtime = BotRuntime(config, state_store=store)

    if args.check:
        store.save(runtime.state)
        return 0

    runtime.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
