# Toobit Bot V2 WS GPT

Multi-symbol Toobit USDT-M breakout bot rebuild.

## Implemented foundation

- Type-safe JSON configuration
- Independent leverage and sessions per symbol
- Secrets loaded only from environment variables
- Independent symbol and session state
- UTC/IANA timezone-aware scheduler
- Range collection from closed-candle high/low shadows
- Expiration state emitted once per session
- Multi-symbol market WebSocket subscription
- Closed-candle detection from live kline bucket transitions
- Public REST kline client and automatic missing-candle recovery
- Close-confirmed long/short breakout strategy
- One signal reservation per symbol session
- Signal callback routing for the upcoming order manager
- Tests for configuration, range building, expiry, WebSocket closure, REST recovery, and breakout routing

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
- [ ] Order manager with market entry and attached TP/SL
- [ ] Expire manager: remove TP/SL, then close the position
- [ ] Atomic persistence and structured logging
- [ ] Integration tests and release ZIP
