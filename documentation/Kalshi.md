# Kalshi API Documentation

Reference for the **Kalshi** prediction-market read surface as modelled by the
packaged provider spec (`src/sportsdata_mcp/specs/kalshi.yaml`). Kalshi is the
CFTC-regulated US event-contract exchange.

> Probed live 2026-06-11. One host serves everything; **market data is public —
> no API key required**. An API key is **optional**: when configured, every
> request is RSA-PSS-signed, which buys Kalshi's higher authenticated rate
> limits on the same read endpoints. The portfolio/trading surfaces a key also
> unlocks stay **out of scope** (repo-wide no-money invariant).

## Optional API key

Set these env vars (or `secrets:` entries) and restart — every request gains
the `KALSHI-ACCESS-KEY` / `-SIGNATURE` / `-TIMESTAMP` headers; unset, the
provider runs anonymously (never an error — doctor shows
`SKIP: optional auth not configured`):

| Env var | Value |
|---|---|
| `KALSHI_API_KEY_ID` | The API key id from kalshi.com account settings |
| `KALSHI_PRIVATE_KEY` | The RSA private key as PEM text… |
| `KALSHI_PRIVATE_KEY_PATH` | …or a path to the PEM file (either works) |

Signing needs the `cryptography` package (`pip install "sportsdata-mcp[kalshi-auth]"`).
Whoever runs the server supplies their own key — it is never stored in the repo
and never appears in tool output.

## Hosts

| Host | Service | Auth |
|---|---|---|
| `api.elections.kalshi.com/trade-api/v2` | All market data | ❌ none |

## The id chain

```
kalshi_series_list(category)        →  series_ticker   (e.g. KXNBA)
kalshi_events(series_ticker)        →  event_ticker    (series + date/strike)
kalshi_markets(event_ticker)        →  ticker          (event + outcome leg)
kalshi_market / kalshi_orderbook / kalshi_trades / kalshi_candlesticks(ticker)
```

A market ticker embeds its series as the prefix before the first `-`
(`KXNBA-26JUN15-LAL` → series `KXNBA`) — `kalshi_candlesticks` needs both.
Prices are dollar-denominated (`*_dollars` fields); volumes/open interest use
the `*_fp` fixed-point fields.

## Markets — group `kalshi.markets`

| Tool | Path | Capability |
|---|---|---|
| `kalshi_markets` | `/markets?status=&event_ticker=&series_ticker=` | `prediction.markets_list` |
| `kalshi_market` | `/markets/{ticker}` | `prediction.market_detail` |
| `kalshi_orderbook` | `/markets/{ticker}/orderbook?depth=` | `prediction.market_prices` |
| `kalshi_trades` | `/markets/trades?ticker=` | `prediction.trades` |
| `kalshi_candlesticks` | `/series/{seriesTicker}/markets/{ticker}/candlesticks?start_ts=&end_ts=&period_interval=` | `prediction.price_history` |
| `kalshi_candlesticks_batch` | `/markets/candlesticks?market_tickers=` | `prediction.price_history` |

## Events & series — group `kalshi.events`

| Tool | Path | Capability |
|---|---|---|
| `kalshi_events` | `/events?status=&series_ticker=&with_nested_markets=` | `prediction.events_list` |
| `kalshi_event` | `/events/{eventTicker}?with_nested_markets=true` | `prediction.events_list` |
| `kalshi_series_list` | `/series?category=` (category required: Sports, Politics, Economics, Financials, Climate and Weather, Entertainment, …) | `prediction.events_list` |
| `kalshi_series` | `/series/{seriesTicker}` | `prediction.events_list` |
| `kalshi_milestones` | `/milestones` | — (dated catalysts linked to event tickers) |
| `kalshi_mve_collections` | `/multivariate_event_collections` | `prediction.events_list` (parlay-style combo products) |
| `kalshi_mve_collection` | `/multivariate_event_collections/{collectionTicker}` | `prediction.events_list` |
| `kalshi_structured_targets` | `/structured_targets?page_size=&type=` | — (entity registry: players, companies) |
| `kalshi_structured_target` | `/structured_targets/{id}` | — |

## Exchange — group `kalshi.exchange`

| Tool | Path |
|---|---|
| `kalshi_exchange_status` | `/exchange/status` |
| `kalshi_exchange_schedule` | `/exchange/schedule` |
| `kalshi_exchange_announcements` | `/exchange/announcements` |

## Not modelled

- **Portfolio / orders / fills** (`/portfolio/*`) — trading surfaces; out of
  scope for a read-only data provider (the optional key here signs *reads* only).
- The WebSocket streaming API (not REST).
- The legacy demo environment (`demo-api.kalshi.co`).

## Cross-provider comparison

The `prediction.*` capability tags line Kalshi up against Polymarket via
`list_tools_by_capability`:

- **`prediction.markets_list`** → `kalshi_markets` vs `polymarket_markets` /
  `polymarket_clob_markets` — e.g. compare both venues' prices on the same
  real-world event (Fed decision, election, NBA series).
- **`prediction.market_prices`** → `kalshi_orderbook` vs `polymarket_book`.
- **`prediction.price_history`** → `kalshi_candlesticks` vs
  `polymarket_price_history`.
- Sports event contracts also sit naturally next to the bookmaker
  `sport.event_markets` tools for odds-vs-prediction-market comparisons.
