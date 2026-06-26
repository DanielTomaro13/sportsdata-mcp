# NBL — `nbl.com.au` (Australian National Basketball League)

Australia's National Basketball League, read directly from the site's own data
API. **Genius Sports** powers the underlying stats; nbl.com.au fronts them through
a Redis-cached proxy it calls **"rosetta"**. **No token / API key** — but the proxy
is **referer-gated**.

Probed live 2026-06-26. Provider id `nbl`, group `nbl.basketball` (14 tools).

> `nbl_stat_leaders` accepts a `sort` (e.g. `-points_average` for top scorers).
> `nbl_news` is the one feed that returns a **raw array** (not the `{type,count,data}`
> envelope). Per-match play-by-play / shot-charts are served by Genius's own widget
> library (keyed by the fixture UUID in `external_id`) and aren't part of this API;
> per-match player box scores come from `nbl_player_boxscores`.

## How it works

Every feed is:

```
https://prod.rosetta.nbl.com.au/get/{route}
```

The proxy **403s with `{"error":"Access Denied","code":"MISSING_API_KEY"}`** unless
the request carries an **`Origin: https://nbl.com.au`** and **`Referer:
https://nbl.com.au/`** — the message is misleading; it's a referer-gate, not a key.
Those headers (plus the `Sec-Fetch-*` CORS trio) are baked into the spec, so the
feeds return JSON anonymously.

Every response is **enveloped**:

```json
{ "type": "...", "fetched": 1782446463, "ttlRemaining": 300, "count": 73, "source": "redis", "data": [ ... ] }
```

The payload you want is always under `data`.

> The site also exposes a Genius **widget** proxy (`/api_cache/nbl/genius?route=…`,
> for play-by-play / shot-chart widgets, keyed by a fixture UUID) and a Directus
> **CMS** (`/api_cache/nbl/cms`, its own Bearer). Those are out of scope — the
> rosetta stats API below is the data surface.

## Season scoping

Most routes take **`year` = the season START year**: `2025` = **NBL26** (the
2025-26 season, current), `2026` = **NBL27**. `seasonType` ∈ `regular` | `all` |
`in_season` | `preseason` | `finals`.

A few stats routes instead need the season **UUID** (`seasonId`) — get it from
`nbl_seasons` (`data[].id`; pick the `season_type=regular` row for the main season).
Each season also carries the Genius `external_id`.

The NBL runs **Sep–Mar**, so in the deep off-season the `current` / `next` feeds can
come back empty — the call still resolves.

## Tools — group `nbl.basketball`

| Tool | Route (`/get/…`) | Capability |
|---|---|---|
| `nbl_seasons` | `nbl/seasons` | `ref.seasons` |
| `nbl_season_current` | `nbl/seasons/current?limit=` | `ref.seasons` |
| `nbl_teams` | `nbl/teams` | `ref.teams` |
| `nbl_ladder` | `nbl/standings/{year}/{seasonType}` | `stats.ladder` |
| `nbl_schedule` | `nbl/matches/in/season/{year}/{seasonType}` | `sport.fixtures_by_date`, `sport.match_score` |
| `nbl_match_outcomes` | `match/outcomes/for/nbl/teams/in/season/{year}/{seasonType}` | `sport.match_score`, `stats.head_to_head` |
| `nbl_next_matches` | `next/matches/for/teams/in/nbl/{year}` | `sport.fixtures_by_date` |
| `nbl_players` | `nbl/players/in/season/{year}` | `ref.players` |
| `nbl_team_roster` | `nbl/players/for/team/{teamId}/in/season/{year}` | `ref.players` |
| `nbl_player_stats` | `nbl/statistics/for/player/{playerId}` | `stats.player_season`, `stats.player_profile` |
| `nbl_player_boxscores` | `nbl/player_boxscores/for/{playerId}/in/season/{year}/{seasonType}` | `stats.player_game_log` |
| `nbl_team_stats` | `nbl/team/stats/for/season/{year}/{seasonType}` | `stats.team_season` |
| `nbl_stat_leaders` | `nbl/stats/leaders/for/season/id/{seasonId}?limit=&sort=` | `stats.leaders_season` |
| `nbl_news` | `nbl/news?limit=` | `content.news` |

### Typical flow

1. `nbl_seasons` → find the current season (latest `year`, `season_type=regular`);
   keep its `id` (UUID) and `year`.
2. `nbl_ladder` / `nbl_schedule` / `nbl_team_stats` with that `year`.
3. `nbl_players` → player `id`s → `nbl_player_stats` (season averages) or
   `nbl_player_boxscores` (game log).
4. `nbl_stat_leaders` with the season **UUID**.

## Shapes

- **Ladder** (`data[]`): `{position, played, won, lost, points_percentage,
  win_percentage, points_for, points_against, last_5, streak, team}` — 10 clubs.
- **Match** (`data[]`): `{id, external_id, start_time, round, match_status,
  home_score, away_score, attendance, match_slug, play_by_play, home_team{…},
  away_team{…}}`. Each team object carries `name`, `team_code`, `team_logo` and
  brand colours.
- **Player** (`data[]`): `{jersey_number, playing_position, player:{id,
  first_name, last_name}, team:{id, name, team_code}, season}`. Names are **split**
  (`first_name` / `last_name`), not a single `name`.
- **Player stats**: points/rebounds/assists/blocks/steals/turnovers totals and
  `_average`s, shooting splits (`field_goals_*`, `three_pointers_*`,
  `free_throws_*` made / attempted / percentage), fouls, minutes.

## Cross-provider comparison

NBL slots in next to the other league feeds via the shared capabilities:

- **`stats.ladder`** → `nbl_ladder` alongside the football standings (LaLiga,
  Premier League, Serie A) and AFL ladders.
- **`sport.fixtures_by_date`** / **`sport.match_score`** → `nbl_schedule` next to
  the bookmaker fixture lists and the SuperCoach `nbl` fantasy feed (a different
  source — News Corp fantasy — for the same league).
- **`stats.player_season`** / **`stats.leaders_season`** → official Genius-sourced
  box-score stats per player.

## Quick test

```bash
H=(-H 'Origin: https://nbl.com.au' -H 'Referer: https://nbl.com.au/' -H 'User-Agent: Mozilla/5.0')
# current ladder
curl -s "${H[@]}" "https://prod.rosetta.nbl.com.au/get/nbl/standings/2025/regular" \
  | jq '.data[] | {pos: .position, team: .team.name, w: .won, l: .lost}'
# seasons (find the season UUID for stat leaders)
curl -s "${H[@]}" "https://prod.rosetta.nbl.com.au/get/nbl/seasons" \
  | jq '.data[] | select(.season_type=="regular") | {name, year, id}' | head
```
