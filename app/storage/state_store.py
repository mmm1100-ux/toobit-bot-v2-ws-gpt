from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.core.errors import StateError
from app.core.state import BotState, state_from_dict, state_to_dict


class AtomicStateStore:
    """Thread-safe JSON state store using fsync + atomic replace."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> BotState:
        with self._lock:
            if not self.path.exists():
                return BotState()
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StateError(f"cannot read state file {self.path}: {exc}") from exc
            try:
                return state_from_dict(raw)
            except (KeyError, TypeError, ValueError) as exc:
                raise StateError(f"invalid state file {self.path}: {exc}") from exc

    def save(self, state: BotState) -> None:
        payload = json.dumps(state_to_dict(state), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(f".{self.path.name}.tmp")
            try:
                with temp.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, self.path)
                self._fsync_directory()
            except OSError as exc:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass
                raise StateError(f"cannot persist state file {self.path}: {exc}") from exc

    def _fsync_directory(self) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
