# NBA API Documentation

Unofficial reference for the JSON endpoints used by `www.nba.com` and the NBA apps. Two hosts make up the public surface:

- **`cdn.nba.com`** — the **open** content CDN. No headers, no throttle, no auth. Serves today's scoreboard, the full season schedule, live box scores + play-by-play, and odds as static JSON (often labelled `text/plain`).
- **`stats.nba.com`** — the **analytics** API (the `/stats/` family, 137 endpoints, plus a `/js/data/` feed). Fronted by **Akamai**, which black-holes any request that doesn't carry a full browser header bundle, and rate-limits aggressively. No bearer token is required — the "auth" is purely the header bundle + a polite request rate.

> This document is generated from the packaged provider spec (`src/sportsdata_mcp/specs/nba.yaml`) and NBA's public surface as observed on 2026-06-01. The `/stats/` operation catalogue (names, required params and shipped defaults) is the spec's source of truth and is also exposed live at the `nba://stats/operations` MCP resource. Season-dependent defaults reflect the current `2025-26` season.

---

## Table of Contents

- [Hosts & services](#hosts--services)
- [Authentication](#authentication)
- [Conventions](#conventions)
  - [Identifiers](#identifiers)
  - [Season & season type](#season--season-type)
  - [Common query parameters](#common-query-parameters)
  - [Response shapes](#response-shapes)
  - [Rate limiting & errors](#rate-limiting--errors)
- [cdn.nba.com: open CDN JSON](#cdnnbacom-open-cdn-json)
  - [Today's scoreboard](#todays-scoreboard)
  - [Season schedule](#season-schedule)
  - [Box score (single game)](#box-score-single-game)
  - [Play-by-play (single game)](#play-by-play-single-game)
  - [Today's odds](#todays-odds)
- [stats.nba.com: JS data feed](#statsnbacom-js-data-feed)
  - [Daily lineups](#daily-lineups)
- [stats.nba.com: the /stats/ dispatcher](#statsnbacom-the-stats-dispatcher)
  - [How a call is built](#how-a-call-is-built)
  - [Worked examples](#worked-examples)
- [/stats/ operation reference](#stats-operation-reference)
  - [Scoreboard & schedule](#scoreboard--schedule)
  - [Box scores (per GameID)](#box-scores-per-gameid)
  - [Play-by-play & in-game (per GameID)](#play-by-play--in-game-per-gameid)
  - [League dashboards — players](#league-dashboards--players)
  - [League dashboards — teams & lineups](#league-dashboards--teams--lineups)
  - [League-wide lists & standings](#league-wide-lists--standings)
  - [Player profile & dashboards](#player-profile--dashboards)
  - [Player tracking](#player-tracking)
  - [Team profile & dashboards](#team-profile--dashboards)
  - [Team tracking](#team-tracking)
  - [Shot charts](#shot-charts)
  - [Leaders & home page](#leaders--home-page)
  - [Franchise](#franchise)
  - [Draft & combine](#draft--combine)
  - [Cumulative stats](#cumulative-stats)
  - [Video](#video)
  - [Specialized / misc](#specialized--misc)
- [Endpoint quick reference](#endpoint-quick-reference)

---

## Hosts & services

| Host / sub-path | Service | Auth | Throttle |
|---|---|---|---|
| `cdn.nba.com/static/json/liveData/...` | Live scoreboard / box score / play-by-play / odds | ❌ none | ❌ none needed |
| `cdn.nba.com/static/json/staticData/...` | Static season schedule | ❌ none | ❌ none needed |
| `stats.nba.com/js/data/...` | JS data feed (daily lineups, leaders) | header bundle | ⚠️ Akamai |
| `stats.nba.com/stats/...` | The `/stats/` analytics API (137 ops) | header bundle | ⚠️ Akamai |

The two hosts map to the provider's two `base_urls`:

```jsonc
{
  "default": "https://stats.nba.com",   // /stats/ + /js/data/ feeds
  "cdn":     "https://cdn.nba.com"       // open static/liveData JSON
}
```

---

## Authentication

There is **no bearer token or API key.** Both hosts are anonymous. The only access control is on `stats.nba.com`:

### `cdn.nba.com`

Nothing required. Anonymous `GET` works on every path. Note the CDN frequently serves valid JSON with a `Content-Type: text/plain` header — a strict JSON client that keys off content-type will reject it, so parse the body regardless of the declared type.

### `stats.nba.com`

Akamai black-holes any request that doesn't look like the real web client. The full browser header bundle the front-end sends (and which the spec ships in `provider.default_headers`) is:

```jsonc
{
  "User-Agent":          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Accept":              "application/json, text/plain, */*",
  "Accept-Language":     "en-US,en;q=0.9",
  "Referer":             "https://www.nba.com/",
  "Origin":              "https://www.nba.com",
  "Connection":          "keep-alive",
  "x-nba-stats-origin":  "stats",
  "x-nba-stats-token":   "true",
  "Sec-Fetch-Dest":      "empty",
  "Sec-Fetch-Mode":      "cors",
  "Sec-Fetch-Site":      "same-site",
  "Cache-Control":       "no-cache",
  "Pragma":              "no-cache"
}
```

Missing this bundle (or sending it from a flagged IP) yields a hung connection or an Akamai "Access Denied" HTML page rather than a clean HTTP error.

Akamai also rate-limits hard. The spec throttles `stats.nba.com` to ~1 request / 2.5 s and retries transient errors:

```jsonc
{
  "rate_limit_rps":         0.4,                       // ~1 request / 2.5s sustained
  "request_timeout_seconds": 45,
  "burst":                  1,
  "retry_statuses":         [429, 500, 502, 503, 504],
  "max_retries":            3,
  "retry_backoff_seconds":  1.0                         // exponential: 1s, 2s, 4s
}
```

All of these are overridable per-operator via `providers.nba.*` in config. Raising the rate is at your own risk.

---

## Conventions

### Identifiers

| ID | Form | Example | Resolve via |
|---|---|---|---|
| `GameID` | 10-digit string | `0022300001` | `nba_scoreboard_today`, `nba_schedule` (CDN); `scoreboardv2`, `leaguegamelog` (stats) |
| `TeamID` | 10-digit int, `1610612737`–`1610612766` | `1610612747` (Lakers) | `commonteamyears`, `franchisehistory` |
| `PlayerID` | int | `2544` (LeBron James), `201939` (Stephen Curry) | `playerindex`, `commonallplayers` |
| `Season` | `YYYY-YY` string | `2025-26` | n/a (literal) |

The `GameID` prefix encodes the game type: `001…` Pre Season, `002…` Regular Season, `003…` All-Star, `004…` Playoffs, `005…` Play-In.

### Season & season type

| Param | Values |
|---|---|
| `Season` | `YYYY-YY`, e.g. `2025-26`. A few draft/combine ops take a 4-digit `SeasonYear` (`2025`) instead. |
| `SeasonType` | `Regular Season` · `Playoffs` · `Pre Season` · `Play In` |
| `LeagueID` | `00` NBA · `10` WNBA · `20` G-League |

### Common query parameters

Many `/stats/` dashboards share these (all defaulted in the spec, so override only what matters):

| Param | Values |
|---|---|
| `PerMode` | `Totals` · `PerGame` · `Per100Possessions` · `PerMinute` … |
| `MeasureType` | `Base` · `Advanced` · `Misc` · `Four Factors` · `Scoring` · `Opponent` · `Usage` · `Defense` |
| `LastNGames` | `0` = all, else last N |
| `Month` | `0` = all, else 1-12 |
| `OpponentTeamID` | `0` = all |
| `Location` / `Outcome` / `VsConference` / `VsDivision` / `GameSegment` / `Period` | filters; empty = no filter |

### Response shapes

Three distinct envelopes:

1. **Classic `/stats/`** — column-oriented. Zip each `resultSet`'s `headers` with each row in `rowSet`:

   ```jsonc
   {
     "resource": "leaguedashplayerstats",
     "parameters": { "Season": "2025-26", "PerMode": "Totals", "...": "..." },
     "resultSets": [
       {
         "name": "LeagueDashPlayerStats",
         "headers": ["PLAYER_ID", "PLAYER_NAME", "TEAM_ID", "GP", "PTS", "REB", "AST", "..."],
         "rowSet": [
           [201939, "Stephen Curry", 1610612744, 70, 1850, 320, 410, "..."]
         ]
       }
     ]
   }
   ```

   A few ops (e.g. `leagueleaders` with `LeagueLeaders` set) use the alias key `resultSet` (singular) — handle both.

2. **v3 box scores** — nested objects (not column-oriented):

   ```jsonc
   {
     "meta": { "version": 1, "request": "...", "time": "..." },
     "boxScoreTraditional": {
       "gameId": "0022300001",
       "homeTeam": { "teamId": 1610612747, "players": [ { "name": "...", "statistics": { "points": 30, "...": "..." } } ] },
       "awayTeam": { "...": "..." }
     }
   }
   ```

3. **CDN liveData** — already-nested JSON, documented inline per endpoint below.

### Rate limiting & errors

`stats.nba.com` failure modes, in order of likelihood:

| Symptom | Cause | Handling |
|---|---|---|
| Hung request / timeout | Akamai black-hole (missing/flagged headers) or hard throttle | Backoff + retry (spec does this for `429/5xx`); a persistent hang means the IP is flagged |
| HTTP 429 | Rate limit | Spec retries with exponential backoff; lower `rate_limit_rps` if frequent |
| Non-JSON `text/html` body | Akamai "Access Denied" challenge page | Treated as a non-recoverable bot-block |
| Empty `rowSet` | Valid query, no matching data (e.g. off-day, wrong Season) | Not an error — check your filters |

A malformed `operation` is a recoverable error that points back at the catalogue (`nba://stats/operations`).

---

## cdn.nba.com: open CDN JSON

Five endpoints, all anonymous, all on `base: cdn`. These are the fastest path to live game data and require none of the stats.nba.com ceremony.

### Today's scoreboard

```
GET https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json
```

The fastest way to get today's `gameId` values (for `nba_boxscore` / `nba_playbyplay`). The envelope is always present even on an off day — `games` is simply `[]`.

```jsonc
{
  "scoreboard": {
    "gameDate": "2026-06-01",
    "games": [
      {
        "gameId": "0042500401",
        "gameStatus": 2,                 // 1 = scheduled, 2 = live, 3 = final
        "gameStatusText": "Q3 04:21",
        "period": 3,
        "gameClock": "PT04M21.00S",
        "homeTeam": { "teamId": 1610612747, "teamTricode": "LAL", "score": 78 },
        "awayTeam": { "teamId": 1610612738, "teamTricode": "BOS", "score": 81 }
      }
    ]
  }
}
```

### Season schedule

```
GET https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json
```

The whole-season schedule (every game, date, broadcasters, arena). **Large payload (~8 MB)** — for just today, prefer the scoreboard.

```jsonc
{
  "leagueSchedule": {
    "seasonYear": "2025-26",
    "gameDates": [
      { "gameDate": "10/21/2025 00:00:00",
        "games": [ { "gameId": "0022500001", "homeTeam": { "...": "..." }, "awayTeam": { "...": "..." } } ] }
    ]
  }
}
```

### Box score (single game)

```
GET https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gameId}.json
```

| Param | Type | Description |
|---|---|---|
| `gameId` | string (required) | 10-digit game id from the scoreboard / schedule, e.g. `0022300001`. |

Live/final per-player and per-team stat lines, by period.

```jsonc
{
  "game": {
    "gameId": "0022300001",
    "homeTeam": { "teamId": 1610612747, "players": [ { "name": "LeBron James", "statistics": { "points": 28, "reboundsTotal": 11, "assists": 8 } } ] },
    "awayTeam": { "...": "..." }
  }
}
```

### Play-by-play (single game)

```
GET https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_{gameId}.json
```

| Param | Type | Description |
|---|---|---|
| `gameId` | string (required) | 10-digit game id. |

Event-level log: every action with clock, score, player and description.

```jsonc
{
  "game": {
    "gameId": "0022300001",
    "actions": [
      { "actionNumber": 4, "period": 1, "clock": "PT11M42.00S",
        "scoreHome": "2", "scoreAway": "0", "description": "James 2' Driving Layup" }
    ]
  }
}
```

### Today's odds

```
GET https://cdn.nba.com/static/json/liveData/odds/odds_todaysGames.json
```

Sportsbook odds for today's games (spread, money line, total per game and book).

```jsonc
{
  "games": [
    { "gameId": "0042500401",
      "markets": [ { "name": "2way", "books": [ { "name": "...", "outcomes": [ { "...": "..." } ] } ] } ] }
  ]
}
```

---

## stats.nba.com: JS data feed

### Daily lineups

```
GET https://stats.nba.com/js/data/leaders/00_daily_lineups_{date}.json
```

| Param | Type | Description |
|---|---|---|
| `date` | string (required) | `YYYYMMDD`, e.g. `20260101`. |

Projected/confirmed starting lineups for a date's games. This sits on `stats.nba.com`, so it needs the header bundle + throttle (the spec applies both). The exact feed shape varies by date:

```jsonc
{ "games": [ { "gameId": "...", "homeTeam": "...", "awayTeam": "...", "lineups": "..." } ] }
```

---

## stats.nba.com: the /stats/ dispatcher

The 137 `/stats/` endpoints are exposed through **one** tool, `nba_stats_call`, rather than 137 separate tools.

### How a call is built

You supply:

| Field | Required | Description |
|---|---|---|
| `operation` | ✅ | The `/stats/` path segment, e.g. `leaguedashplayerstats`, `shotchartdetail`, `boxscoretraditionalv3`. |
| `query_params` | — | Map of overrides, e.g. `{Season: "2024-25", PlayerID: "201939"}`. |
| `path_params` | — | Map of path-template values. No shipping op currently needs these, but the input exists for path-templated ops. |

Each operation ships its **full default query-param set** (most fields default to empty strings, which NBA's API requires to be present). The dispatcher merges your `query_params` *over* those defaults:

```
final_query = { **op.query_defaults, **query_params }
```

So you override only the fields that matter; everything else flows up as its default. Browse every operation, its required params and its defaults at the **`nba://stats/operations`** resource.

### Worked examples

**Top scorers, this season, per game:**

```jsonc
// nba_stats_call
{ "operation": "leaguedashplayerstats",
  "query_params": { "PerMode": "PerGame" } }
// → resultSets[0] = { name: "LeagueDashPlayerStats", headers: [...], rowSet: [[...]] }
```

**Stephen Curry's career stats:**

```jsonc
{ "operation": "playercareerstats",
  "query_params": { "PlayerID": "201939" } }
// → resultSets: SeasonTotalsRegularSeason, CareerTotalsRegularSeason, ...
```

**A player's made/missed shots for a season (shot chart):** `shotchartdetail` requires both `TeamID` and `PlayerID`; pass `TeamID: "0"` to span all of a player's teams. `ContextMeasure` defaults to `PTS`.

```jsonc
{ "operation": "shotchartdetail",
  "query_params": { "PlayerID": "201939", "TeamID": "0", "Season": "2024-25" } }
// → resultSets: Shot_Chart_Detail (LOC_X/LOC_Y per shot), LeagueAverages
```

**Standings, overriding just the season:** the op's other defaults flow up untouched.

```jsonc
{ "operation": "leaguestandingsv3",
  "query_params": { "Season": "2024-25" } }
// → resultSets[0] = { name: "Standings", rowSet: 30 rows }
```

**Full traditional box score (v3, nested):**

```jsonc
{ "operation": "boxscoretraditionalv3",
  "query_params": { "GameID": "0022300001" } }
// → boxScoreTraditional: { gameId, homeTeam:{players:[...]}, awayTeam:{...} }
```

---

## /stats/ operation reference

All 137 operations, grouped by family. The **Req** column lists the `query_params` you must supply (everything else is defaulted). Read full per-op defaults at `nba://stats/operations`.

### Scoreboard & schedule

| Operation | Req | Returns |
|---|---|---|
| `scoreboardv2` | — | Scoreboard for a date (`GameDate` default = today). resultSets: GameHeader, LineScore, … |
| `scoreboardv3` | `GameDate` | Scoreboard v3 for a date. |
| `scheduleleaguev2` | — | League schedule. |

### Box scores (per GameID)

All take `GameID`. `v2` variants are deprecated for 2025-26 — prefer the `v3` sibling.

| Operation | Returns |
|---|---|
| `boxscoretraditionalv2` / `boxscoretraditionalv3` | PlayerStats, TeamStarterBenchStats, TeamStats |
| `boxscoreadvancedv2` / `boxscoreadvancedv3` | PlayerStats, TeamStats (advanced) |
| `boxscorescoringv2` / `boxscorescoringv3` | Scoring breakdown |
| `boxscoremiscv2` / `boxscoremiscv3` | Misc stats |
| `boxscoreusagev2` / `boxscoreusagev3` | Usage stats |
| `boxscorefourfactorsv2` / `boxscorefourfactorsv3` | Four factors |
| `boxscoresummaryv2` / `boxscoresummaryv3` | GameSummary, GameInfo, Officials, LineScore, InactivePlayers, … |
| `boxscoredefensivev2` | Defensive box (v2 only) |
| `boxscorematchupsv3` | Per-matchup defensive assignments |
| `boxscoreplayertrackv3` | Player-tracking box |
| `boxscorehustlev2` | Hustle stats |
| `hustlestatsboxscore` | HustleStatsAvailable, PlayerStats, TeamStats |
| `infographicfanduelplayer` | FanDuel infographic player line |

### Play-by-play & in-game (per GameID)

| Operation | Req | Returns |
|---|---|---|
| `playbyplay` / `playbyplayv2` / `playbyplayv3` | `GameID` | Event-level play log |
| `gamerotation` | `GameID` | AwayTeam, HomeTeam substitution rotation |
| `winprobabilitypbp` | `GameID` | Win-probability per event |
| `videoevents` | `GameID` | Video event index for a game |

### League dashboards — players

None require params (all defaulted; set `Season`, `PerMode`, `MeasureType`, filters as needed).

| Operation | Returns |
|---|---|
| `leaguedashplayerstats` | Per-player season stats (the main player leaderboard) |
| `leaguedashplayerbiostats` | Bio + advanced (height, age, usage, …) |
| `leaguedashplayerclutch` | Clutch-time splits |
| `leaguedashplayerptshot` | Player tracking shot stats |
| `leaguedashplayershotlocations` | Shot stats by zone/distance |
| `leaguedashptdefend` | Player tracking defensive stats |

### League dashboards — teams & lineups

| Operation | Req | Returns |
|---|---|---|
| `leaguedashteamstats` | — | Per-team season stats |
| `leaguedashteamclutch` | — | Team clutch splits |
| `leaguedashteamptshot` | — | Team tracking shot stats |
| `leaguedashteamshotlocations` | — | Team shot stats by zone |
| `leaguedashptteamdefend` | — | Team tracking defense |
| `leaguedashptstats` | — | Player-or-team tracking stats (`PlayerOrTeam`) |
| `leaguedashoppptshot` | — | Opponent tracking shot stats |
| `leaguedashlineups` | — | 5-man (etc.) lineup stats (`GroupQuantity`) |
| `leaguelineupviz` | `MinutesMin` | Lineup efficiency viz |

### League-wide lists & standings

| Operation | Req | Returns |
|---|---|---|
| `leagueleaders` | — | Statistical leaders (`StatCategory`, `PerMode`, `Scope`) |
| `leaguestandings` / `leaguestandingsv3` | — | Standings (30 rows) |
| `leaguegamelog` | — | Every game log line for a season (`PlayerOrTeam`) |
| `leaguegamefinder` | — | Filterable game finder (rich `Eq*`/`Gt*`/`Lt*` filters) |
| `leaguehustlestatsplayer` / `leaguehustlestatsteam` | — | Hustle leaderboards |
| `leagueseasonmatchups` | — | Season matchup rollup (off/def player ids) |
| `leagueplayerondetails` | `TeamID` | On-court player details for a team |
| `matchupsrollup` | — | Defensive matchups rollup |
| `iststandings` | — | In-Season Tournament standings |
| `playoffpicture` | — | Live playoff/play-in picture |
| `commonplayoffseries` | — | Playoff series for a season |

### Player profile & dashboards

| Operation | Req | Returns |
|---|---|---|
| `commonallplayers` | — | All players (roster index for a season) |
| `commonplayerinfo` | `PlayerID` | Bio, draft, headline stats |
| `playerindex` | — | Searchable player index |
| `playercareerstats` | `PlayerID` | Season + career totals (regular/post/college) |
| `playerprofilev2` | `PlayerID` | Career profile + season highs |
| `playergamelog` | `PlayerID` | Game-by-game log (one season) |
| `playergamelogs` | — | Game logs across players/seasons (filterable) |
| `playerawards` | `PlayerID` | Awards/honours |
| `playercompare` | `PlayerIDList`, `VsPlayerIDList` | Head-to-head player comparison |
| `playervsplayer` | `PlayerID`, `VsPlayerID` | One-vs-one splits |
| `playerestimatedmetrics` | — | Estimated advanced metrics, all players |
| `playernextngames` | `PlayerID` | Upcoming schedule for a player |
| `playergamestreakfinder` | — | Streak finder (player games) |
| `playerfantasyprofilebargraph` | `PlayerID` | Fantasy profile bar-graph data |
| `playercareerbycollege` | `College` | Players by college |
| `playercareerbycollegerollup` | — | College rollup |
| `playerdashboardbygeneralsplits` | `PlayerID` | General splits |
| `playerdashboardbyclutch` | `PlayerID` | Clutch splits |
| `playerdashboardbygamesplits` | `PlayerID` | By-game splits (half, quarter, …) |
| `playerdashboardbylastngames` | `PlayerID` | Last-N splits |
| `playerdashboardbyshootingsplits` | `PlayerID` | Shooting splits |
| `playerdashboardbyteamperformance` | `PlayerID` | By team performance (W/L, margin) |
| `playerdashboardbyyearoveryear` | `PlayerID` | Year-over-year |

### Player tracking

All take `TeamID` + `PlayerID` (use `TeamID: "0"` to span teams).

| Operation | Returns |
|---|---|
| `playerdashptpass` | Passing (passes made/received) |
| `playerdashptreb` | Rebounding detail |
| `playerdashptshots` | Shooting detail (dribbles, touch time, defender distance) |
| `playerdashptshotdefend` | Defensive shot impact |

### Team profile & dashboards

| Operation | Req | Returns |
|---|---|---|
| `commonteamyears` | — | Franchise/year span for every team (id ↔ name resolver) |
| `commonteamroster` | `TeamID` | Coaches + roster |
| `teamdetails` | `TeamID` | Team detail (arena, history, social, championships) |
| `teaminfocommon` | `TeamID` | Common team info + season ranks |
| `teamgamelog` | `TeamID` | Game-by-game log (one season) |
| `teamgamelogs` | — | Game logs across teams/seasons (filterable) |
| `teamyearbyyearstats` | `TeamID` | Year-by-year team stats |
| `teamhistoricalleaders` | `TeamID` | All-time franchise leaders |
| `teamestimatedmetrics` | — | Estimated advanced metrics, all teams |
| `teamplayerdashboard` | `TeamID` | Per-player splits for a team |
| `teamplayeronoffdetails` | `TeamID` | On/off-court detail |
| `teamplayeronoffsummary` | `TeamID` | On/off-court summary |
| `teamvsplayer` | `TeamID`, `VsPlayerID` | Team vs a specific player |
| `teamandplayersvsplayers` | `TeamID`, `PlayerID1..5`, `VsTeamID`, `VsPlayerID1..5` | 5-on-5 unit matchup |
| `teamgamestreakfinder` | — | Streak finder (team games) |
| `teamdashboardbygeneralsplits` | `TeamID` | General splits |
| `teamdashboardbyshootingsplits` | `TeamID` | Shooting splits |
| `teamdashlineups` | `TeamID` | Team lineup combinations |

### Team tracking

All take `TeamID`.

| Operation | Returns |
|---|---|
| `teamdashptpass` | Passing detail |
| `teamdashptreb` | Rebounding detail |
| `teamdashptshots` | Shooting detail |

### Shot charts

| Operation | Req | Returns |
|---|---|---|
| `shotchartdetail` | `TeamID`, `PlayerID` | Per-shot LOC_X/LOC_Y + make/miss (`ContextMeasure` default `PTS`); `TeamID: "0"` spans teams |
| `shotchartleaguewide` | — | League-wide shot zones |
| `shotchartlineupdetail` | — | Shot chart for a lineup |

### Leaders & home page

None require params.

| Operation | Returns |
|---|---|
| `alltimeleadersgrids` | All-time leaders per stat (AST/BLK/DREB/…) |
| `assistleaders` | Assist leaders (player or team) |
| `assisttracker` | Tracked assist totals |
| `leaderstiles` | "Leaders" tiles incl. season/all-time highs |
| `homepageleaders` | Home-page leaders (`StatCategory`) |
| `homepagev2` | Home-page stat tiles v2 |
| `defensehub` | Defensive hub leaders |
| `dunkscoreleaders` | Dunk score leaders |
| `gravityleaders` | Gravity (off-ball) leaders |

### Franchise

| Operation | Req | Returns |
|---|---|---|
| `franchisehistory` | — | Franchise history + defunct teams |
| `franchiseleaders` | `TeamID` | All-time franchise leaders |
| `franchiseplayers` | `TeamID` | All players to play for a franchise |

### Draft & combine

None require params (`Season`/`SeasonYear` defaulted to the current draft class).

| Operation | Returns |
|---|---|
| `drafthistory` | Full draft history (filterable) |
| `draftboard` | Draft board for a season |
| `draftcombinestats` | Combine stats |
| `draftcombinedrillresults` | Combine drill results |
| `draftcombinenonstationaryshooting` | Non-stationary shooting |
| `draftcombineplayeranthro` | Anthropometric measurements |
| `draftcombinespotshooting` | Spot shooting |

### Cumulative stats

| Operation | Req | Returns |
|---|---|---|
| `cumestatsplayer` | `PlayerID`, `GameIDs` | Cumulative player stats across given games |
| `cumestatsplayergames` | `PlayerID` | Game list for a player (feeds `cumestatsplayer`) |
| `cumestatsteam` | `TeamID`, `GameIDs` | Cumulative team stats across given games |
| `cumestatsteamgames` | `TeamID` | Game list for a team |

### Video

| Operation | Req | Returns |
|---|---|---|
| `videodetails` | `TeamID`, `PlayerID` | Video clip index for events |
| `videodetailsasset` | `TeamID`, `PlayerID` | Video clip index w/ asset URLs |
| `videoevents` | `GameID` | Per-game video events |
| `videostatus` | — | Video availability by date |

### Specialized / misc

| Operation | Req | Returns |
|---|---|---|
| `synergyplaytypes` | — | Synergy play-type stats (iso, P&R, post-up, …) |
| `fantasywidget` | — | Fantasy widget result set |
| `glalumboxscoresimilarityscore` | `Person1Id`, `Person2Id` | G-League alum box-score similarity |

---

## Endpoint quick reference

Tools exposed by this server's NBA spec:

| Tool | Group | Host | Path |
|---|---|---|---|
| `nba_scoreboard_today` | `nba.public.cdn` | cdn | `/static/json/liveData/scoreboard/todaysScoreboard_00.json` |
| `nba_schedule` | `nba.public.cdn` | cdn | `/static/json/staticData/scheduleLeagueV2_1.json` |
| `nba_boxscore` | `nba.public.cdn` | cdn | `/static/json/liveData/boxscore/boxscore_{gameId}.json` |
| `nba_playbyplay` | `nba.public.cdn` | cdn | `/static/json/liveData/playbyplay/playbyplay_{gameId}.json` |
| `nba_odds_today` | `nba.public.cdn` | cdn | `/static/json/liveData/odds/odds_todaysGames.json` |
| `nba_daily_lineups` | `nba.stats` | stats | `/js/data/leaders/00_daily_lineups_{date}.json` |
| `nba_stats_call` | `nba.stats` | stats | `/stats/{operation}` — dispatcher over 137 ops (catalogue: `nba://stats/operations`) |

**Discovery flow:** `nba_scoreboard_today` → grab a `gameId` → `nba_boxscore` / `nba_playbyplay` for that game; or `nba_stats_call` with an analytics `operation` (resolve `TeamID`/`PlayerID` via `commonteamyears` / `playerindex` first).
