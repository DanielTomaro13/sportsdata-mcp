# Dabble — Reverse-Engineered API Documentation

Reference for the **Dabble** (dabble.com.au) read surface as modelled by the
packaged provider spec (`src/sportsdata_mcp/specs/dabble.yaml`). Dabble is an
Australian social-betting app; this models the **native iOS app's backend**,
read directly.

> **Unofficial / undocumented.** Re-probed live **2026-06-25**. Read-only odds
> data — no bet placement (the repo's no-money invariant).

## How it works (the scrape)

`api.dabble.com.au` is the iOS app's API and is **Cloudflare-fronted**. The trick
to reaching it is to **pose as the app**: send the app's header bundle and the
public feeds return JSON **anonymously** (no Bearer token) from an Australian IP.

| Header | Value (shipped as a default) |
|---|---|
| `user-agent` | `Dabble/1000041710 CFNetwork/3826.600.41.2.1 Darwin/24.6.0` |
| `x-device-id` | `00000000-0000-0000-0000-000000000000` |
| `x-app-version` | `4.17.10+019ededb` |
| `accept-language` | `en-AU,en;q=0.9` |

The spec bakes all of these into `provider.default_headers`, so it works out of
the box with the engine's httpx.

### ⚠️ Geo + bot gating

Like the other AU books, Dabble is **AU-only**: it serves from an Australian
connection but **403s / challenges from non-AU or datacenter IPs** (so its
contract test skips in CI). And because it's Cloudflare-fronted, if Cloudflare
ever starts **JA3-fingerprinting** the TLS, the engine's plain httpx may be
blocked — the app's own client uses a Safari-iOS TLS impersonation
(`curl_cffi impersonate="safari_ios"`). At probe time plain httpx reached every
feed from an AU IP. (An optional `Bearer` token unlocks account features, which
are out of scope.)

## Shape

One **fixtures feed per competition** embeds the markets, prices and selections;
a per-fixture **details** endpoint returns the *full* book. Markets join to
selections and prices by `marketId` / `selectionId`:

```
dabble_competition_fixtures(competitionId)  →  fixtures (+ embedded markets/prices/selections)
                                            →  fixture id
dabble_fixture_details(fixtureId)           →  the FULL book (hundreds of markets + Pick'em)
```

Decimal odds live on each `prices[].price`. Dabble also runs a **Pick'em**
(multiplier/parlay) product alongside its fixed-odds book — those surface as
`playerProps[]` in the details payload (flat picks, not traditional fixed odds).

## Tools — group `dabble.sport`

| Tool | Path | Capability |
|---|---|---|
| `dabble_competition_fixtures` | `/frontend-api/competitions/{competitionId}/sport-fixtures?includeInPlay=&exclude[]=` | `sport.fixtures_by_date`, `sport.event_markets`, `sport.prices` |
| `dabble_fixture_details` | `/frontend-api/sport-fixtures/details/{fixtureId}` | `sport.event_markets`, `sport.prices`, `sport.same_game_multi` |

- `exclude` (mapped to the wire param `exclude[]`) slims the fixtures payload —
  pass `markets`, `prices` or `selections` to drop that block (default `none` =
  include all).
- `dabble_fixture_details` is **large** (~1 MB+ for a major match — 400+ markets,
  thousands of prices); fetch one fixture at a time.

## Competition ids

Competition ids are opaque UUIDs. The two verified here:

| Competition | id |
|---|---|
| AFL Matches | `ad4c78ec-e39d-45ee-8cec-ff5d485a3205` |
| NRL | `c709772d-d5d0-4252-af89-be8a163706dc` |

Discover others from the app's network traffic. The `/competitions` catalogue
*does* exist but is a **~38 MB / ~140,000-row dump** (all competitions ever), so
it is **deliberately not modelled** — filter it offline if you need more ids.

## Not modelled

- **`/competitions`** — the 38 MB catalogue firehose (no server-side filter).
- **Account / wagering** (bet placement, balances, the authenticated `Bearer`
  surfaces) — out of scope for a read-only data provider.
- The Pick'em **placement** flow — only the `playerProps` *data* is read (in
  `dabble_fixture_details`).

## Cross-provider comparison

Tagged with the shared bookmaker capabilities, Dabble lines up against the other
books via `list_tools_by_capability`:

- **`sport.event_markets`** / **`sport.prices`** → `dabble_fixture_details` next
  to `sportsbet_event_markets`, `pointsbet_event`, `tab_match_markets`,
  `betfair_market_prices`, Pinnacle — cross-book odds comparison on the same AFL
  / NRL fixture.
- **`sport.fixtures_by_date`** → `dabble_competition_fixtures` alongside the
  league data feeds (NRL Champion Data, AFL) to line up odds with the official
  fixture.
- **`sport.same_game_multi`** → Dabble's `marketGroups` next to Sportsbet/TAB SGMs.
