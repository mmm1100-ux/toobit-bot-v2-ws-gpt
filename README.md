# Toobit Bot V2 WS GPT

Multi-symbol Toobit USDT-M breakout bot rebuild.

## Implemented foundation

- Type-safe JSON configuration
- Independent leverage and sessions per symbol
- Secrets loaded only from environment variables
- Independent symbol and session state
- UTC/IANA timezone-aware scheduler
- Range collection from closed-candle high/low shadows
- Multi-symbol market WebSocket subscription
- Closed-candle detection from live kline bucket transitions
- Public REST kline client and automatic missing-candle recovery
- Close-confirmed long/short breakout strategy
- One signal reservation per symbol session
- Signed Toobit private REST client
- Total futures wallet-balance sizing
- Quantity and price rounding with exchange rules
- Per-symbol leverage and margin-mode configuration helpers
- Market entry with attached TP/SL
- Explicit rejection versus unknown-order-outcome safety policy
- Expire Manager that cancels BUY and SELL open orders, including TP/SL and pending close orders
- LONG, SHORT, and hedge-mode position cleanup using Toobit Flash Close
- Post-close flat-position verification with bounded retries
- Conservative timeout reconciliation for cancel and close operations
- Session expiration only after the symbol is verified flat
- Atomic state writes using temp file, fsync, and replace
- Full Decimal/enums/candle/session restoration after restart
- Versioned state migration and fail-closed corrupt-state handling
- Structured JSON logs to console and file
- Tests for strategy, execution, expiration, persistence, migration, and interrupted writes

## Persistence safety

State is written to a temporary file, flushed to disk, and atomically moved over the previous state. A failed write does not delete the last valid state. On startup, corrupt or unsupported future-version state fails closed instead of silently resetting sessions and risking a duplicate trade.

## Expiration safety sequence

At each configured expiration time the bot performs this sequence for the affected symbol:

1. Cancel all open orders on both BUY and SELL directions.
2. Query all current positions for the symbol.
3. Flash-close every open LONG and SHORT side independently.
4. Re-query positions and verify that the symbol is flat.
5. Re-cancel orders and retry if a partial close or order race is detected.
6. Mark the due session expired only after flat verification succeeds.

Timeouts are not assumed successful. The bot queries open orders or positions to reconcile ambiguous outcomes. If it cannot prove that orders are canceled and positions are flat, it raises an expiration error and leaves the session unfinalized.

## Security

Never store API credentials in `config.json` or Git. Set them in the process environment:

```powershell
$env:TOOBIT_API_KEY="..."
$env:TOOBIT_API_SECRET="..."
```

Any API key previously included in a shared ZIP or repository must be deleted and replaced.

## Local setup

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy config.example.json config.json
python -m app.main --config config.json
pytest
```

Keep `dry_run` enabled until exchange integration tests are complete.

## Roadmap

- [x] Architecture: multi-symbol engine, session engine, state model
- [x] Config rewrite and validation
- [x] WebSocket manager and REST candle recovery
- [x] Public Toobit REST market-data client
- [x] Breakout strategy and signal routing
- [x] Order manager with market entry and attached TP/SL
- [x] Expire manager: remove TP/SL, close all position sides, and verify flat
- [x] Atomic persistence, restart recovery, migrations, and structured logging
- [ ] Integration tests and release ZIP
