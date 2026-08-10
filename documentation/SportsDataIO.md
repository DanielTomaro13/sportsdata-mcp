# SportsDataIO (`sportsdataio`) — DFS salaries and projections

**9 tools · BYO key · shapes unverified**

NFL, NBA, MLB and NHL from [sportsdata.io](https://sportsdata.io). Host and refusal
probed live 2026-08-10.

## Keys are per sport

This is the trap. SportsDataIO issues a **separate key for each sport**, and a trial key
for one sport returns 401 on another. This spec reads one variable per sport rather than
pretending a single key works everywhere — set only the ones you actually hold:

```bash
export SPORTSDATAIO_NFL_KEY=...
export SPORTSDATAIO_NBA_KEY=...
export SPORTSDATAIO_MLB_KEY=...
export SPORTSDATAIO_NHL_KEY=...
```

The header is `Ocp-Apim-Subscription-Key` (the API sits behind Azure API Management).

## Why carry it when `mlb`, `nhl` and `nba` are official and keyless

For the two things the official feeds do not publish:

**DFS salaries.** `sportsdataio_nfl_dfs_slates` and `sportsdataio_nba_dfs_slates` give
you DraftKings, FanDuel and Yahoo slates with each player's salary and
`FantasyPointsPerDollar`. Nothing else in this catalogue has that.

**Projections.** `sportsdataio_nfl_projections` returns projected player game stats with
**per-operator scoring columns** — `FantasyPointsDraftKings` and `FantasyPointsFanDuel`
differ because the operators score differently. Use the column that matches the contest
you are entering.

Between them, that fills the gap between "what happened" (the official providers) and
"my league" (`espnfantasy`, `sleeper`).

## Tools

| Tool | Sport | What it gives you |
|---|---|---|
| `sportsdataio_nfl_teams` | NFL | Franchises, stadiums, coaches |
| `sportsdataio_nfl_scores` | NFL | Scores by season and week, with spread and total |
| `sportsdataio_nfl_dfs_slates` | NFL | **DFS slates and salaries** |
| `sportsdataio_nfl_projections` | NFL | **Projected player game stats** |
| `sportsdataio_nfl_injuries` | NFL | Weekly injury report |
| `sportsdataio_nba_games_by_date` | NBA | Games with the line |
| `sportsdataio_nba_dfs_slates` | NBA | **DFS slates and salaries** |
| `sportsdataio_mlb_games_by_date` | MLB | Games with probable pitchers and the line |
| `sportsdataio_nhl_games_by_date` | NHL | Games with the line |

## Conventions

**Fields are PascalCase** throughout — `HomeTeam`, `AwayTeamScore`, `PointSpread`.

**Season strings carry a type suffix**: `2023` is the regular season, `2023PRE` is
preseason, `2023POST` is the playoffs. A bare year does **not** include the postseason.
The `SeasonType` field in responses uses `1` = pre, `2` = regular, `3` = post.

## When to use something else

| For | Use instead |
|---|---|
| MLB box scores, play-by-play | `mlb` — official, keyless, deeper |
| NHL box scores, play-by-play | `nhl` — official, keyless |
| NBA play-by-play, shot charts | `nba` — official, keyless |
| Your own fantasy league | `espnfantasy`, `sleeper` |

Come here for salaries, projections and the line.
