# PointsBet (Australia) API Documentation

Unofficial reference for the anonymous JSON endpoints behind **pointsbet.com.au**.
Every endpoint, parameter and response shape below was verified against live
traffic (probed 2026-06-04). Fields are reproduced from the wire — nothing that
was not observed is invented.

> **No auth, no API key.** All endpoints are `GET` and return `application/json`.
> Many feeds return a **top-level JSON array** rather than an object (noted
> per-endpoint). In the MCP server those payloads arrive in the tool result's
> text content block, since MCP structured output is object-typed.

## Hosts

| Host | Role |
|---|---|
| `api.au.pointsbet.com` | The sportsbook API — sports + racing data, markets, prices, promotions. |
| `pointsbet.com.au` | Static CMS / navigation assets under `/assets/content/**` and `/_manifest/**`. |

Two surfaces only. (A third host, `api-global.pointsbet.com/api/v2/bettingstats/…`,
exists but keys events by an opaque `PB…` id whose mapping isn't exposed on the
public feeds, so it is intentionally **not** modelled.)

## Conventions

- **Event keys** are numeric strings, e.g. `"2754627"`. They appear as `key` in
  every events feed and are the `{eventKey}` for `pointsbet_event`.
- **Competition keys** are numeric, e.g. `7523` (AFL), `7176` (NBA). Find them in
  `pointsbet_sports_list` or `pointsbet_sport_competitions`.
- **Racing ids** — `meetingId` and `raceId` are numeric strings. Resolve them from
  `pointsbet_racing_meetings` (a date window) or `pointsbet_racing_featured`.
- **Sport slugs** are kebab-case, e.g. `aussie-rules`, `basketball`, `tennis`,
  `e-sports`, `motor-sports`.
- **Times** are ISO-8601 UTC (`2026-06-04T09:30:00Z`).

---

## Sports — `api.au.pointsbet.com` (group `pointsbet.sports`)

| Tool | Path | Capabilities | Notes |
|---|---|---|---|
| `pointsbet_sports_inplay` | `/api/v2/sports/inplay` | `sport.in_play` | Sports with a live event count. |
| `pointsbet_inplay_streaming` | `/api/v2/sports/sports-inplay-streaming` | `sport.in_play`, `sport.live_video` | In-play events carrying a video stream. |
| `pointsbet_sports_list` | `/api/v2/sports/list/{date}` | `sport.competitions_list` | Whole sports + competitions catalogue. `{date}` is a `ddMMMyyyy` token (e.g. `02May2018`); the feed returns the current catalogue regardless of value. |
| `pointsbet_sport_competitions` | `/api/v2/sports/{sportKey}/competitions` | `sport.competitions_list` | Competitions for one sport, bucketed by locale (Featured / country). |
| `pointsbet_sport_featured_events` | `/api/v2/sports/{sportKey}/events/all-featured` | — | Featured events for one sport. |
| `pointsbet_competition_events` | `/api/mes/v3/events/featured/competition/{competitionKey}` | `sport.competition_screen` | Paged events for one competition; follow `nextPage`. |
| `pointsbet_event` | `/api/mes/v3/events/{eventKey}` | `sport.event_markets`, `sport.match_detail` | **Full event book**: `fixedOddsMarkets`, `featuredMarkets`, `prePricedSgm`, team stats, insights. |
| `pointsbet_event_search` | `/api/v2/sports/search` | — | Search events by `competitionKey` / `eventClassIds`; optional historic H2H stats. |
| `pointsbet_events_nextup` | `/api/v2/events/nextup` | — | Next-up events across all codes by start time. |
| `pointsbet_preprice_multis` | `/api/mes/v3/prepricedmulti/fivefor25s` | `sport.same_game_multi` | Pre-priced "5 for $25" multi suggestions. Top-level array. |

### Discovery flow (sports)

```
pointsbet_sports_list                      → competitionKey (e.g. 7523 = AFL)
  └ or pointsbet_sport_competitions(sportKey="aussie-rules")
pointsbet_competition_events(competitionKey=7523)   → event key (e.g. 2754627)
pointsbet_event(eventKey=2754627)          → every market + selection + price
```

---

## Racing — `api.au.pointsbet.com` (group `pointsbet.racing`)

| Tool | Path | Capabilities | Notes |
|---|---|---|---|
| `pointsbet_racing_meetings` | `/api/racing/v4/meetings` | `racing.meetings_by_date` | All meetings for a `startDate`/`endDate` window. Top-level array of date groups. |
| `pointsbet_racing_featured` | `/api/racing/v4/races/featured` | — | Featured races with a top-runner preview. Top-level array. |
| `pointsbet_racing_meeting` | `/api/racing/v3/meetings/{meetingId}` | — | One meeting: venue, conditions, races. |
| `pointsbet_racing_race` | `/api/racing/v3/races/{raceId}` | `racing.race_card`, `racing.race_results` | Full racecard; the `results` block (winners + dividends) populates once the race is run. |
| `pointsbet_racing_races` | `/api/racing/v3/races?raceIds=…` | `racing.race_card` | Batch racecards. Top-level array. |
| `pointsbet_racing_srm` | `/api/srm/v3/market/race/{raceId}` | `racing.same_race_multi` | SRM market + availability for one race. |
| `pointsbet_racing_futures` | `/api/v2/sports/racing-futures` | `racing.futures` | Cup/Carnival outrights and long-running racing markets. |
| `pointsbet_racing_hourly_quaddie` | `/api/racing/hourlyquaddie/v1` | — | Quaddie races grouped by hour. Top-level array. |
| `pointsbet_racing_tips` | `/api/racing-tips/v1/{racingType}/{country}/today` | — | Tipster selections by venue. Top-level array. |
| `pointsbet_racing_insights` | `/api/racing-tips/v1/insights/{raceId}` | — | Editorial form insights for one race (`204 No Content` before published). |
| `pointsbet_racing_form` | `/api/v2/racing-form/{country}/{venue}/{meetingNumber}/{date}/{raceNumber}` | — | Detailed form guide. `{date}` is `YYYY-MM-DD-am`/`-pm`; `{raceNumber}` is zero-padded (`01`). |

### Discovery flow (racing)

```
pointsbet_racing_meetings(startDate, endDate)   → meetingId + raceId
pointsbet_racing_race(raceId)                   → runners, prices, (results once run)
pointsbet_racing_srm(raceId)                    → Same Race Multi market
```

---

## Content — `pointsbet.com.au` (group `pointsbet.content`)

| Tool | Path / Operation | Capabilities | Notes |
|---|---|---|---|
| `pointsbet_promotions` | `api.au` `/api/gpp/v3/client/promotions` | `content.promo` | Live promotions for a `displayTarget` (e.g. `carousel`). Top-level array. |
| `pointsbet_promo_code` | `/assets/content/au/promo-codes/{code}.json` | `content.promo` | Sign-up splash (info text + hero image) for a promo code, e.g. `WELCOME`. |
| `pointsbet_content_call` | dispatcher over `pointsbet.com.au` static assets | — | One tool, many static JSON assets — see below. |

> **Not modelled:** the markdown assets (`OnlineHouseRules.md`, per-event
> `eventbettingpreviews/*.md`) — the client decodes JSON only; `quick-sgm/price`
> (a POST taking a bet-leg body); the SignalR/push websocket negotiation; and
> `api-global …/bettingstats/{PB-id}` (keyed by an opaque id with no public map).

`pointsbet_content_call` operations (browse `pointsbet://content/operations`):

| Operation | Asset |
|---|---|
| `league_menu` | `/assets/content/leagueMenu.json` — top-level league menu |
| `quick_links` | `/assets/content/au/quickLinks.json` — quick-link chips |
| `home_tiles` | `/assets/content/au/hometiles/tiles.json` — homepage tiles |
| `sidebar_events` | `/assets/content/au/sidebarmenu/sidebarevents.json` — sidebar featured events |
| `logo_mappings` | `/assets/content/logos/mappings_v2.json` — competition/team → logo mappings |
| `app_manifest` | `/_manifest/application.au.json` — AU app build manifest |
| `maintenance_kill` | `/assets/content/au/maintenance/kill.json` — maintenance banner |

---

## Cross-provider comparison

PointsBet shares capability tags with the other Australian books, so its tools are
directly comparable via `list_tools_by_capability`:

- `sport.event_markets` / `sport.match_detail` → `pointsbet_event` alongside
  `sportsbet_event_markets`, Entain's GraphQL event ops.
- `racing.race_card` → `pointsbet_racing_race` alongside `sportsbet_racecard`.
- `racing.meetings_by_date` → `pointsbet_racing_meetings` alongside
  `sportsbet_racing_allracing`.
- `racing.same_race_multi` → `pointsbet_racing_srm` alongside
  `sportsbet_racing_popular_srms`.

See [`examples/comparator-prompt.md`](../examples/comparator-prompt.md) for a
worked cross-book odds comparison.
