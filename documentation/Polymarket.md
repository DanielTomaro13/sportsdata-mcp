# Polymarket API Documentation

Reference for the **Polymarket** read surface as modelled by the packaged
provider spec (`src/sportsdata_mcp/specs/polymarket.yaml`). Polymarket is the
largest crypto prediction market (binary outcome tokens on a CLOB, settled on
Polygon).

> Spec written 2026-06-11 from the official docs (docs.polymarket.com) and
> Polymarket's own agent-skills reference; response shapes are
> regression-checked by the CI contract job from US runners. **No auth for any
> read endpoint.** The wallet/API keys Polymarket's SDKs use are for ORDER
> PLACEMENT only — trading is out of scope for this read-only provider
> (repo-wide no-money invariant), so there are no secrets to configure.

## ⚠️ Geo-gating

Polymarket drops connections **at the network edge** from restricted
jurisdictions — observed live: from Australian IPs every host (including
`polymarket.com` itself) times out on connect. From a blocked region these
tools fail with `TRANSPORT_ERROR` and `doctor` reports FAIL. Run from an
unrestricted region (US cloud, GitHub runners) or a VPN.

## Hosts

| Host | Service | Auth |
|---|---|---|
| `gamma-api.polymarket.com` | Discovery: markets / events / tags / search | ❌ none |
| `clob.polymarket.com` | Price plane: books, best prices, midpoints, spreads, history | ❌ none (reads) |
| `data-api.polymarket.com` | Public trade tape + holders | ❌ none |

## The id chain

```
polymarket_events / polymarket_markets   →  market {id, conditionId, clobTokenIds}
clobTokenIds[0|1] (YES/NO outcome token) →  polymarket_book / price / midpoint /
                                            spread / price_history (token_id)
conditionId                              →  polymarket_trades / polymarket_holders
```

Gamma list responses are **top-level arrays**. `clobTokenIds` is often a
JSON-encoded string — parse it before passing a token id to the CLOB tools.

## Discovery — group `polymarket.gamma`

| Tool | Path | Capability |
|---|---|---|
| `polymarket_markets` | `/markets?active=&closed=&order=volume24hr&tag_id=` | `prediction.markets_list` |
| `polymarket_market` | `/markets/{id}` | `prediction.market_detail` |
| `polymarket_events` | `/events?active=&closed=&order=&slug=&series_id=` | `prediction.events_list` |
| `polymarket_event` | `/events/{id}` | `prediction.events_list` |
| `polymarket_series_list` | `/series` | `prediction.events_list` (series → events → markets hierarchy) |
| `polymarket_series` | `/series/{id}` | `prediction.events_list` |
| `polymarket_sports` | `/sports` | — (sports metadata: tag ids, resolution links, series) |
| `polymarket_tags` | `/tags` | — (tag ids feed the `tag_id` filters) |
| `polymarket_search` | `/public-search?q=` | — |

## Price plane — group `polymarket.clob`

| Tool | Path | Capability |
|---|---|---|
| `polymarket_book` | `/book?token_id=` | `prediction.market_prices` |
| `polymarket_price` | `/price?token_id=&side=buy\|sell` | `prediction.market_prices` |
| `polymarket_midpoint` | `/midpoint?token_id=` | `prediction.market_prices` |
| `polymarket_spread` | `/spread?token_id=` | `prediction.market_prices` |
| `polymarket_price_history` | `/prices-history?market=<token_id>&interval=1d` | `prediction.price_history` |
| `polymarket_clob_markets` | `/markets?next_cursor=` | `prediction.markets_list` |

## Trade tape — group `polymarket.data`

| Tool | Path | Capability |
|---|---|---|
| `polymarket_trades` | `/trades?market=<conditionId>` | `prediction.trades` |
| `polymarket_holders` | `/holders?market=<conditionId>` | — |

## Not modelled

- **Order placement / management** (CLOB POST endpoints, L1/L2 wallet auth) and
  anything touching balances or positions for a *specific* authed user — out of
  scope for a read-only data provider.
- The WebSocket realtime channels (not REST).
- The batch POST quote endpoints (`/books`, `/prices`, `/midpoints`, `/spreads`)
  — the single-token GET forms cover the read path; batch can be added if a
  consumer needs them.
- The Goldsky subgraph (GraphQL over on-chain data; the REST surfaces above
  carry the same market data).

## Cross-provider comparison

Tagged `prediction.*`, comparable with Kalshi via `list_tools_by_capability`:

- **`prediction.markets_list`** / **`prediction.events_list`** →
  `polymarket_markets`/`polymarket_events` vs `kalshi_markets`/`kalshi_events`.
- **`prediction.market_prices`** → `polymarket_book` vs `kalshi_orderbook` —
  same-event price comparison across the two largest prediction venues.
- **`prediction.price_history`** → `polymarket_price_history` vs
  `kalshi_candlesticks`.
- Sports markets also compose with bookmaker `sport.event_markets` tools for
  bookie-vs-prediction-market lines.
