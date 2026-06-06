# MLB API Documentation

Reference for the official **MLB Stats API** (`statsapi.mlb.com/api`) — the same
public, no-auth JSON API that the
[MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI/wiki) Python library wraps.
We read it directly. Verified against live traffic (probed 2026-06-05).

> **No auth.** Every endpoint is public. Most live under `/api/v1`; the complete
> game **feed/live** lives under `/api/v1.1` (modelled via a second base URL).

## Id model

`sportId=1` is Major League Baseball. Discover ids, then drill in:

| To get… | Call | Yields |
|---|---|---|
| team ids | `mlb_teams?sportId=1` | `teamId` |
| game ids | `mlb_schedule?sportId=1&date=` | `gamePk` |
| player ids | `mlb_team_roster` / `mlb_player_search` | `personId` |
| venue ids | a team's `venue` / `mlb_venues` | `venueId` |

> **`hydrate` is the power feature.** Many endpoints take a comma-separated `hydrate`
> string to embed related objects in one call — e.g.
> `mlb_schedule(hydrate="team,linescore,probablePitcher,decisions")`,
> `mlb_player(hydrate="currentTeam,stats(type=season)")`,
> `mlb_team_roster(hydrate="person(stats(type=season))")`.

## Reference — group `mlb.reference`

| Tool | Path | Capability |
|---|---|---|
| `mlb_sports` | `/sports` | — (the sportId lookup) |
| `mlb_leagues` | `/league?sportId=1` | `sport.competitions_list` |
| `mlb_divisions` | `/divisions` | — |
| `mlb_conferences` | `/conferences` | — |
| `mlb_teams` | `/teams?sportId=1` | `ref.teams` |
| `mlb_team` | `/teams/{teamId}` | `ref.teams` |
| `mlb_teams_affiliates` | `/teams/affiliates?teamIds=` | `ref.teams` |
| `mlb_teams_history` | `/teams/history?teamIds=` | — |
| `mlb_team_uniforms` | `/uniforms/team?teamIds=` | — |
| `mlb_team_roster` | `/teams/{teamId}/roster` | `ref.players` |
| `mlb_team_alumni` | `/teams/{teamId}/alumni?season=` | `ref.players` |
| `mlb_team_coaches` | `/teams/{teamId}/coaches` | `ref.coaches` |
| `mlb_team_personnel` | `/teams/{teamId}/personnel` | — |
| `mlb_player` | `/people/{personId}` | `ref.players`, `stats.player_profile` |
| `mlb_people` | `/people?personIds=` | `ref.players` |
| `mlb_player_search` | `/people/search?names=` | `ref.players` |
| `mlb_sports_players` | `/sports/{sportId}/players?season=` | `ref.players` |
| `mlb_venues` | `/venues?venueIds=` | `ref.venues` |
| `mlb_seasons` | `/seasons?sportId=1` | `ref.seasons` |
| `mlb_season` | `/seasons/{seasonId}` | `ref.seasons` |

## Schedule — group `mlb.schedule`

| Tool | Path | Capability |
|---|---|---|
| `mlb_schedule` | `/schedule?sportId=1&date=` (or `startDate`/`endDate`, `teamId`) | `sport.fixtures_by_date` |
| `mlb_schedule_postseason` | `/schedule/postseason` | `sport.fixtures_by_date` |
| `mlb_schedule_postseason_series` | `/schedule/postseason/series` | — |
| `mlb_schedule_postseason_tunein` | `/schedule/postseason/tuneIn` | — |
| `mlb_schedule_tied` | `/schedule/games/tied?season=` | — |

## Game — group `mlb.game`

| Tool | Path | Capability |
|---|---|---|
| `mlb_boxscore` | `/game/{gamePk}/boxscore` | `sport.match_boxscore`, `stats.player_match` |
| `mlb_linescore` | `/game/{gamePk}/linescore` | `sport.match_score` |
| `mlb_playbyplay` | `/game/{gamePk}/playByPlay` | `stats.play_by_play` |
| `mlb_live_feed` | `/api/v1.1/game/{gamePk}/feed/live` | `sport.match_detail` |
| `mlb_game_win_probability` | `/game/{gamePk}/winProbability` | `stats.win_probability` |
| `mlb_game_context_metrics` | `/game/{gamePk}/contextMetrics` | `stats.advanced_metrics` |
| `mlb_game_content` | `/game/{gamePk}/content` | `content.video` |
| `mlb_player_game_stats` | `/people/{personId}/stats/game/{gamePk}` | `stats.player_match` |
| `mlb_game_changes` | `/game/changes?updatedSince=` | — |
| `mlb_game_uniforms` | `/uniforms/game?gamePks=` | — |

`mlb_live_feed` is the firehose: `gameData` (teams, players, venue, weather,
probables) + `liveData` (full plays, linescore, boxscore, decisions). It's large —
prefer the focused boxscore/linescore/playByPlay tools unless you need everything.
The boxscore/linescore/playByPlay/feed/winProbability tools accept a `timecode`
(`YYYYMMDD_HHMMSS`) for point-in-time replay.

## Stats — group `mlb.stats`

| Tool | Path | Capability |
|---|---|---|
| `mlb_standings` | `/standings?leagueId=103,104` | `stats.ladder` |
| `mlb_stats` | `/stats?stats=season&group=hitting` | `stats.player_season` |
| `mlb_player_stats` | `/people/{personId}/stats?stats=&group=` | `stats.player_season`, `stats.player_career`, `stats.player_game_log` |
| `mlb_leaders` | `/stats/leaders?leaderCategories=` | `stats.leaders_season` |
| `mlb_team_stats` | `/teams/{teamId}/stats?season=&group=` | `stats.team_season` |
| `mlb_teams_stats` | `/teams/stats?season=&group=` | `stats.team_season` |
| `mlb_team_leaders` | `/teams/{teamId}/leaders?leaderCategories=` | `stats.leaders_season` |
| `mlb_game_pace` | `/gamePace?season=` | — |
| `mlb_high_low` | `/highLow/{orgType}?sortStat=&season=` | — |

`leagueId` 103 = AL, 104 = NL. `mlb_player_stats` switches between season / career /
yearByYear / gameLog via the `stats` param, and hitting / pitching / fielding via
`group`. `mlb_leaders` categories include `homeRuns`, `battingAverage`,
`runsBattedIn`, `era`, `strikeouts`, `wins`, `saves`, …

## Extra — group `mlb.extra`

| Tool | Path | Capability |
|---|---|---|
| `mlb_draft` | `/draft/{year}` | `sport.draft` |
| `mlb_draft_prospects` | `/draft/prospects/{year}` | — |
| `mlb_awards` | `/awards/{awardId}/recipients` | — |
| `mlb_attendance` | `/attendance?teamId=&leagueId=` | — |
| `mlb_transactions` | `/transactions?teamId=&startDate=&endDate=` | `sport.transactions` |
| `mlb_free_agents` | `/people/freeAgents?season=` | — |
| `mlb_jobs` | `/jobs?jobType=` | — |
| `mlb_umpires` | `/jobs/umpires` | — |
| `mlb_datacasters` | `/jobs/datacasters` | — |
| `mlb_official_scorers` | `/jobs/officialScorers` | — |
| `mlb_home_run_derby` | `/homeRunDerby/{gamePk}` | — |
| `mlb_allstar_ballot` | `/league/{leagueId}/allStarBallot?season=` | — |
| `mlb_allstar_writeins` | `/league/{leagueId}/allStarWriteIns?season=` | — |
| `mlb_allstar_final_vote` | `/league/{leagueId}/allStarFinalVote?season=` | — |

Common `awardId`s: `MLBHOF` (Hall of Fame), `ALMVP`/`NLMVP`, `ALCY`/`NLCY` (Cy Young),
`ALROY`/`NLROY` (Rookie of the Year). `mlb_jobs` `jobType` codes: `UMPR`, `SCORER`,
`DATACASTER`, `BROADCASTER`, … (see `mlb_meta(type="jobTypes")`).

## Meta — group `mlb.meta`

| Tool | Path | Capability |
|---|---|---|
| `mlb_meta` | `/{type}` | — |

`mlb_meta` is one tool over the API's `/{type}` lookup endpoint — it returns the valid
values for parameters used by the other tools. `type` is one of: `awards`,
`baseballStats`, `eventTypes`, `gameStatus`, `gameTypes`, `hitTrajectories`,
`jobTypes`, `languages`, `leagueLeaderTypes`, `logicalEvents`, `metrics`, `pitchCodes`,
`pitchTypes`, `platforms`, `positions`, `reviewReasons`, `rosterTypes`,
`scheduleEventTypes`, `situationCodes`, `sky`, `standingsTypes`, `statGroups`,
`statTypes`, `windDirection`.

> **Not modelled:** a handful of MLB Stats API endpoints require MLB-internal auth
> (e.g. `/jobs/umpires/games/{umpireId}` → 401) or are incremental diff/timestamp
> helpers (`feed/live/diffPatch`, `feed/color`, `feed/live/timestamps`). Those are
> deliberately left out; everything in the tables above is public and verified.

## Cross-provider comparison

The MLB feeds reuse the shared capability tags, so they line up with the other
providers via `list_tools_by_capability`:

- **`ref.teams`** / **`ref.players`** / **`ref.venues`** / **`ref.seasons`** →
  `mlb_teams` / `mlb_team_roster` + `mlb_player(_search)` / `mlb_venues` /
  `mlb_seasons` join the AFL / NBA / cricket / Data Golf catalogues.
- **`sport.fixtures_by_date`** → `mlb_schedule` next to the ESPN / NBA / OpenF1 /
  cricket schedules.
- **`sport.match_boxscore`** / **`stats.player_match`** → `mlb_boxscore` alongside the
  NBA box score and cricket scorecard.
- **`sport.match_score`** / **`stats.play_by_play`** / **`sport.match_detail`** →
  linescore, play-by-play and the live feed compose with ESPN / NBA equivalents.
- **`stats.ladder`** → `mlb_standings` with the AFL ladder, cricket + OpenF1 standings.
- **`stats.leaders_season`** → `mlb_leaders` / `mlb_team_leaders` alongside AFL season leaders.
- **`stats.team_season`** → `mlb_team_stats` / `mlb_teams_stats` for team aggregates.
- **`ref.coaches`**, **`sport.transactions`**, **`stats.win_probability`** →
  `mlb_team_coaches`, `mlb_transactions` and `mlb_game_win_probability` each make their
  tag multi-provider (all three previously ESPN-only).
- **`sport.draft`** → `mlb_draft` joins ESPN on the draft tag.

## Notes

- **Source.** The official MLB Stats API, read directly (not the `MLB-StatsAPI`
  Python package). The `copyright` field on every response is MLB's standard notice.
- **v1 vs v1.1.** Only `feed/live` is v1.1; everything else is v1. Both are modelled
  as base URLs so the tools are transparent about it.
- **Seasons.** Stat/standings/schedule tools default to the current season when
  `season` is omitted; pass an explicit year for historical data (1876→).
