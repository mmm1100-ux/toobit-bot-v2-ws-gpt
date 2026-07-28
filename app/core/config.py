from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.enums import MarginType, TriggerBy
from app.core.errors import ConfigError


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ConfigError(f"{field} must be a decimal number") from exc


@dataclass(frozen=True, slots=True)
class ExchangeConfig:
    api_key: str
    api_secret: str
    base_url: str = "https://api.toobit.com"
    ws_url: str = "wss://stream.toobit.com/quote/ws/v1"
    recv_window: int = 5000
    server_time_sync_seconds: int = 60


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    timezone: str = "UTC"
    timeframe: str = "5m"
    dry_run: bool = True
    state_path: str = "state.json"
    log_path: str = "logs/bot.log"


@dataclass(frozen=True, slots=True)
class SessionConfig:
    name: str
    collection_start: str
    collection_end: str
    expire_time: str
    collection_start_minute: int
    collection_end_minute: int
    expire_minute: int

    @property
    def crosses_midnight(self) -> bool:
        return self.expire_minute <= self.collection_start_minute


@dataclass(frozen=True, slots=True)
class SymbolConfig:
    symbol: str
    enabled: bool
    margin_type: MarginType
    leverage: int
    wallet_percent: Decimal
    take_profit_percent: Decimal
    stop_loss_percent: Decimal
    trigger_by: TriggerBy
    sessions: tuple[SessionConfig, ...]


@dataclass(frozen=True, slots=True)
class BotConfig:
    exchange: ExchangeConfig
    runtime: RuntimeConfig
    symbols: tuple[SymbolConfig, ...]

    @property
    def enabled_symbols(self) -> tuple[SymbolConfig, ...]:
        return tuple(symbol for symbol in self.symbols if symbol.enabled)


def _minute(text: str, field: str) -> int:
    try:
        hour_text, minute_text = text.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (ValueError, AttributeError) as exc:
        raise ConfigError(f"{field} must use HH:MM format") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ConfigError(f"{field} must be a valid 24-hour time")
    return hour * 60 + minute


def _session(raw: dict[str, Any], symbol: str) -> SessionConfig:
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ConfigError(f"{symbol}: every session needs a non-empty name")
    start = str(raw.get("collection_start", ""))
    end = str(raw.get("collection_end", ""))
    expire = str(raw.get("expire_time", ""))
    start_minute = _minute(start, f"{symbol}.{name}.collection_start")
    end_minute = _minute(end, f"{symbol}.{name}.collection_end")
    expire_minute = _minute(expire, f"{symbol}.{name}.expire_time")
    if start_minute == end_minute:
        raise ConfigError(f"{symbol}.{name}: collection window cannot be empty")
    if end_minute < start_minute:
        raise ConfigError(f"{symbol}.{name}: collection window may not cross midnight")
    if expire_minute == end_minute:
        raise ConfigError(f"{symbol}.{name}: expire_time must be after collection_end")
    if expire_minute > start_minute and expire_minute < end_minute:
        raise ConfigError(f"{symbol}.{name}: expire_time cannot be inside collection window")
    return SessionConfig(name, start, end, expire, start_minute, end_minute, expire_minute)


def _symbol(raw: dict[str, Any]) -> SymbolConfig:
    symbol = str(raw.get("symbol", "")).strip().upper()
    if not symbol:
        raise ConfigError("every symbol entry needs symbol")
    try:
        margin_type = MarginType(str(raw.get("margin_type", "CROSS")).upper())
        trigger_by = TriggerBy(str(raw.get("trigger_by", "CONTRACT_PRICE")).upper())
    except ValueError as exc:
        raise ConfigError(f"{symbol}: invalid margin_type or trigger_by") from exc
    leverage = int(raw.get("leverage", 0))
    if not 1 <= leverage <= 125:
        raise ConfigError(f"{symbol}: leverage must be between 1 and 125")
    wallet_percent = _decimal(raw.get("wallet_percent"), f"{symbol}.wallet_percent")
    tp = _decimal(raw.get("take_profit_percent"), f"{symbol}.take_profit_percent")
    sl = _decimal(raw.get("stop_loss_percent"), f"{symbol}.stop_loss_percent")
    if not Decimal("0") < wallet_percent <= Decimal("100"):
        raise ConfigError(f"{symbol}: wallet_percent must be > 0 and <= 100")
    if tp <= 0 or sl <= 0:
        raise ConfigError(f"{symbol}: TP and SL percentages must be positive")
    sessions = tuple(_session(item, symbol) for item in raw.get("sessions", []))
    if not sessions:
        raise ConfigError(f"{symbol}: at least one session is required")
    names = [session.name for session in sessions]
    if len(names) != len(set(names)):
        raise ConfigError(f"{symbol}: session names must be unique")
    return SymbolConfig(
        symbol=symbol,
        enabled=bool(raw.get("enabled", True)),
        margin_type=margin_type,
        leverage=leverage,
        wallet_percent=wallet_percent,
        take_profit_percent=tp,
        stop_loss_percent=sl,
        trigger_by=trigger_by,
        sessions=sessions,
    )


def load_config(path: str | Path = "config.json") -> BotConfig:
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {config_path}: {exc}") from exc

    exchange_raw = raw.get("exchange", {})
    runtime_raw = raw.get("runtime", {})
    timezone_name = str(runtime_raw.get("timezone", "UTC"))
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"unknown timezone: {timezone_name}") from exc

    exchange = ExchangeConfig(
        api_key=os.getenv("TOOBIT_API_KEY", ""),
        api_secret=os.getenv("TOOBIT_API_SECRET", ""),
        base_url=str(exchange_raw.get("base_url", "https://api.toobit.com")).rstrip("/"),
        ws_url=str(exchange_raw.get("ws_url", "wss://stream.toobit.com/quote/ws/v1")),
        recv_window=int(exchange_raw.get("recv_window", 5000)),
        server_time_sync_seconds=int(exchange_raw.get("server_time_sync_seconds", 60)),
    )
    runtime = RuntimeConfig(
        timezone=timezone_name,
        timeframe=str(runtime_raw.get("timeframe", "5m")),
        dry_run=bool(runtime_raw.get("dry_run", True)),
        state_path=str(runtime_raw.get("state_path", "state.json")),
        log_path=str(runtime_raw.get("log_path", "logs/bot.log")),
    )
    symbols = tuple(_symbol(item) for item in raw.get("symbols", []))
    if not symbols:
        raise ConfigError("at least one symbol must be configured")
    names = [symbol.symbol for symbol in symbols]
    if len(names) != len(set(names)):
        raise ConfigError("symbols must be unique")
    if not any(symbol.enabled for symbol in symbols):
        raise ConfigError("at least one symbol must be enabled")
    if not runtime.dry_run and (not exchange.api_key or not exchange.api_secret):
        raise ConfigError("TOOBIT_API_KEY and TOOBIT_API_SECRET are required in live mode")
    return BotConfig(exchange=exchange, runtime=runtime, symbols=symbols)
