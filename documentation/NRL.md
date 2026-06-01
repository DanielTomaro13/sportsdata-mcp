# NRL API Documentation

Unofficial reference for the **Champion Data "Match Centre"** JSON feeds that power the official `nrl.com` match centre. A single host serves everything:

- **`mc.championdata.com`** — Champion Data's static-JSON CDN. The same feeds the nrl.com match centre reads in the browser. No authentication, no rate limit, no cache-buster params required.

> This document is generated from the packaged provider spec (`src/sportsdata_mcp/specs/nrl.yaml`) and the Champion Data match-centre surface as observed on 2026-06-01. Response shapes are reproduced from the spec's field maps (`response_hint`) — the same shapes the match centre consumes — and illustrated with the spec's example ids (`competitionId: 12999` = 2026 NRL Premiership, `matchId: 129990101`). Statistic codes are decoded via the `nrl://stats/definitions` dictionary.

---

## Table of Contents

- [Host & service](#host--service)
- [Authentication](#authentication)
- [Conventions](#conventions)
  - [The ID chain](#the-id-chain)
  - [Competitions](#competitions)
  - [Squads (teams)](#squads-teams)
  - [Match status](#match-status)
  - [Time format](#time-format)
  - [Statistic codes](#statistic-codes)
- [Endpoints](#endpoints)
  - [Competitions catalogue](#competitions-catalogue)
  - [Application settings](#application-settings)
  - [Fixture (one competition)](#fixture-one-competition)
  - [Match (per-player stats)](#match-per-player-stats)
- [Resources](#resources)
  - [Statistic definitions](#statistic-definitions)
- [Endpoint quick reference](#endpoint-quick-reference)

---

## Host & service

Everything lives under one host, exposed as the provider's single `base_url`:

```jsonc
{ "default": "https://mc.championdata.com" }
```

| Sub-path | Feed | Auth |
|---|---|---|
| `/data/competitions.json` | Global competition catalogue | ❌ none |
| `/nrl/settings/application_settings.json` | Match-centre app config | ❌ none |
| `/data/{competitionId}/fixture.json` | Fixture + results for one competition | ❌ none |
| `/data/{competitionId}/{matchId}.json` | Full per-player match file | ❌ none |
| `/global/settings/nrl_statistic_definitions.json` | Stat-code dictionary | ❌ none |

Champion Data runs the same match-centre platform for several sports/leagues; the `competitions.json` catalogue is global, so you filter it down to NRL by name/season client-side.

---

## Authentication

**None.** Anonymous `GET` works on every feed.

Browser traffic carries `uuid` and `_=<ms>` query parameters — these are **cache-busters only**. The feeds resolve fine without them, so the spec omits them. A minimal header set (`User-Agent`, `Accept: application/json, text/plain, */*`) is sent; like several CDNs, the JSON may arrive labelled `text/plain`, so parse the body regardless of the declared content-type.

---

## Conventions

### The ID chain

Every per-match query is reached through a two-step id resolution:

```
nrl_competitions / nrl_application_settings  →  competitionId   (e.g. 12999)
nrl_fixture(competitionId)                   →  matchId         (e.g. 129990101)
nrl_match(competitionId, matchId)            →  full per-player / per-period stats
```

The `matchId` embeds the competition + round + match sequence: `129990101` = competition `12999`, round `01`, match `01`.

### Competitions

`competitionId` examples (resolve the live list from `nrl_competitions`):

| `competitionId` | Competition |
|---|---|
| `12999` | 2026 NRL Premiership |
| `13009` | 2026 State of Origin |

Each competition entry carries its `season`, `rounds`, and period config (`regulationPeriods`, `regulationPeriodLength` — 2 × 40-minute halves for rugby league).

### Squads (teams)

Teams are **squads**. A fixture entry names both: `homeSquadId` / `homeSquadName` and `awaySquadId` / `awaySquadName`. Squad ids are stable across a season and reused in the match file's `teamInfo`.

### Match status

The `matchStatus` field on a fixture entry indicates whether a game is upcoming, in progress, or complete (e.g. `Pre Game` / `Playing` / `Full Time`). Pair it with `homeSquadScore` / `awaySquadScore` to distinguish a scheduled `0–0` from a genuine result.

### Time format

Each fixture match carries two clocks:

| Field | Meaning |
|---|---|
| `utcStartTime` | Kickoff in UTC (ISO 8601) |
| `localStartTime` | Kickoff in venue-local time |

### Statistic codes

The match file (`nrl_match`) reports per-player stats under terse codes (`runMetres`, `lineBreaks`, `tryAssists`, `offloads`, `handlingErrors`, `metresGained`, …). Decode every code — including compound/calculated formulas — via the [`nrl://stats/definitions`](#statistic-definitions) dictionary.

---

## Endpoints

All four endpoints are in the `nrl.public.core` group, anonymous, on the single host.

### Competitions catalogue

```
GET https://mc.championdata.com/data/competitions.json
```

The global Champion Data competition catalogue. Returns every competition id (NRL, State of Origin, plus other Champion Data sports) with its season and round count. Find the NRL `competitionId` here.

```jsonc
{
  "competitionDetails": {
    "competition": [
      {
        "id": 12999,
        "name": "NRL Premiership",
        "season": 2026,
        "rounds": 27,
        "regulationPeriods": 2,
        "regulationPeriodLength": 40
      }
    ]
  }
}
```

> The list spans all Champion Data sports — filter by `name` / `season` for NRL.

### Application settings

```
GET https://mc.championdata.com/nrl/settings/application_settings.json
```

The NRL match-centre application config: the current-season competition list, stat-grid column layouts, UI components and team/competition image paths. Handy for discovering the **active** `competitionId`s and which statistics the official site surfaces.

```jsonc
{
  "applicationInfo": { "...": "..." },
  "userInfo":        { "...": "..." },
  "competitionList": [ { "id": 12999, "name": "NRL Premiership", "season": 2026 } ],
  "components":      [ "..." ],
  "dataGrids":       [ { "name": "...", "columns": [ "..." ] } ],   // stat-grid layouts
  "shellGroups":     [ "..." ]
}
```

### Fixture (one competition)

```
GET https://mc.championdata.com/data/{competitionId}/fixture.json
```

| Param | Type | Description |
|---|---|---|
| `competitionId` | integer (required) | Champion Data competition id, e.g. `12999`. From `nrl_competitions` / `nrl_application_settings`. |

Full fixture + results for one competition: one entry per match with round, status, kickoff times, home/away squad ids/names/scores and venue. Use it to list a round's games and to resolve the `matchId` for `nrl_match`.

```jsonc
{
  "fixture": {
    "match": [
      {
        "matchId": 129990101,
        "roundNumber": 1,
        "matchStatus": "Full Time",
        "utcStartTime": "2026-03-05T08:00:00Z",
        "localStartTime": "2026-03-05T19:00:00",
        "homeSquadId": 500,  "homeSquadName": "Knights",  "homeSquadScore": 24,
        "awaySquadId": 501,  "awaySquadName": "Cowboys",  "awaySquadScore": 18,
        "venueId": 42, "venueName": "McDonald Jones Stadium"
      }
    ]
  }
}
```

### Match (per-player stats)

```
GET https://mc.championdata.com/data/{competitionId}/{matchId}.json
```

| Param | Type | Description |
|---|---|---|
| `competitionId` | integer (required) | Champion Data competition id, e.g. `12999`. |
| `matchId` | integer (required) | Match id from `nrl_fixture`, e.g. `129990101`. |

The full match file — **the per-player, per-match stat source.** Per-player match statistics (tries, tackles, runMetres, lineBreaks, tryAssists, offloads, handlingErrors, metresGained, …), per-period player stats, team/player rosters, period durations, sin bins and on-report records.

```jsonc
{
  "matchStats": {
    "matchInfo":   { "matchId": 129990101, "...": "..." },
    "teamInfo":    { "team":   [ { "squadId": 500, "squadName": "Knights" }, { "...": "..." } ] },
    "playerInfo":  { "player": [ { "playerId": 9001, "firstname": "...", "surname": "..." } ] },
    "periodInfo":  { "qtr":    [ { "period": 1, "duration": "..." } ] },
    "playerStats": { "player": [ { "playerId": 9001, "tries": 1, "tackles": 32, "runMetres": 118, "lineBreaks": 2, "tryAssists": 1, "offloads": 3, "handlingErrors": 1, "metresGained": 130 } ] },
    "playerPeriodStats": { "player": [ { "playerId": 9001, "period": 1, "...": "..." } ] },
    "sinBins":     { "binned":   [ "..." ] },
    "reports":     { "onReport": [ "..." ] },
    "created":     "2026-03-05T10:00:00Z"
  },
  "jobId": "..."
}
```

> Stat keys under `playerStats` / `playerPeriodStats` are decoded by [`nrl://stats/definitions`](#statistic-definitions).

---

## Resources

### Statistic definitions

```
GET https://mc.championdata.com/global/settings/nrl_statistic_definitions.json
```

Exposed as the MCP resource **`nrl://stats/definitions`**. A dictionary of every NRL statistic code: `dataName`, `code`, `shortName`, `longName`, `dataType`, and compound/calculated formulas. Use it to interpret the stat fields returned by `nrl_match`.

```jsonc
{
  "definitions": [
    { "dataName": "runMetres", "code": "...", "shortName": "Run M", "longName": "Run Metres", "dataType": "integer" },
    { "dataName": "tackleEfficiency", "shortName": "Tkl %", "longName": "Tackle Efficiency", "dataType": "percentage", "formula": "tacklesMade / (tacklesMade + missedTackles)" }
  ]
}
```

This is a small static lookup table, fetched lazily on first read and reused for the session.

---

## Endpoint quick reference

| Tool / resource | Group | Path |
|---|---|---|
| `nrl_competitions` | `nrl.public.core` | `/data/competitions.json` |
| `nrl_application_settings` | `nrl.public.core` | `/nrl/settings/application_settings.json` |
| `nrl_fixture` | `nrl.public.core` | `/data/{competitionId}/fixture.json` |
| `nrl_match` | `nrl.public.core` | `/data/{competitionId}/{matchId}.json` |
| `nrl://stats/definitions` | resource | `/global/settings/nrl_statistic_definitions.json` |

**Discovery flow:** `nrl_competitions` (or `nrl_application_settings`) → pick a `competitionId` (e.g. `12999`) → `nrl_fixture(competitionId)` → pick a `matchId` → `nrl_match(competitionId, matchId)` for full per-player stat lines → decode codes via `nrl://stats/definitions`.
