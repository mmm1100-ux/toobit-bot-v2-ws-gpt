from __future__ import annotations

from datetime import datetime

from app.expire.manager import ExpireManager
from app.expire.models import ExpireReport
from app.symbols.engine import SymbolEngine


class ExpireCoordinator:
    """Runs one symbol cleanup and marks due sessions expired only after flat verification."""

    def __init__(self, manager: ExpireManager) -> None:
        self.manager = manager

    def run_due(self, engine: SymbolEngine, now: datetime) -> ExpireReport | None:
        due = engine.due_expirations(now)
        if not due:
            return None
        report = self.manager.expire_symbol(engine.config.symbol)
        if not report.verified_flat:
            raise RuntimeError("expire manager returned without flat verification")
        for _, state in due:
            state.expire()
        return report
