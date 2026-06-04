# FanDuel (US) API Documentation

Unofficial reference for the anonymous JSON/GraphQL endpoints behind FanDuel
Racing (TVG) **and** the FanDuel Sportsbook. Verified against live traffic
(probed 2026-06-03/04). **US data** (US tracks + US sports, region NJ).

> **No auth, no API key.** Two surfaces under one provider:
> - **Racing** (`fanduel.racing`) — a **full-query GraphQL** API (POSTs the whole
>   query text, not a persisted hash).
> - **Sportsbook** (`fanduel.sportsbook`) — REST keyed by the static *public* `_ak`
>   web key, region NJ.
>
> The two halves require **different `Origin` headers** (`racing.fanduel.com`
> rejects the sportsbook origin and vice-versa). The provider default carries the
> racing origin; the sportsbook dispatcher overrides `Origin` + `x-sportsbook-region`
> via its own headers.

## Hosts

| Host | Role |
|---|---|
| `api.racing.fanduel.com/cosmo/v1/graphql` | The racing GraphQL API (featured/today races, tracks, pools, talent picks). |
| `service.racing.fanduel.com` | Racing REST aux: site messages, homepage quick-links. |
| `api.sportsbook.fanduel.com` | The sportsbook REST API (event pages, in-play, promos, configs). |
| `fdx-api.sportsbook.fanduel.com` | Live event scores. |

## The `graphql_query` dispatcher

FanDuel Racing is the first **full-query** GraphQL provider in this repo. Unlike
the persisted-query providers (Entain, Sportsbet — which send a sha256 hash), it
POSTs `{operationName, query, variables}` with the literal query text. That text
lives server-side in the spec's `graphql.operations` block, so the model only
supplies an **operation name + variables** (discovered via
`fanduel://racing/operations`).

Every operation carries **`default_variables`** — the boilerplate
`brand=FDR`, `product=TVG5`, `device=Desktop`, `wagerProfile=FDR-Generic`,
filters and sorts — merged *under* whatever the caller passes. So most calls need
**no variables at all**; override only what varies (e.g. `{results: 12}` or
`{trackCode: "GP", raceNumber: "5"}`).

> **Queries are sent verbatim.** FanDuel validates that every declared variable is
> used; a trimmed query that orphans a variable (e.g. dropping the
> `@include(if: $isLoggedIn)` fields) is rejected with `variable … never used`.

### `fanduel_racing_call` operations

| Operation | Returns | Capability |
|---|---|---|
| `getRaceDate` | The current race date (no variables — the simplest probe). | — |
| `getTracks` | All tracks today (id, name, code, race count, greyhound flag, location). | `racing.meetings_by_date` |
| `getTodayRaces` | Every race today across tracks (status, type, video, distance, post time). | `racing.next_to_jump` |
| `getFeaturedRaces` | Top/featured races **with `bettingInterests` → `currentOdds`** (runners, silks, trainer/jockey). The race-card surface. | `racing.race_card` |
| `getTopPools` | Carry-over / jackpot pools by wager type. | — |
| `getGraphTalentPicks` | Expert talent picks (filterable by `trackCode` + `raceNumber`). | — |

The dispatcher's union capabilities are `racing.next_to_jump`,
`racing.meetings_by_date`, `racing.race_card`.

### Discovery flow

```
fanduel_racing_call(getTracks)                          → trackCode (e.g. "GP")
fanduel_racing_call(getTodayRaces)                       → races by post time
fanduel_racing_call(getFeaturedRaces, {results: 12})     → featured races + currentOdds
fanduel_racing_call(getGraphTalentPicks, {trackCode:"GP", raceNumber:"5"})  → picks
```

## REST aux — `service.racing.fanduel.com` (group `fanduel.racing`)

| Tool | Path | Notes |
|---|---|---|
| `fanduel_racing_messages` | `/capi/v1/messages/namespace` | Site copy / disclaimers for a namespace. |
| `fanduel_racing_quicklinks` | `/pes/v1/homepage/quicklinks` | Homepage quick-link tiles. |

## Sportsbook — `api.sportsbook.fanduel.com` (group `fanduel.sportsbook`)

`fanduel_sb_call` is a templated-REST dispatcher that carries the static public
`_ak` web key + the sportsbook `Origin`/`x-sportsbook-region: NJ` headers, so the
caller supplies only the variable query params. Browse `fanduel://sportsbook/operations`.

| Operation | Path | Notes |
|---|---|---|
| `application_context` | `/sbapi/application-context` | Nav scaffolding — pick blocks via `dataEntries` (POPULAR_BETTING, QUICK_LINKS, AZ_BETTING, EVENT_TYPES, …). |
| `content_page` | `/sbapi/content-managed-page` | A managed sport/landing page (events + markets) by `customPageId` (e.g. `mlb`, `nfl`, `nba`). |
| `event_page` | `/sbapi/event-page` | Full event page: tabs of markets + selections for one `eventId`. |
| `inplay_counter` | `/sbapi/in-play/counter` | Count of events currently in-play. |
| `inplay_livedata` | `/ips/inplayservice/v1.0/livedata` | Live scores/media for comma-separated `eventIds`. |
| `promotions` | `/promos/api/v2/promotions` | Sportsbook promotions for a `context`. |
| `season_data` | `/ips/seasondata` | Season metadata / rankings. |
| `static_config` | `/config/static/NJ.json` | Static app config (banners, feature blocks). |

Dispatcher capabilities: `sport.event_markets`, `sport.match_detail`,
`sport.competition_screen`, `sport.in_play`, `content.promo`.

| Discrete tool | Path | Capability |
|---|---|---|
| `fanduel_sb_live_score` | `fdx-api` `/api/v1/live/event/{eventId}/score/NJ` | `sport.match_score` |

### Discovery flow (sportsbook)

```
fanduel_sb_call(content_page, {customPageId: "mlb"})   → eventId (attachments.events)
fanduel_sb_call(event_page,   {eventId})                → every market + selection
fanduel_sb_live_score(eventId)                          → live score
```

## Cross-provider comparison

FanDuel Racing reuses the racing capability tags, so it composes with the other
books via `list_tools_by_capability` (e.g. `racing.race_card` → `fanduel_racing_call`
alongside `tab_racing_race`, `sportsbet_racecard`, `pointsbet_racing_race`). Note
FanDuel is **US** racing, so a like-for-like odds comparison applies when other US
sources are added; the tag still makes it discoverable.

## Not modelled

- `smp.nj.sportsbook.fanduel.com/.../getMarketPrices` — a POST endpoint that wants
  a body of market ids; the markets + prices already come from `event_page`.
- `boapi.sportsbook.fanduel.com/popular/events/{id}` — overlaps `event_page`.
- Storyblok CMS (`api.storyblok.com`) — third-party CMS, not a FanDuel host.
- Account / wagering surfaces — out of scope for a read-only data provider.
