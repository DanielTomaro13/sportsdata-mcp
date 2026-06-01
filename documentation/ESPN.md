# ESPN API Documentation

Unofficial reference for the public JSON feeds that power `espn.com` and the ESPN apps. There is **no API key and no auth** — every host below answers anonymous `GET` requests. Four hosts make up the surface:

- **`site.api.espn.com`** — the **site API**: scoreboards, team catalogues, standings, league news, game summaries, athlete game-logs/bios, rankings. Hosts both `/apis/site/v2/...` and `/apis/site/v3/...` (plus the standalone `/apis/v2/...standings`).
- **`sports.core.api.espn.com`** — the **core API**: the canonical, deeply `$ref`-linked data model. Athletes + statistics + career logs, per-event odds / win-probabilities / plays / situation / broadcasts / predictor, per-competitor line-scores, season teams/coaches/draft/futures, venues, leaders, franchises, coaches. **Path uses `leagues/{league}` (plural).**
- **`site.web.api.espn.com`** — the **web API**: site-wide search and the `common/v3` athlete overview/stats/gamelog/splits views that back player-profile pages.
- **`cdn.espn.com`** — the **CDN core** live feed: lightly-cached scoreboard/game/boxscore/playbyplay JSON. Every request needs `?xhr=1`.

> This document is generated from the packaged provider spec (`src/sportsdata_mcp/specs/espn.yaml`) and ESPN's public surface as observed on 2026-06-01. The dispatcher operation catalogues (names, path params, query params, defaults) are the spec's source of truth and are also exposed live at the `espn://site/operations`, `espn://core/operations`, `espn://web/operations` and `espn://cdn/operations` MCP resources.

---

## Table of Contents

- [Hosts & services](#hosts--services)
- [Authentication](#authentication)
- [Conventions](#conventions)
  - [The `{sport}/{league}` convention](#the-sportleague-convention)
  - [Sport & league slugs](#sport--league-slugs)
  - [Identifiers](#identifiers)
  - [Common query parameters](#common-query-parameters)
  - [Response shapes](#response-shapes)
  - [Rate limiting & errors](#rate-limiting--errors)
- [espn.scores: discrete endpoints](#espnscores-discrete-endpoints)
  - [Scoreboard](#scoreboard)
  - [Teams](#teams)
  - [Standings](#standings)
  - [Game summary](#game-summary)
  - [News](#news)
- [espn.site: the site dispatcher](#espnsite-the-site-dispatcher)
- [espn.core: the core dispatcher](#espncore-the-core-dispatcher)
- [espn.web: the web dispatcher](#espnweb-the-web-dispatcher)
- [espn.cdn: the CDN dispatcher](#espncdn-the-cdn-dispatcher)
- [Endpoint quick reference](#endpoint-quick-reference)

---

## Hosts & services

| Host | Service | Auth | In spec as |
|---|---|---|---|
| `site.api.espn.com` | Scoreboards, teams, standings, news, summaries, rosters, athlete logs | ❌ none | `base: site` |
| `sports.core.api.espn.com` | Canonical `$ref`-linked core model (odds, probabilities, plays, venues, drafts…) | ❌ none | `base: core` |
| `site.web.api.espn.com` | Site-wide search + `common/v3` athlete views | ❌ none | `base: web` |
| `cdn.espn.com` | CDN live core feed (needs `?xhr=1`) | ❌ none | `base: cdn` |

The four hosts map to the provider's four `base_urls`:

```jsonc
{
  "site": "https://site.api.espn.com",
  "core": "https://sports.core.api.espn.com",
  "web":  "https://site.web.api.espn.com",
  "cdn":  "https://cdn.espn.com"
}
```

---

## Authentication

**None.** No bearer token, no API key, no header bundle. Anonymous `GET` works everywhere. ESPN occasionally labels JSON responses `text/plain`; a strict client that keys off content-type will choke, so parse the body regardless of the declared type.

ESPN's hosts can throttle aggressive bursts (transient `429`/`5xx`). The spec ships a modest rate limit and transient-error retry:

```jsonc
{
  "rate_limit_rps":          5,
  "request_timeout_seconds": 30,
  "burst":                   5,
  "retry_statuses":          [429, 500, 502, 503, 504],
  "max_retries":             3,
  "retry_backoff_seconds":   0.5
}
```

All overridable per-operator via `providers.espn.*` in config.

---

## Conventions

### The `{sport}/{league}` convention

Almost every ESPN URL is shaped `.../sports/{sport}/{league}/{resource}`. That single shape is what lets this provider cover **every** ESPN league with a handful of tools instead of one tool per league: the discrete endpoints and the dispatcher operations all take `sport` and `league` as parameters.

- **Site API:** `/apis/site/v2/sports/{sport}/{league}/{resource}`
- **Core API:** `/v2/sports/{sport}/leagues/{league}/{resource}` ← note **`leagues`** (plural)
- **Web API:** `/apis/common/v3/sports/{sport}/{league}/athletes/{id}/{view}`
- **CDN:** `/core/{leagueSlug}/{resource}?xhr=1` ← the path slug is the league (`nfl`), except soccer which is `/core/soccer/...&league=eng.1`

### Sport & league slugs

A non-exhaustive map (anything ESPN covers works):

| `sport` | `league` slugs |
|---|---|
| `football` | `nfl`, `college-football`, `cfl`, `ufl`, `xfl` |
| `basketball` | `nba`, `wnba`, `mens-college-basketball`, `womens-college-basketball`, `nbl` |
| `baseball` | `mlb`, `college-baseball`, `world-baseball-classic` |
| `hockey` | `nhl`, `mens-college-hockey`, `womens-college-hockey` |
| `soccer` | `eng.1`, `esp.1`, `ger.1`, `ita.1`, `fra.1`, `usa.1`, `uefa.champions`, `fifa.world`, `usa.nwsl`, … |
| `golf` | `pga`, `lpga`, `liv` |
| `racing` | `f1`, `nascar-premier` |
| `tennis` | `atp`, `wta` |
| `mma` | `ufc` |

For **soccer** the league is a dotted competition code (`eng.1` = Premier League, `esp.1` = La Liga). On the CDN feed, soccer uses `sport=soccer` in the path plus a `league=eng.1` query.

### Identifiers

| ID | Form | Where it comes from |
|---|---|---|
| `event` / `eventId` | numeric string, e.g. `401547439` | `espn_scoreboard` → `events[].id` |
| `competitionId` | usually equal to the `eventId` | the event's `competitions[].id` |
| `competitorId` | numeric team id within a competition | the competition's `competitors[].id` |
| `teamId` | numeric string, e.g. `12` | `espn_teams`, `espn_core_call(teams)` |
| `athleteId` | numeric string, e.g. `1966` (LeBron) | `espn_core_call(athletes)`, `espn_web_call(search)` |
| `year` | 4-digit season, e.g. `2025` | n/a (literal) |

### Common query parameters

| Param | Meaning |
|---|---|
| `dates` | `YYYYMMDD`, or a range `YYYYMMDD-YYYYMMDD`. Omit for "today". |
| `week` | Week number (NFL / college football). |
| `seasontype` | `1` pre · `2` regular · `3` post · `4` off. |
| `season` | Season year, e.g. `2025`. |
| `limit` / `page` | Paging on the core `$ref` lists. |
| `group` | Conference/division group id (for grouped standings). |
| `xhr` | CDN only: `1` (supplied automatically by the CDN dispatcher). |

### Response shapes

Three distinct envelopes, by host:

1. **Site / web API** — fully-materialised nested JSON. Scoreboards: `{leagues:[...], events:[{id, name, status, competitions:[{competitors:[{team, score}]}]}]}`. Standings: `{name, children:[{standings:{entries:[{team, stats:[{name, value}]}]}}]}` where `children` are the conferences/divisions.

2. **Core API** — a lazy, `$ref`-linked model. List endpoints return a **paged reference envelope**; follow each `$ref` for the full object:

   ```jsonc
   {
     "count": 30, "pageIndex": 1, "pageSize": 25, "pageCount": 2,
     "items": [ { "$ref": "http://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/teams/1?lang=en" } ]
   }
   ```

3. **CDN core** — a single large object with the live data nested under `content` (e.g. `content.sbData`, `content.gamepackage`), alongside `meta`, `news`, `analytics`.

### Rate limiting & errors

| Symptom | Cause | Handling |
|---|---|---|
| HTTP 429 / 5xx | Burst throttle | Spec retries with backoff; lower `rate_limit_rps` if frequent |
| JSON as `text/plain` | ESPN content-type quirk | Client parses the body regardless |
| Empty `events` | Off-day / off-season scoreboard | Not an error — the envelope is still present |
| `{ "$ref": … }` only | You hit a core list; the data is one hop away | Follow the `$ref` |

A malformed dispatcher `operation` is a recoverable error pointing back at that dispatcher's catalogue resource.

---

## espn.scores: discrete endpoints

Five convenience tools over the site API. All take `sport` + `league` slugs.

### Scoreboard

```
GET https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard
```

| Param | Type | Description |
|---|---|---|
| `sport` | string (required) | e.g. `football`, `basketball`, `soccer` |
| `league` | string (required) | e.g. `nfl`, `nba`, `eng.1` |
| `dates` | string | `YYYYMMDD` (or range); omit for today |
| `week` | integer | Week number (NFL/college football) |
| `seasontype` | integer | `1` pre · `2` regular · `3` post · `4` off |

The fastest way to get the `event` ids that `espn_game_summary` / `espn_core_call(event_*)` need. The envelope is always present even off-season — `events` is simply `[]`.

```jsonc
{
  "leagues": [ { "id": "28", "name": "National Football League", "abbreviation": "NFL" } ],
  "events": [
    { "id": "401547439", "name": "Bears at Packers", "date": "2025-11-02T18:00Z",
      "status": { "type": { "state": "post", "completed": true } },
      "competitions": [ { "id": "401547439", "competitors": [ { "homeAway": "home", "team": { "abbreviation": "GB" }, "score": "27" } ] } ] }
  ]
}
```

### Teams

```
GET https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams
```

| Param | Type | Description |
|---|---|---|
| `sport` / `league` | string (required) | e.g. `football` / `nfl` |

Team catalogue: id, name, abbreviation, colours, logos. Feed the ids into `espn_site_call` (roster/schedule/…).

```jsonc
{ "sports": [ { "leagues": [ { "teams": [ { "team": { "id": "12", "displayName": "Kansas City Chiefs", "abbreviation": "KC" } } ] } ] } ] }
```

### Standings

```
GET https://site.api.espn.com/apis/v2/sports/{sport}/{league}/standings
```

> Note the `/apis/v2/...` prefix (not `/apis/site/v2/...`) — the `site/v2` standings path returns only a link stub for pro leagues, so the spec uses the fuller `/apis/v2/` variant.

| Param | Type | Description |
|---|---|---|
| `sport` / `league` | string (required) | e.g. `basketball` / `nba` |
| `season` | integer | Season year; omit for current |
| `seasontype` | integer | `1` pre · `2` regular · `3` post |

```jsonc
{
  "name": "National Basketball Association",
  "children": [
    { "name": "Eastern Conference",
      "standings": { "entries": [ { "team": { "displayName": "Boston Celtics" },
        "stats": [ { "name": "wins", "value": 64 }, { "name": "losses", "value": 18 } ] } ] } }
  ]
}
```

### Game summary

```
GET https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary?event={event}
```

| Param | Type | Description |
|---|---|---|
| `sport` / `league` | string (required) | e.g. `football` / `nfl` |
| `event` | string (required) | Event id from `espn_scoreboard` |

The everything-view for one game: `boxscore`, `drives` / `plays`, `scoringPlays`, `leaders`, `winprobability`, `odds`, `injuries`, `broadcasts`.

```jsonc
{ "boxscore": { "teams": [...], "players": [...] }, "drives": {...}, "leaders": [...], "winprobability": [...] }
```

### News

```
GET https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/news
```

| Param | Type | Description |
|---|---|---|
| `sport` / `league` | string (required) | e.g. `football` / `nfl` |
| `limit` | integer (default 50) | Max articles |

```jsonc
{ "header": "NFL News", "articles": [ { "headline": "...", "description": "...", "published": "...", "links": {...} } ] }
```

---

## espn.site: the site dispatcher

**`espn_site_call`** — one tool over the site API resource families (`base: site`). Supply an `operation`, a `path_params` map (at least `sport` + `league`, plus any id the op needs), and optional `query_params`. Browse live at **`espn://site/operations`**.

```jsonc
// espn_site_call — Patrick Mahomes' game log (athleteId 3139477)
{ "operation": "athlete_gamelog",
  "path_params": { "sport": "football", "league": "nfl", "athleteId": "3139477" } }
```

| Operation | Path params (beyond sport/league) | Returns |
|---|---|---|
| `team_detail` | `teamId` | Team record, standing, next event |
| `team_roster` | `teamId` | Roster: athletes, position, jersey, physicals |
| `team_schedule` | `teamId` | Schedule + results for a season (form) |
| `team_injuries` | `teamId` | Injury report (athlete, status, type) |
| `team_depthchart` | `teamId` | Depth chart (positional ordering) |
| `team_transactions` | `teamId` | Transactions (signings, trades, waivers) |
| `team_history` | `teamId` | Season-by-season team history |
| `athlete` | `athleteId` | Athlete profile (position, team, status) |
| `athlete_gamelog` | `athleteId` | Game-by-game log for the season |
| `athlete_splits` | `athleteId` | Statistical splits |
| `athlete_news` | `athleteId` | News for one athlete |
| `athlete_bio` | `athleteId` | Biography (birthplace, draft, college) |
| `groups` | — | Conference/division groups (group ids) |
| `rankings` | — | Poll rankings (mainly college) |
| `calendar` | — | Season calendar (dates/weeks with games) |
| `scoreboard_v3` | — | v3 scoreboard variant |
| `summary_v3` | — | v3 game summary (query `event`) |

---

## espn.core: the core dispatcher

**`espn_core_call`** — one tool over the canonical core model (`base: core`). The deepest surface. **Path uses `leagues/{league}` (plural).** Most responses are the `$ref`-linked envelope — follow the refs. Browse live at **`espn://core/operations`**.

```jsonc
// espn_core_call — odds for one competition
{ "operation": "event_odds",
  "path_params": { "sport": "football", "league": "nfl", "eventId": "401547439", "competitionId": "401547439" } }
```

| Operation | Path params (beyond sport/league) | Returns |
|---|---|---|
| `athletes` | — | Athlete index (`{count, items:[{$ref}]}`) |
| `athlete` | `athleteId` | Single athlete (core model) |
| `athlete_statistics` | `athleteId` | Season statistics (categorised) |
| `athlete_statisticslog` | `athleteId` | Per-season career stats log |
| `athlete_eventlog` | `athleteId` | Games played (per-game stat `$ref`s) |
| `event_odds` | `eventId`, `competitionId` | Per-book odds (spread, ML, total) |
| `event_probabilities` | `eventId`, `competitionId` | Win-probability time series |
| `event_plays` | `eventId`, `competitionId` | Play-by-play |
| `event_situation` | `eventId`, `competitionId` | Live situation (down/distance, bases) |
| `event_broadcasts` | `eventId`, `competitionId` | Broadcast listings (networks/markets) |
| `event_predictor` | `eventId`, `competitionId` | Matchup predictor (projected score / win %) |
| `event_powerindex` | `eventId`, `competitionId` | Game power-index per competitor |
| `competitor_linescores` | `eventId`, `competitionId`, `competitorId` | Per-period line score |
| `competitor_statistics` | `eventId`, `competitionId`, `competitorId` | Per-game team stats |
| `seasons` | — | Season catalogue |
| `season_teams` | `year` | Teams active in a season |
| `season_coaches` | `year` | Coaches for a season |
| `season_draft` | `year` | Draft results / picks |
| `season_futures` | `year` | Season-long futures markets |
| `standings` | — | Core standings (`$ref` to group standings) |
| `teams` | — | Team index (core model) |
| `venues` | — | Venue catalogue (id, name, city, capacity) |
| `leaders` | — | Season statistical leaders |
| `rankings` | — | Poll rankings (core model) |
| `franchises` | — | Franchise catalogue (stable identity) |
| `coach` | `coachId` | Single coach (record, team, experience) |

---

## espn.web: the web dispatcher

**`espn_web_call`** — site-wide search + the `common/v3` athlete views (`base: web`). `search` needs only `query_params`; the `athlete_*` ops need `path_params` (sport, league, athleteId). Browse live at **`espn://web/operations`**.

```jsonc
// espn_web_call — find an athlete by name
{ "operation": "search", "query_params": { "query": "lebron", "limit": 5 } }
```

| Operation | Path params | Query params | Returns |
|---|---|---|---|
| `search` | — | `query`, `limit`, `sport` | Teams/athletes/leagues/articles by text |
| `scoreboard_header` | — | `sport`, `league`, `dates` | Compact multi-sport top-bar scoreboard |
| `athlete_overview` | `sport`, `league`, `athleteId` | — | Profile overview: headline stats, news |
| `athlete_stats` | `sport`, `league`, `athleteId` | — | Season + career statistics tables |
| `athlete_gamelog` | `sport`, `league`, `athleteId` | `season`, `seasontype` | Game-by-game log (web/v3 shape) |
| `athlete_splits` | `sport`, `league`, `athleteId` | `season`, `category` | Statistical splits (web/v3 shape) |
| `stats_byathlete` | `sport`, `league` | `season`, `page`, `sort` | League leaderboard ranked by athlete |

---

## espn.cdn: the CDN dispatcher

**`espn_cdn_call`** — the CDN live core feed (`base: cdn`). The path slug is the **league** (`nfl`, `nba`, `mlb`, `nhl`); for soccer use `sport=soccer` + a `league=eng.1` query. `xhr=1` is supplied automatically. `gameId` comes from the `scoreboard` op. Browse live at **`espn://cdn/operations`**.

```jsonc
// espn_cdn_call — NFL scoreboard
{ "operation": "scoreboard", "path_params": { "sport": "nfl" } }

// espn_cdn_call — one game's box score
{ "operation": "boxscore", "path_params": { "sport": "nfl" }, "query_params": { "gameId": "401547439" } }
```

| Operation | Path | Query params | Returns |
|---|---|---|---|
| `scoreboard` | `/core/{sport}/scoreboard` | `dates`, `league` | Scoreboard for a league slug; events + ids |
| `game` | `/core/{sport}/game` | `gameId`, `league` | Single-game feed |
| `boxscore` | `/core/{sport}/boxscore` | `gameId`, `league` | Box score for one game |
| `playbyplay` | `/core/{sport}/playbyplay` | `gameId`, `league` | Play-by-play for one game |

All four carry `xhr=1` as a query default so the feed returns JSON.

---

## Endpoint quick reference

Tools exposed by this server's ESPN spec:

| Tool | Group | Host | Path |
|---|---|---|---|
| `espn_scoreboard` | `espn.scores` | site | `/apis/site/v2/sports/{sport}/{league}/scoreboard` |
| `espn_teams` | `espn.scores` | site | `/apis/site/v2/sports/{sport}/{league}/teams` |
| `espn_standings` | `espn.scores` | site | `/apis/v2/sports/{sport}/{league}/standings` |
| `espn_game_summary` | `espn.scores` | site | `/apis/site/v2/sports/{sport}/{league}/summary?event=…` |
| `espn_news` | `espn.scores` | site | `/apis/site/v2/sports/{sport}/{league}/news` |
| `espn_site_call` | `espn.site` | site | dispatcher over 17 ops (catalogue: `espn://site/operations`) |
| `espn_core_call` | `espn.core` | core | dispatcher over 26 ops (catalogue: `espn://core/operations`) |
| `espn_web_call` | `espn.web` | web | dispatcher over 7 ops (catalogue: `espn://web/operations`) |
| `espn_cdn_call` | `espn.cdn` | cdn | dispatcher over 4 ops (catalogue: `espn://cdn/operations`) |

**Discovery flow:** `espn_scoreboard(sport, league)` → grab an `event` id → `espn_game_summary(sport, league, event=…)` for box score + plays, or `espn_core_call(event_odds / event_probabilities / event_plays, …)` for the deep per-event model. Use `espn_teams` / `espn_standings` / `espn_news` for league-wide context, `espn_web_call(search)` to resolve an `athleteId`, and `espn_site_call` / `espn_core_call` for the deeper resource families.
