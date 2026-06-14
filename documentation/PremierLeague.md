# Premier League — Reverse-Engineered API Documentation

Reference for the **Premier League** read surface as modelled by the packaged
provider spec (`src/sportsdata_mcp/specs/premierleague.yaml`). These are the
private JSON APIs that power **premierleague.com**, read directly.

> **Unofficial / undocumented.** No published contract; routes can change without
> notice. Every endpoint below was re-probed live and confirmed `200` on
> **2026-06-15** (from country `AU`), except `pl_team_next_fixture` which `404`s
> when no fixture is scheduled (off-season at probe time). The underlying data is
> **Opta** (Stats Perform), so stat keys (`expectedGoals`, `goalAssists`,
> `possWonAtt3rd`, …) are Opta's standard vocabulary.

## Hosts

| Host | base_urls key | Role | Auth |
|---|---|---|---|
| `sdp-prem-prod.premier-league-prod.pulselive.com` | `default` | **SDP** ("Sport Data Platform") — core stats/match/standings/player API. *The main one.* | ❌ none |
| `api.premierleague.com` | `content` | Editorial content, broadcasting schedules, personalisation feeds | ❌ none |
| `resources.premierleague.com` | `resources` | Static config blobs (current gameweek, club metadata) | ❌ none |

**No auth, no key, no cookies.** SDP rate-limits **300 req / 60 s per IP** (~5 rps)
and echoes `x-ratelimit-remaining`; the provider throttles to **4 rps** (one bucket
across all three hosts) and retries `429/5xx`. The gateway is allow-listed: a
non-enabled route returns `400 application/problem+json`, a valid route with a
missing entity returns `404` `"Could not find requested entity"`.

## Conventions & ids

- **Competition `8` = Premier League** (others exist: `1` = FA Cup, `10` = Championship).
- **Season id = the starting year.** `2025` = the **2025/26** season (`2026` = 2026/27).
  Use **2025** for current live data.
- **Team ids** are Opta-style and stable: Liverpool `14`, Man City `43`, Arsenal `3`,
  Aston Villa `7`, Newcastle `4`, Brighton `36`, etc. (full list via `pl_clubs_metadata`).
- **Player ids** are stable integers (Haaland `223094`); **match ids** are 7-digit (`2561895`).
- **Pagination:** SDP list responses wrap as `{pagination, data:[…]}`. Tools expose
  `limit` (→ `_limit`) and `next_cursor` (→ `_next`, an opaque cursor from
  `pagination._next`).
- **Sorting:** `sort` (→ `_sort`) takes `field:dir`, e.g. `goals:desc`. Both snake_case
  (`goal_assists`) and camelCase (`goalAssists`) keys are accepted.

> The SDP wire names (`_limit`, `_sort`, `_next`, and the matches `kickoff>` / `kickoff<`
> range operators) aren't valid tool-parameter names, so the tools take clean names
> (`limit`, `sort`, `next_cursor`, `kickoff_after`, `kickoff_before`) mapped to the wire
> names via the spec's `api_name`.

## Discovery flow

```
pl_teams(cid=8)                          →  team id (tid)
pl_matches(competition=8, season=2025)   →  match id  →  pl_match / events / lineups / stats / officials / commentary
pl_players(cid=8, sid=2025)              →  player id →  pl_player / pl_player_season_stats
pl_standings(cid=8, sid=2025)            →  the league table
```

## Core — group `premierleague.core`

| Tool | Path | Capability |
|---|---|---|
| `pl_competitions` | `/api/v1/competitions` | `sport.competitions_list` |
| `pl_competition` | `/api/v1/competitions/{cid}` | — |
| `pl_structure` | `/api/v1/competitions/{cid}/seasons/{sid}/structure` | — |
| `pl_awards` | `/api/v1/competitions/{cid}/seasons/{sid}/awards` | — (POTM/MOTM) |
| `pl_standings` | `/api/v5/competitions/{cid}/seasons/{sid}/standings?live=` | `stats.ladder` |
| `pl_current_gameweek` | `resources …/config/current-gameweek.json` | — |
| `pl_country` | `…/country` | — (geo echo) |

## Teams — group `premierleague.teams`

| Tool | Path | Capability |
|---|---|---|
| `pl_teams` | `/api/v1/competitions/{cid}/teams` | `ref.teams` |
| `pl_team` | `/api/v1/competitions/{cid}/teams/{tid}` | `ref.teams` |
| `pl_season_teams` | `/api/v1/competitions/{cid}/seasons/{sid}/teams` | `ref.teams` |
| `pl_teams_by_id` | `/api/v2/teams-by-id?id=` | `ref.teams` |
| `pl_squad` | `/api/v2/competitions/{cid}/seasons/{sid}/teams/{tid}/squad` | `ref.players` |
| `pl_team_form` | `/api/v1/competitions/{cid}/seasons/{sid}/teams/{tid}/form` | `stats.team_game_log` |
| `pl_teamform` | `/api/v1/competitions/{cid}/seasons/{sid}/teamform` | `stats.team_game_log` |
| `pl_team_stats` | `/api/v1/competitions/{cid}/teams/{tid}/stats` | `stats.team_season` |
| `pl_team_next_fixture` | `/api/v1/competitions/{cid}/seasons/{sid}/teams/{tid}/nextfixture` | `sport.match_detail` (404 when none scheduled) |
| `pl_clubs_metadata` | `resources …/config/clubs-metadata.json` | — |

## Matches — group `premierleague.matches`

| Tool | Path | Capability |
|---|---|---|
| `pl_matches` | `/api/v2/matches?competition=&season=&matchweek=&team=&period=` | `sport.fixtures_by_date` |
| `pl_matchweek_matches` | `/api/v1/competitions/{cid}/seasons/{sid}/matchweeks/{mw}/matches` | `sport.fixtures_by_date` |
| `pl_match` | `/api/v2/matches/{id}` | `sport.match_detail` |
| `pl_match_events` | `/api/v1/matches/{id}/events` | `stats.play_by_play` |
| `pl_match_lineups` | `/api/v3/matches/{id}/lineups` | — |
| `pl_match_stats` | `/api/v3/matches/{id}/stats` | `sport.match_boxscore`, `stats.team_match` |
| `pl_match_officials` | `/api/v1/matches/{id}/officials` | — |
| `pl_match_commentary` | `/api/v1/matches/{id}/commentary` | `sport.commentary` |

`pl_matches` also accepts a kickoff date range: `kickoff_after` / `kickoff_before`
(`YYYY-MM-DD`, mapped to the API's `kickoff>` / `kickoff<`), and `period` ∈
`PreMatch` / `Live` / `FullTime`. `pl_match_stats` returns a 2-element array (Home/Away)
of ~200 Opta metrics each.

## Players — group `premierleague.players`

| Tool | Path | Capability |
|---|---|---|
| `pl_players` | `/api/v1/competitions/{cid}/seasons/{sid}/players` | `ref.players` |
| `pl_player_basic` | `/api/v1/players/{pid}/basic` | `stats.player_profile` |
| `pl_player` | `/api/v1/players/{pid}` | `stats.player_career` |
| `pl_players_by_id` | `/api/v2/players-by-id?id=` | `ref.players` |
| `pl_player_comp_stats` | `/api/v1/competitions/{cid}/players/{pid}/stats` | `stats.player_career` |
| `pl_player_season_stats` | `/api/v1/competitions/{cid}/seasons/{sid}/players/{pid}/stats` | `stats.player_season` |
| `pl_player_info` | `/api/v1/competitions/{cid}/seasons/{sid}/playerinfo/{pid}` | `stats.player_profile` |
| `pl_metadata` | `/api/v1/metadata/{type}/{mid}` | — (external/fantasy links) |

`pl_player` returns a top-level array — one entry per club/season spell.

## Stats — group `premierleague.stats`

| Tool | Path | Capability |
|---|---|---|
| `pl_player_leaderboard` | `/api/v3/competitions/{cid}/seasons/{sid}/players/stats/leaderboard?sort=&position=` | `stats.leaders_season` |
| `pl_team_leaderboard` | `/api/v2/competitions/{cid}/teams/stats/leaderboard?season=&sort=` | `stats.leaders_season` |

Sort by any Opta metric: players — `goals`, `goal_assists`, `clean_sheets`,
`total_passes`, `expectedGoals`, …; teams — `tackles_won`, `blocks`,
`possessionPercentage`, `passingAccuracy`, … **Note** the team leaderboard takes
`season` as a **query** param, not a path segment.

## Content / broadcasting — group `premierleague.content`

| Tool | Path | Capability |
|---|---|---|
| `pl_content` | `/content/premierleague/{lang}?contentTypes=&references=&tagExpression=` | `content.news` |
| `pl_content_item` | `/content/premierleague/{type}/{lang}/{contentId}` | — |
| `pl_news_latest` | `/personalisation/content/news/latest/smart_order` | `content.news` |
| `pl_news_popular` | `/personalisation/content/news/popular/smart_order?recency=` | `content.news` |
| `pl_video_latest` | `/personalisation/content/video/latest/smart_order` | `content.video` |
| `pl_video_popular` | `/personalisation/content/video/popular/smart_order?recency=` | `content.video` |
| `pl_broadcasting_events` | `/broadcasting/events?fromDate=&toDate=` | `broadcast.schedule` |
| `pl_broadcast_match_events` | `/broadcasting/match-events?sportDataId=` | `broadcast.schedule` |

`pl_content` links content to an entity via `references=SDP_FOOTBALL_MATCH:{id}`
(e.g. match highlights), `SDP_FOOTBALL_PLAYER:{pid}` or `SDP_FOOTBALL_TEAM:{tid}`.

## Not modelled

- **Static binary assets** (`resources.premierleague.com/.../badges/{id}.svg`,
  player headshots `.png`, sponsor logos) — not JSON; fetch by URL directly.
- **Phase-scoped matches** (`…/phases/{p}/matches`) — `pl_matches?matchweek=` and
  `pl_matchweek_matches` cover the same data.
- **Routes the gateway does not allow-list** (`…/seasons` listing, `…/phases`,
  `…/matchweeks/current`) — return `400 "not enabled"`. The valid season ids are
  embedded in each team's `seasons[]` array (`pl_teams`).
- Third-party SDKs the site also calls (video/ads/analytics) — not PL data.

## Legal

premierleague.com's terms restrict automated/commercial data use and
redistribution. This models how the public site works for read access; for
production/commercial use obtain a proper data licence (the underlying provider
is **Opta / Stats Perform**). Respect the rate limit and cache aggressively.

## Cross-provider comparison

EPL reuses the shared capability tags, so it composes with the other league/data
providers via `list_tools_by_capability`:

- **`stats.ladder`** → `pl_standings` next to AFL/NRL ladders and MLB standings.
- **`sport.fixtures_by_date`** → `pl_matches` alongside the MLB / ESPN / cricket schedules.
- **`stats.player_season`** / **`stats.leaders_season`** → `pl_player_season_stats` /
  `pl_player_leaderboard` next to MLB / NBA / AFL stat leaders.
- **`sport.commentary`** → `pl_match_commentary` alongside Sportsbet's commentary feed.
- Sports prediction/odds: a fixture's teams also line up with bookmaker
  `sport.event_markets` and the Kalshi/Polymarket `prediction.*` soccer markets.
