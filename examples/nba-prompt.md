# Worked example — NBA shot chart + box score for a game

A demonstration of the **dispatcher pattern**: going from "today's games" to a
per-player shot chart by combining the open CDN surface with the
`nba_stats_call` gateway over the 137-endpoint `stats.nba.com` `/stats/` API.
Load the server with [`nba-config.yaml`](./nba-config.yaml), which enables both
NBA tool groups.

```
sportsdata-mcp --config examples/nba-config.yaml serve
```

---

## The prompt

> For tonight's marquee NBA game, show me the box-score line for the top scorer
> and where they took their shots from.

## Why this works

NBA is a single provider with **two surfaces** behind one config:

- `cdn.nba.com` — wide open JSON (no auth, no special headers). It serves
  today's scoreboard, the full schedule, live box scores, play-by-play and odds.
  It even labels JSON as `text/plain`; the client accepts it anyway.
- `stats.nba.com` — the analytics `/stats/` API, behind Akamai. The spec ships
  the full browser header bundle in `provider.default_headers` so requests get
  through, and throttles to ~1 req / 2.5 s with 429/5xx retry so you don't get
  rate-limited.

Crucially, the 137 `/stats/` endpoints are **one tool**, `nba_stats_call`. You
pick an `operation` (the path segment, e.g. `shotchartdetail`) and pass
`query_params`. Every operation already carries NBA's full, mostly-empty default
param set, so you override only the handful of fields that matter. Browse the
whole catalogue — every operation, its required params and its defaults — in the
`nba://stats/operations` resource.

> **Note on capabilities.** Unlike the [cross-bookie example](./comparator-prompt.md),
> where a shared capability slug lets you compare the *same* event across bookies,
> NBA's stat capabilities are marked `single_provider: true`. Here the capability
> index is a **discovery aid** (find the right tool for a question), not a
> comparison axis — there's no second NBA-data provider to line up against.

## Expected tool-call sequence

### 1. Find tonight's game and its ids

```jsonc
// tool: nba_scoreboard_today
{}
```

Returns `{scoreboard:{gameDate, games:[...]}}`. Each game carries the
`gameId` plus `homeTeam`/`awayTeam` with their `teamId`s and live score —
pick the marquee matchup and keep its `gameId` and both `teamId`s.

```jsonc
// e.g. from the response
{ "gameId": "0022500741", "homeTeam": { "teamId": 1610612747, "teamTricode": "LAL" },
                          "awayTeam": { "teamId": 1610612738, "teamTricode": "BOS" } }
```

### 2. Pull the box score and find the top scorer

```jsonc
// tool: nba_boxscore
{ "gameId": "0022500741" }
```

Returns `{game:{homeTeam:{players:[{personId, name, statistics:{points, ...}}]}, awayTeam:{...}}}`.
Scan both teams' `players[]` for the highest `statistics.points`, and keep that
player's `personId` (their PlayerID) and `teamId`.

### 3. Pull that player's shot locations for the game

`shotchartdetail` needs `PlayerID` + `TeamID`; scope it to the one game with
`GameID` and the season. Everything else falls back to the operation's defaults
(`ContextMeasure: PTS`, all the empty filters), so you only set four fields:

```jsonc
// tool: nba_stats_call
{
  "operation": "shotchartdetail",
  "query_params": {
    "PlayerID": "2544",
    "TeamID": "1610612747",
    "GameID": "0022500741",
    "Season": "2025-26"
  }
}
```

Returns the classic column-oriented shape
`{resultSets:[{name:"Shot_Chart_Detail", headers:[...], rowSet:[[...]]}]}`. Zip
`headers` with each row in `rowSet`; the useful columns are `LOC_X`, `LOC_Y`
(court coordinates in tenths of a foot), `SHOT_DISTANCE`, `SHOT_MADE_FLAG`,
`SHOT_TYPE` and `ACTION_TYPE`.

### 4. (optional) Richer per-player stats from the v3 box score

```jsonc
// tool: nba_stats_call
{ "operation": "boxscoretraditionalv3", "query_params": { "GameID": "0022500741" } }
```

`boxscoretraditionalv3` returns the nested v3 shape
`{boxScoreTraditional:{homeTeam:{players:[...]}, awayTeam:{...}}}` — a fuller
stat line (minutes, FG splits, +/-, usage) than the CDN box score.

## Expected answer shape

> **Top scorer — LeBron James (LAL), 34 pts vs BOS**
>
> | Stat | Value |
> |---|---|
> | FG | 13 / 22 |
> | 3P | 4 / 9 |
> | Shot zones | 8 in the paint, 5 mid-range, 9 from three |
> | Best range | 4/9 from beyond the arc, mostly above the break |
>
> Shots clustered at the rim and the left corner three; only two attempts from
> the right mid-range.

(Exact numbers vary by game; the point is the flow — CDN scoreboard → CDN box
score → `nba_stats_call` for the spatial detail the CDN feed doesn't carry.)

## Other things to try with `nba_stats_call`

- `leaguestandingsv3` — current conference standings (`{Season: "2025-26"}`; 30 rows).
- `leaguedashplayerstats` — the season-long player leaderboard, sortable by any
  stat; switch `MeasureType` to `"Advanced"` for PER-style metrics.
- `playercareerstats` — per-season career totals for one `PlayerID`.
- `commonteamyears` / `franchisehistory` — resolve the 30 `teamId`s to names.
- `shotchartleaguewide` — league-average shot zones to normalise a player's chart.

Browse all 137 operations and their parameters in `nba://stats/operations`, and
the always-on `list_tools_by_capability` / `list_resources` meta-tools to discover
the rest.
