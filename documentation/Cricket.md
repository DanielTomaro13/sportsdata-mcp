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

1. `cricket_fixtures` → each fixture carries `id`, `competitionId`, `venueId`,
   `homeTeamId`, `awayTeamId`.
2. `cricket_scorecard?fixtureId=` → per-innings batting/bowling + a `players[]` lookup.
3. `cricket_players?playerIds=` → resolve those player ids to full profiles.
4. `cricket_standings?competitionId=` → that competition's ladder.

Every apiv2 response is wrapped `{<payload>, responseError}`.

## Core — group `cricket.core`

| Tool | Path | Capability |
|---|---|---|
| `cricket_fixtures` | `/fixtures?year=&isCompleted=&competitionId=` | `sport.fixtures_by_date` |
| `cricket_competitions` | `/competitions` | `sport.competitions_list` |
| `cricket_teams` | `/teams` | `ref.teams` |
| `cricket_players` | `/players?playerIds=` | `ref.players`, `stats.player_profile` |
| `cricket_standings` | `/standings?competitionId=` | `stats.ladder` |

`cricket_players` takes a **list** of ids (sent comma-separated). `cricket_standings`
returns an empty `standings` array for competitions that don't run a points table
(e.g. one-off tours / bilateral series).

## Match — group `cricket.match`

| Tool | Path | Capability |
|---|---|---|
| `cricket_scorecard` | `/views/scorecard?fixtureId=` | `sport.match_boxscore`, `stats.player_match` |
| `cricket_runs_graph` | `/views/graphs/runs?fixtureId=` | `stats.advanced_metrics` |
| `cricket_streams` | `/streams?fixtureId=` | `sport.live_video` |

`cricket_scorecard` carries `fixture.innings[]` with `batsmen` / `bowlers` /
`wickets` per innings. `cricket_runs_graph` is the run-progression series behind the
site's worm/manhattan graphs. `cricket_streams` is empty unless the match is live.

## Content — group `cricket.content`

| Tool | Path | Capability |
|---|---|---|
| `cricket_content` | `/{contentType}/EN?pageSize=&page=&tagNames=` | `content.video`, `content.news` |
| `cricket_playlist` | `/PLAYLIST/EN/{playlistId}` | `content.video` |

`cricket_content` lists Pulselive CMS items by type — **VIDEO** (highlights/replays),
**TEXT** (articles) or **AUDIO** — paginated via `pageInfo`. `cricket_playlist`
returns one curated collection (e.g. a match's highlights playlist).

## Cross-provider comparison

The cricket feeds reuse the shared capability tags, so they line up with the other
providers via `list_tools_by_capability`:

- **`ref.teams`** / **`ref.players`** → `cricket_teams` / `cricket_players` join the
  AFL / NBA / Data Golf catalogues.
- **`sport.fixtures_by_date`** → `cricket_fixtures` sits next to the ESPN / NBA / OpenF1
  schedules.
- **`stats.ladder`** → `cricket_standings` alongside the AFL ladder and OpenF1
  championship standings.
- **`sport.match_boxscore`** / **`stats.player_match`** → `cricket_scorecard` next to
  the NBA box score and other per-player match feeds.
- **`sport.competitions_list`**, **`sport.live_video`**, **`content.video`** /
  **`content.news`** → competitions, streams and CMS content compose with the
  bookmakers' and broadcasters' equivalents.

## Notes

- **No auth, public.** Both hosts respond without a key; `jsconfig=eccn:true` (apiv2)
  and `detail=STANDARD` (Pulselive) are config flags, not secrets.
- **Match detail is one call.** There is no per-fixture or per-player REST resource —
  use `cricket_scorecard?fixtureId=` for a match and `cricket_players?playerIds=` for
  a batch of players (the `views/*` paths only expose `scorecard` and `graphs/runs`).
- **Source.** These are the site's own XHR feeds, read directly.
