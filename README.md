# Toobit Bot V2 WS GPT

Multi-symbol Toobit USDT-M breakout bot rebuild.

## Implemented

- Type-safe multi-symbol configuration and independent sessions
- Market WebSocket with reconnect, ping/pong, closed-candle detection, and REST gap recovery
- Close-confirmed LONG/SHORT breakout strategy with one trade reservation per session
- Signed private REST client, balance-based sizing, exchange-rule rounding, market entry, and attached TP/SL
- Safe expiration flow: cancel orders, close LONG/SHORT or hedge positions, retry partial closes, and verify flat
- Atomic versioned state persistence and complete restart recovery
- Structured JSON logging
- Integrated runtime coordinating market data, strategy, execution, expiration, and persistence
- End-to-end runtime tests and GitHub Actions CI for Python 3.11 and 3.12
- Reproducible release ZIP builder

## Security

Never store API credentials in `config.json` or Git. Set them in the process environment:

```powershell
$env:TOOBIT_API_KEY="..."
$env:TOOBIT_API_SECRET="..."
```

Any API key previously included in a shared ZIP or repository must be deleted and replaced.

## Setup

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy config.example.json config.json
python -m app.main --config config.json --check
pytest
```

Start the bot in dry-run mode:

```powershell
python -m app.main --config config.json
```

Build the distributable archive:

```powershell
python scripts/build_release.py
```

The archive is created at `dist/toobit-bot-v2.zip`.

## Production checklist

1. Keep `dry_run=true` while validating symbols, schedules, wallet percentages, leverage, TP/SL, and timezone.
2. Revoke all previously exposed API keys and create a restricted futures-trading key without withdrawal permission.
3. Run `python -m app.main --config config.json --check` and the complete test suite.
4. Validate contract quantity and price rules against the live exchange before disabling dry-run.
5. Start with minimal capital and monitor JSON logs, open orders, positions, and expiration cleanup.

## Expiration safety sequence

At each configured expiration time the bot cancels open orders on both directions, queries all positions, closes each LONG and SHORT side, verifies the symbol is flat, and retries bounded partial-close or race conditions. Ambiguous timeouts are reconciled through read-only queries and are never silently treated as success.

## Project status

All planned implementation phases are complete. Live exchange certification remains an operational step and must be performed with a newly issued restricted API key and minimal capital before normal use.
