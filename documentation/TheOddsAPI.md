# The Odds API (`theoddsapi`) — international odds aggregator

**6 tools · BYO key · shapes unverified**

Odds from ~40 international bookmakers across 70+ sports, from
[the-odds-api.com](https://the-odds-api.com).

## Why this one is worth the signup

It is the only genuine **coverage** gap this catalogue has. The server is deep on
Australian books — Sportsbet, TAB, PointsBet, BetR, Unibet, Entain, Dabble — plus Betfair
and Pinnacle, and blind outside that. The Odds API is how you price a Bundesliga match
against European books, or an NFL game against US ones.

It aggregates rather than integrating, so it is **shallower per book** than the direct
providers here. Use the direct ones for AU markets and this for everywhere else.

## Getting a key

```bash
export THE_ODDS_API_KEY=your_key_here
```

Sign up at <https://the-odds-api.com>. Free tier: **500 requests per month**.

Verified live 2026-08-10 (keyless): the host and paths exist and return a clean
`401 {"message":"API key is missing","error_code":"MISSING_KEY"}`.

## Quota is the thing to watch, and it is not 1 per call

The cost of a request is **(number of markets) × (number of regions)**:

```
markets=h2h,spreads,totals  ×  regions=us,uk,eu,au   =  12 credits for ONE call
markets=h2h                 ×  regions=au            =   1 credit
```

At 500/month, the first pattern gives you ~41 calls. The second gives you 500. Keep both
lists as narrow as the question allows.

Every response carries your position in headers:

```
x-requests-remaining: 437
x-requests-used: 63
```

**Two endpoints cost nothing**: `theoddsapi_sports` and `theoddsapi_events`. Use them to
find sport keys and event ids before spending quota on prices.

## Tools

| Tool | Quota | What it gives you |
|---|---|---|
| `theoddsapi_sports` | **free** | Every sport/competition with its `sport_key` — start here |
| `theoddsapi_events` | **free** | Upcoming events without prices — cheap way to get event ids |
| `theoddsapi_odds` | markets × regions | Odds for a competition across many books |
| `theoddsapi_event_odds` | markets × regions | One event, **including player props** |
| `theoddsapi_scores` | 1–2 | Live and recently completed scores |
| `theoddsapi_historical_odds` | paid add-on | Odds as they stood at a past timestamp |

## Response shape, and the three things that catch people

**Outcome `name` is a team name, not `home`/`away`:**

```json
{"key": "h2h", "outcomes": [{"name": "Arsenal", "price": 1.85},
                            {"name": "Chelsea", "price": 4.20}]}
```

Match it against the event's `home_team` / `away_team` to work out which side you are
looking at. There is no side flag.

**`point` appears only on spreads and totals**, not on h2h.

**Player props live on `theoddsapi_event_odds` only.** The competition-wide
`theoddsapi_odds` call does not carry them, whatever markets you ask for. On props, the
player's name is in `description`, not `name`.

**Scores are strings**, and `scores` is `null` until a game starts.

## The historical endpoint is a different shape

`theoddsapi_historical_odds` wraps everything in a snapshot envelope:

```json
{"timestamp": "...", "previous_timestamp": "...", "next_timestamp": "...", "data": [ ... ]}
```

The `data` array is the same shape as the live call. Historical access is a **paid
add-on** — the free tier returns 401/422 here, which is easy to mistake for a bad key.

The `previous_timestamp` / `next_timestamp` fields are how you walk backwards through a
market's history without guessing intervals — that is the CLV workflow.

## Worked example: is the AU price good?

1. `theoddsapi_sports` (free) → `soccer_epl`.
2. `theoddsapi_odds` with `regions: [eu], markets: [h2h]` → 1 credit, European consensus.
3. `sportsbet_event_markets` / `pinnacle_matchup_markets` → the AU price, live and deeper.
4. Compare. Pinnacle is the sharper reference; the European spread tells you whether an
   AU outlier is an edge or an error.

## Choosing between the three odds aggregators

| | Books | Sports | Best at |
|---|---:|---:|---|
| **`theoddsapi`** | ~40 | 70+ | **Historical snapshots** for CLV work |
| `oddsapiio` | 274 | 34 | Breadth of books, obscure sports |
| `sportsgameodds` | dozens | US-led | Player props with stable market ids |

## See also

- [OddsAPIio.md](OddsAPIio.md), [SportsGameOdds.md](SportsGameOdds.md)
- [Pinnacle.md](Pinnacle.md) — the sharpest single book, keyless
- [Betfair.md](Betfair.md) — exchange prices, keyless
