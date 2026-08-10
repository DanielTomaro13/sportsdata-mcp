# Odds-API.io (`oddsapiio`) — 274 bookmakers, 34 sports

**5 tools · BYO key · two endpoints verified open**

The widest bookmaker index in this catalogue, from
[odds-api.io](https://odds-api.io).

## It is v3, not v2

The vendor's own pages still show `/v2/` paths. **Every one of them returns
`404 page not found`.** The live API is `/v3/`. This was caught by probing before the
spec was written; a spec built from the documentation would have shipped with all five
tools broken. If a call here 404s, check the version segment first.

## What is verified

Two endpoints are **open** and were probed live on 2026-08-10:

| Endpoint | Verified result |
|---|---|
| `oddsapiio_sports` | 34 sports |
| `oddsapiio_bookmakers` | 274 bookmakers, 263 currently active |

The other three return `401 {"error":"You need to provide a valid apiKey"}`, so their
shapes come from the vendor's documentation and are marked unverified.

## Getting a key

```bash
export ODDS_API_IO_KEY=your_key_here
```

Sign up at <https://odds-api.io>. The two open endpoints work without it.

## Tools

| Tool | Needs a key | What it gives you |
|---|---|---|
| `oddsapiio_sports` | no | The 34 sport slugs everything else filters on |
| `oddsapiio_bookmakers` | no | 274 bookmakers and whether each is active |
| `oddsapiio_leagues` | yes | Leagues within a sport |
| `oddsapiio_events` | yes | Upcoming events, without prices |
| `oddsapiio_odds` | yes | Prices for one event across the indexed books |

## The sports it covers

```
football        basketball   tennis         baseball       american-football
ice-hockey      esports      darts          mixed-martial-arts   boxing
handball        volleyball   snooker        table-tennis   rugby
cricket         water-polo   futsal         beach-volleyball     aussie-rules
floorball       squash       beach-soccer   lacrosse       curling
padel           bandy        gaelic-football     beach-handball  athletics
badminton       cross-country     golf      cycling
```

Verified live, not copied from marketing. The long tail here — padel, bandy, floorball,
gaelic football — is genuinely not available anywhere else in this catalogue.

## Choosing between the three odds aggregators

| | Books | Sports | Best at |
|---|---:|---:|---|
| `theoddsapi` | ~40 | 70+ | Historical snapshots for CLV work |
| `oddsapiio` | **274** | 34 | Breadth of books, and obscure sports |
| `sportsgameodds` | dozens | US-led | **Player props**, with stable market ids |

For Australian markets, the direct providers (`sportsbet`, `tab`, `pointsbet`, `betr`,
`betfair`, `unibet`) remain deeper and live — an aggregator is a second opinion, not a
replacement.

## See also

- [TheOddsAPI.md](TheOddsAPI.md), [SportsGameOdds.md](SportsGameOdds.md)
