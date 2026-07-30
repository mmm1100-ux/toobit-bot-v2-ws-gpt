from __future__ import annotations

from app.core.config import BotConfig
from app.core.state import BotState, SymbolState
from app.symbols.engine import SymbolEngine


class TradingEngine:
    def __init__(self, config: BotConfig, state: BotState | None = None) -> None:
        self.config = config
        self.state = state or BotState()
        self.symbols: dict[str, SymbolEngine] = {}
        for symbol_config in config.enabled_symbols:
            symbol_state = self.state.symbols.setdefault(
                symbol_config.symbol,
                SymbolState(symbol=symbol_config.symbol),
            )
            self.symbols[symbol_config.symbol] = SymbolEngine(symbol_config, symbol_state)
