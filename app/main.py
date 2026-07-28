from __future__ import annotations

import argparse

from app.core.config import load_config
from app.core.engine import TradingEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Toobit multi-symbol breakout bot")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()
    config = load_config(args.config)
    engine = TradingEngine(config)
    print(
        "CONFIG_OK",
        f"symbols={','.join(engine.symbols)}",
        f"timezone={config.runtime.timezone}",
        f"dry_run={config.runtime.dry_run}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
