# Cricket Australia API Documentation

Reference for the data feeds behind [cricket.com.au](https://www.cricket.com.au/) —
the official Cricket Australia site. Two public hosts, **no auth**. Verified against
live traffic (probed 2026-06-05).

> **`jsconfig=eccn:true` matters.** The `apiv2.cricket.com.au/web` endpoints only
> return the documented **camelCase** envelope (e.g. the `fixture` object) when called
> with `jsconfig=eccn:true`. Drop it and the response shape changes. Every apiv2 tool
> carries it as a default param, so you normally never set it yourself.

## Hosts

| Host | Base | Used by |
|---|---|---|
| apiv2 | `https://apiv2.cricket.com.au/web` | fixtures, competitions, teams, players, standings, scorecard, run graph, streams |
| Pulselive CMS | `https://api.cricket-australia.pulselive.com/content/cricket-australia` | video / text / audio content + playlists |

## Id model

1. `cricketaustralia_fixtures` → each fixture carries `id`, `competitionId`, `venueId`,
   `homeTeamId`, `awayTeamId`.
2. `cricketaustralia_scorecard?fixtureId=` → per-innings batting/bowling + a `players[]` lookup.
3. `cricketaustralia_players?playerIds=` → resolve those player ids to full profiles.
4. `cricketaustralia_standings?competitionId=` → that competition's ladder.

Every apiv2 response is wrapped `{<payload>, responseError}`.

## Core — group `cricketaustralia.core`

| Tool | Path | Capability |
|---|---|---|
| `cricketaustralia_fixtures` | `/fixtures?year=&isCompleted=&competitionId=` | `sport.fixtures_by_date` |
| `cricketaustralia_competitions` | `/competitions` | `sport.competitions_list` |
| `cricketaustralia_tours` | `/tours` | `sport.competitions_list` |
| `cricketaustralia_teams` | `/teams` | `ref.teams` |
| `cricketaustralia_players` | `/players?playerIds=` | `ref.players`, `stats.player_profile` |
| `cricketaustralia_venue` | `/venue?venueId=` | `ref.venues` |
| `cricketaustralia_standings` | `/standings?competitionId=` | `stats.ladder` |

`cricketaustralia_players` takes a **list** of ids (sent comma-separated). `cricketaustralia_venue`
resolves one venue id per call (get ids from a fixture's `venueId`; there is no venue
list endpoint). `cricketaustralia_tours` is the series view behind the site nav — each tour
carries `isUpComing` / `isInProgress` / `isCompleted` and its nested `competitions[]`.
`cricketaustralia_standings` returns an empty `standings` array for competitions that don't run
a points table (e.g. one-off tours / bilateral series).

## Match — group `cricketaustralia.match`

| Tool | Path | Capability |
|---|---|---|
| `cricketaustralia_scorecard` | `/views/scorecard?fixtureId=` | `sport.match_boxscore`, `stats.player_match` |
| `cricketaustralia_runs_graph` | `/views/graphs/runs?fixtureId=` | `stats.advanced_metrics` |
| `cricketaustralia_streams` | `/streams?fixtureId=` | `sport.live_video` |

`cricketaustralia_scorecard` carries `fixture.innings[]` with `batsmen` / `bowlers` /
`wickets` per innings. `cricketaustralia_runs_graph` is the run-progression series behind the
site's worm/manhattan graphs. `cricketaustralia_streams` is empty unless the match is live.

## Content — group `cricketaustralia.content`

| Tool | Path | Capability |
|---|---|---|
| `cricketaustralia_content` | `/{contentType}/EN?pageSize=&page=&tagNames=` | `content.video`, `content.news` |
| `cricketaustralia_playlist` | `/PLAYLIST/EN/{playlistId}` | `content.video` |

`cricketaustralia_content` lists Pulselive CMS items by type — **VIDEO** (highlights/replays),
**TEXT** (articles), **AUDIO**, or **PLAYLIST** (curated collections) — paginated via
`pageInfo`. `cricketaustralia_playlist` returns one curated collection by id (e.g. a match's
highlights playlist).

## Cross-provider comparison

The cricket feeds reuse the shared capability tags, so they line up with the other
providers via `list_tools_by_capability`:

- **`ref.teams`** / **`ref.players`** / **`ref.venues`** → `cricketaustralia_teams` /
  `cricketaustralia_players` / `cricketaustralia_venue` join the AFL / NBA / Data Golf catalogues.
- **`sport.fixtures_by_date`** → `cricketaustralia_fixtures` sits next to the ESPN / NBA / OpenF1
  schedules.
- **`stats.ladder`** → `cricketaustralia_standings` alongside the AFL ladder and OpenF1
  championship standings.
- **`sport.match_boxscore`** / **`stats.player_match`** → `cricketaustralia_scorecard` next to
  the NBA box score and other per-player match feeds.
- **`sport.competitions_list`**, **`sport.live_video`**, **`content.video`** /
  **`content.news`** → competitions, streams and CMS content compose with the
  bookmakers' and broadcasters' equivalents.

## Notes

- **No auth, public.** Both hosts respond without a key; `jsconfig=eccn:true` (apiv2)
  and `detail=STANDARD` (Pulselive) are config flags, not secrets.
- **Match detail is one call.** There is no per-fixture or per-player REST resource —
  use `cricketaustralia_scorecard?fixtureId=` for a match and `cricketaustralia_players?playerIds=` for
  a batch of players (the `views/*` paths only expose `scorecard` and `graphs/runs`).
- **Source.** These are the site's own XHR feeds, read directly.
