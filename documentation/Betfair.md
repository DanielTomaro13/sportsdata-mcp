# Betfair Exchange (Australia) API Documentation

Unofficial reference for the open **read-only web APIs** behind
`betfair.com.au/exchange`, keyed by the public `_ak` web key (a query param, not a
secret). Verified against live traffic (probed 2026-06-05). The exchange's
**back/lay prices are the sharpest "true odds"** of any book here.

> Comma-separated id params (`marketIds`, `eventIds`) are **`string_csv`** — pass a
> **list** (e.g. `["1.258654642"]`); the engine serialises to CSV. Market ids look
> like `1.258654642`; event ids are integers like `35680153`.

## Hosts

| Host | Role |
|---|---|
| `ero.betfair.com.au` | Market prices/state — the `bymarket` exchange odds feed. |
| `scan-inbf.betfair.com.au` | The navigation graph (sport → meeting → event → market). |
| `ips.betfair.com.au` | In-play service: scores, event details, timelines, broadcast. |
| `cos.betfair.com.au` | Cash-out availability. |

## Discovery flow

```
betfair_navigation(nodeIds=["EVENT_TYPE:7"], attachments=["MENU","EVENT","MARKET"], maxOutDistance=4)
   → walk the tree to a MARKET node → marketId (1.xxxxxxxxx)
betfair_market_prices(marketIds=[marketId])     → back/lay prices + runners + state
betfair_event_details(eventIds=[eventId])        → in-play event detail
betfair_scores(eventIds=[eventId])               → live score
```

`EVENT_TYPE` ids: `7` Horse Racing, `4339` Greyhounds, `1` Soccer, `2` Tennis,
`7522` Basketball, … (discover them from the navigation root).

## Exchange — group `betfair.exchange`

| Tool | Host / Path | Capability |
|---|---|---|
| `betfair_market_prices` | `ero` `/www/sports/exchange/readonly/v1/bymarket` | `sport.event_markets`, `sport.prices` |
| `betfair_cashout` | `cos` `/cashout-service/readonly/v1.0/availableCashoutMarkets` | — |

`betfair_market_prices` `types` (CSV, all default-on) selects the data sections:
`MARKET_STATE`, `MARKET_RATES`, `MARKET_DESCRIPTION`, `EVENT`, `RUNNER_DESCRIPTION`,
`RUNNER_STATE`, `RUNNER_EXCHANGE_PRICES_BEST` (the back/lay ladder),
`RUNNER_METADATA`, `MARKET_LINE_RANGE_INFO`. Prices/volumes are in `currencyCode`
(default `AUD`).

## Navigation — group `betfair.navigation`

| Tool | Host / Path | Capability |
|---|---|---|
| `betfair_navigation` | `scan` `/www/sports/navigation/v2/graph/bynode` | `sport.competitions_list` |

A graph walk: start from `nodeIds` (an `EVENT_TYPE:n`, `COMP:n`, or `EVENT:n`) and
walk `maxOutDistance` levels down (and `maxInDistance` up). Node types are
`EVENT_TYPE`, `MENU`, `EVENT`, `MARKET`. This is how you resolve market ids to feed
`betfair_market_prices`.

## In-play — group `betfair.inplay` (`ips`)

| Tool | Path | Capability |
|---|---|---|
| `betfair_scores` | `/inplayservice/v1/scores` | `sport.match_score` |
| `betfair_event_details` | `/inplayservice/v1/eventDetails` | `sport.in_play`, `sport.match_detail` |
| `betfair_event_timeline` | `/inplayservice/v1/eventTimeline` | `sport.match_score` |
| `betfair_scores_broadcast` | `/inplayservice/v1/scoresAndBroadcast` | `sport.match_score` |

## Cross-provider comparison

Betfair's exchange prices are the sharpest reference of all, so comparing them
against the soft books is the headline use:

- `sport.prices` → `betfair_market_prices` alongside `pinnacle_matchup_markets`,
  `tab_match`, `sportsbet_event_markets`.
- `sport.event_markets` → also `pointsbet_event`, `unibet_kambi_call`,
  `betr_sports_category`, `fanduel_sb_call`.
- `sport.match_score` → `betfair_scores` alongside `sportsbet_event_commentary`,
  `fanduel_sb_live_score`.

## Not modelled

- `apieds.betfair.com.au` (`next-races`, `meeting-races`, `sports-highlights`,
  `multimarkets`, `capi-content`) — sits behind a Cloudflare JS challenge that
  blocks datacenter IPs (it works from a residential browser). Racing is still
  fully covered via `betfair_navigation` (EVENT_TYPE:7) → `betfair_market_prices`.
- `appsync.navql.betfair.com.au/graphql` (`nextToJump`) — returns 401 without a
  logged-in session.
- `betfair-data-supplier` (herokuapp) — needs an `ssoid`.
- `ips/soccerEventStats` — returns `null` for most events; low value.
- Account / wagering surfaces — out of scope for a read-only data provider.
