# PuntersEdge — `puntersedge.online` (AU + NZ racing and sports odds aggregator)

An Australian and New Zealand odds API that aggregates the AU bookmaker panel behind
one key, rather than being a bookmaker itself. Host `api.puntersedge.online`, OpenAPI
3.1 at [`/openapi.json`](https://api.puntersedge.online/openapi.json), human docs at
[puntersedge.online/developers](https://puntersedge.online/developers?utm_source=sportsdata_mcp).

Provider id `puntersedge`, 13 tools across three groups. Demo probed live 2026-09-17.

The panel was **14 Australian bookmakers** when this was written (2026-09-17), and 12 on
the New Zealand cards. That number moves, so read it from the publisher's own live
[`coverage-report.json`](https://puntersedge.online/coverage-report.json) —
`served_bookmaker_count` and `bookmakers[]` — rather than trusting this line. Betfair
and Pinnacle are ingested but deliberately withheld from responses, and are listed under
`excluded_bookmakers` with the reason; for those two, use the `betfair` and `pinnacle`
providers here directly.

## Why it is here, given the AU books are already integrated

This overlaps `sportsbet`, `tab`, `betr`, `pointsbet`, `entain` and `unibet` — but it
answers three questions none of them can:

- **It is not geo-blocked.** The AU books are licensed for Australia and block everyone
  else at the edge. This is an ordinary public HTTPS API, so it is the only way to see
  Australian racing prices from outside Australia — and the only AU-odds provider here
  whose tools run in CI.
- **New Zealand racing**, which nothing else in the catalogue covers.
- **A permanent closing-line archive** (`stats.closing_odds`), so CLV work and
  backtesting on AU racing are possible without having polled it yourself.

For a single book's own racecard, deep or exotic markets, or SGM pricing, the direct
providers remain better — an aggregator flattens those surfaces away.

## Auth

`X-API-Key` header from `PUNTERSEDGE_API_KEY`, declared `optional`. Two consequences
worth knowing:

1. **The three `puntersedge.demo` tools never send a key** and return real live data, so
   this provider is part of the `free` preset. They are rate-limited to **30 requests
   per minute per IP** and are truncated samples, not the full feed.
2. A missing key never breaks startup. Only the keyed tools refuse, and they refuse
   loudly — the engine names `PUNTERSEDGE_API_KEY` and quotes the upstream body.

A free key is 1,500 credits/month with no card, from
[puntersedge.online/api](https://puntersedge.online/api?utm_source=sportsdata_mcp).
**Every tool's summary quotes that endpoint's own credit cost** (1–5 credits; the
closing-lines CSV format is 20), taken from the API's published descriptions rather
than estimated.

### Shapes: what is verified and what is not

`shapes_verified: false` at provider level, with the three demo tools overriding it to
`true`. The demo hints are transcribed from real responses received on 2026-09-17. The
**keyed** hints are not: we hold no key, so they come from the vendor's own
machine-readable OpenAPI schema and its worked examples. That is a good deal better
than prose, but it is still not a live probe, so those tools carry the standard
unverified caveat. A PR flipping them to verified, with corrections, is welcome from
anyone who runs them with a key.

### Errors

Every failure is RFC-9457 `application/problem+json` whose `title`/`detail` name the
fix, and the engine surfaces that body verbatim. Nothing needs an `error_signals`
block — this API does not report failure with a `200`.

| Status | Means | What the body says |
|---|---|---|
| `401` | no key, or a bad one | where to get a key, and the keyless demo endpoints |
| `402` | credits exhausted | "Monthly credit allowance exhausted for this plan", plus the upgrade URL |
| `403` | `puntersedge_racing_closing_lines` on Free/Hobby | the archive needs Standard or higher |
| `422` | bad bookmaker key, market or competition | **free**, and lists the valid values |
| `429` | plan rate limit | carries `Retry-After` in seconds |

## The id model

Racing is **not** a `sport_key`. Passing `horse-racing` to the sports tools returns
`404`; horse, harness and greyhound racing live entirely under `puntersedge.racing`.

- `puntersedge_racing_events` (the card, priced or not) → `race_id` →
  `puntersedge_racing_next_to_go` / `puntersedge_racing_best_odds` (prices) →
  `puntersedge_racing_results` (settled) → `puntersedge_racing_closing_lines` (archive).
  The same `race_id` runs through all of them, including the demo tool.
- `puntersedge_racing_venues` → `venue_id` / `venue_site`, the join key against sources
  that spell venues differently. `venue_site` groups multi-track complexes (Sandown,
  Sandown Hillside, Sandown Lakeside and Sandown Park all carry site `sandown`).
- `puntersedge_sports` → `key` → `puntersedge_sport_odds` /
  `puntersedge_sport_best_odds`.

## Tools

### `puntersedge.demo` — no key, no signup

| Tool | Path | Capability |
|---|---|---|
| `puntersedge_demo_racing_next_to_go` | `/v1/demo/racing/next-to-go` | `racing.next_to_jump`, `sport.prices` |
| `puntersedge_demo_best_odds` | `/v1/demo/best-odds?sport=` | `sport.prices`, `sport.event_markets` |
| `puntersedge_demo_book_sport` | `/v1/demo/book-sport?book=&sport=` | `sport.prices` |

All three return an **envelope** (`{demo, note, signup_url, …}`), unlike their keyed
counterparts which return bare arrays. `puntersedge_demo_book_sport` takes its own
sandbox slug vocabulary (`sportsbet`, `afl`, `horse-racing`) — *not* the keyed API's
bookmaker keys or `sport_key`s; read `type` off the response before indexing `items`,
because it switches the item shape between sports and racing.

### `puntersedge.racing` — AU/NZ horse, harness and greyhound

| Tool | Path | Capability |
|---|---|---|
| `puntersedge_racing_next_to_go` | `/v1/racing/next-to-go` | `racing.next_to_jump`, `racing.race_card`, `sport.prices` |
| `puntersedge_racing_best_odds` | `/v1/racing/best-odds` | `racing.race_card`, `sport.prices` |
| `puntersedge_racing_events` | `/v1/racing/events` | `racing.meetings_by_date` |
| `puntersedge_racing_results` | `/v1/racing/results` | `racing.race_results` |
| `puntersedge_racing_closing_lines` | `/v1/racing/closing-lines` | `stats.closing_odds` |
| `puntersedge_racing_movers` | `/v1/racing/movers` | `sport.prices` |
| `puntersedge_racing_venues` | `/v1/racing/venues` | `ref.venues` |

`puntersedge_racing_next_to_go` and `puntersedge_racing_best_odds` declare
`never_cache` — they are live price feeds, and a re-read served from the engine's 60s
cache would compare a price against itself. The other five keep the cache.

### `puntersedge.sport` — pre-match team sports

| Tool | Path | Capability |
|---|---|---|
| `puntersedge_sports` | `/v1/sports` | `sport.competitions_list` |
| `puntersedge_sport_odds` | `/v1/sports/{sport_key}/odds` | `sport.event_markets`, `sport.prices` |
| `puntersedge_sport_best_odds` | `/v1/best-odds/{sport_key}` | `sport.prices`, `sport.event_markets` |

**Pre-match only — there is no in-play feed.** An event leaves `puntersedge_sport_odds`
the moment it starts, so nothing here updates during a match.

## Things that will bite you

- **`country=AU` alone silently drops most of an Australian card.** A race's country is
  unresolved until the meeting is confirmed — 58.8% of horse races in the vendor's
  measured window — so pair any `country` filter with `include_unresolved: true`.
- **Freshness is reported worst-first.** `data_age_seconds` on a race is the age of the
  *oldest* bookmaker quote in it. Before comparing two books, read each book's own
  `age_seconds`.
- **`best_tote` is not comparable to `best_win`.** A pre-race tote figure is an estimate
  that moves as the pool fills, and taking the maximum across books is upward-biased by
  construction. Greyhound pools swing hardest.
- **`books_quoting_win` and `books_quoting_place` are different sets** — a book can quote
  a win price and no place price on the same runner.
- **A `runners` entry in a result is not necessarily a starter.** Read its `status`, and
  take a scratching's deduction from `deductions`, never from `1/sp`.
- **`move_pct` is negative for a firming runner** in `puntersedge_racing_movers`, and
  `open_price` is the first price captured inside the 60-minute pre-race window, not a
  true market open — how close it is to 60 minutes varies sharply by book, so read each
  book's `open_secs_to_jump`.
- **`closing_only` defaults to true** on `puntersedge_racing_closing_lines`, because
  14.5% of archived series are not closing lines and mixing them in silently is how a
  CLV study goes wrong.

## Cross-provider comparison

- **`racing.race_card` / `racing.next_to_jump`** — `puntersedge_racing_next_to_go` and
  `puntersedge_racing_best_odds` against `sportsbet_racecard`, `tab_racing_race`,
  `pointsbet_racing_race`, `entain_racing_racecard`. The direct books give one book's
  full card; PuntersEdge gives every book's price on the same race in one call, already
  reduced to a best price and a market percentage — and works from outside Australia.
- **`racing.race_results`** — `puntersedge_racing_results` alongside
  `sportsbet_racing_resulted_events`, and the racecards that double as results
  (`tab_racing_race`, `pointsbet_racing_race`). It is the only one of the four carrying
  dividends, deductions and each book's *settled* price in the same row.
- **`stats.closing_odds`** — `puntersedge_racing_closing_lines` is the racing
  counterpart to `footballdatauk_season` (football closing odds) and
  `theoddsapi_historical_odds` (international, paid tier).
- **`ref.venues`** — `puntersedge_racing_venues` is the canonical AU/NZ track directory,
  which the per-book racecards do not publish.
- **`sport.event_markets` / `sport.prices`** — `puntersedge_sport_odds` and
  `puntersedge_sport_best_odds` line up against Pinnacle, Betfair, the direct AU books
  and `theoddsapi` for the same fixture; `canonical_event_id` joins books that spell the
  teams differently.
- **`sport.competitions_list`** — `puntersedge_sports`.

## Quick test (no key needed)

```bash
# Next three races, every demo tool is keyless
curl -s "https://api.puntersedge.online/v1/demo/racing/next-to-go" \
  | jq '.races[] | {venue, race_number, category, runners: (.runners | length)}'

# Best price per selection + arb flag
curl -s "https://api.puntersedge.online/v1/demo/best-odds" \
  | jq '.sport, (.events[] | {home_team, away_team, arb_exists})'

# One book, one sport
curl -s "https://api.puntersedge.online/v1/demo/book-sport?book=sportsbet&sport=afl" \
  | jq '{book, sport, type, items: (.items | length)}'
```

With a key, the same shape at full depth:

```bash
curl -s -H "X-API-Key: $PUNTERSEDGE_API_KEY" \
  "https://api.puntersedge.online/v1/racing/next-to-go?num_races=3&include_unresolved=true" \
  | jq '.[] | {venue, race_number, books: [.runners[0].bookmakers[].key]}'
```
