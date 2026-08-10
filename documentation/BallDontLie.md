# BallDontLie (`balldontlie`) — NBA, NFL, MLB, EPL

**10 tools · BYO key · shapes unverified**

One small consistent shape across four leagues, from
[balldontlie.io](https://balldontlie.io).

## It used to be keyless. It is not any more.

Older tutorials, blog posts and Stack Overflow answers call
`api.balldontlie.io/v1/players` with no credentials at all. Those examples now return
`401 Unauthorized` — verified live 2026-08-10 on every sport path. A free key still
exists; the change is that you must register for one.

```bash
export BALLDONTLIE_API_KEY=your_key_here
```

Free tier: **5 requests per minute**. The provider is throttled accordingly here, so
expect calls to pace themselves rather than fail.

## Two API details that cause most of the errors

**Authorization takes the bare key** — `Authorization: <key>`, with **no `Bearer `
prefix**. Nearly every other API in this catalogue wants the prefix, so adding it out of
habit is the usual failure.

**Pagination is cursor-based.** Responses carry `meta.next_cursor`; you pass it back as
`cursor`. There are no page numbers, and asking for `page=2` does nothing.

## Tools

| Tool | League | What it gives you |
|---|---|---|
| `balldontlie_nba_teams` | NBA | All 30 franchises with conference and division |
| `balldontlie_nba_players` | NBA | Players, searchable by name |
| `balldontlie_nba_games` | NBA | Games by date, season or team |
| `balldontlie_nba_stats` | NBA | Per-player, per-game box-score lines |
| `balldontlie_nba_season_averages` | NBA | Season averages for specific players |
| `balldontlie_nba_standings` | NBA | Standings for a season |
| `balldontlie_nfl_games` | NFL | Games by season, week or team |
| `balldontlie_mlb_games` | MLB | Games by date, season or team |
| `balldontlie_epl_teams` | EPL | Clubs for a season |
| `balldontlie_epl_games` | EPL | Fixtures and results |

## The shape is not uniform across sports

Worth knowing before you write a helper that handles "a game":

- NBA and NFL games call the away side **`visitor_team`**
- MLB games call it **`away_team`**
- `stats.min` is a **`"MM:SS"` string**, not a number

## Why use it at all

Convenience, not depth. For any single league, the official keyless provider here is
better:

| For | Use instead |
|---|---|
| NBA | `nba` — official, play-by-play, keyless |
| MLB | `mlb` — official Stats API, keyless, far deeper |
| EPL | `premierleague` — official, keyless |
| NFL | `espn` or `sportsdataio` |

BallDontLie earns its place when you want **one shape across four leagues** — a
cross-sport question is much easier to write against it than against four different
official APIs.

## Working within 5 requests a minute

The free tier is tight enough to shape how you use it:

- Filter server-side. `balldontlie_nba_games` accepts `dates`, `seasons`, `team_ids` and
  `postseason` — every filter you apply is a page you do not have to fetch.
- Raise `per_page` to 100 rather than paging at the default 25.
- Let the response cache serve repeats; identical calls inside the TTL cost nothing.
- `balldontlie_nba_season_averages` **requires** `player_ids` — it will not return a
  whole league, so gather the ids you need first from one `players` call.

## Season numbering

A season is its **start year**: the 2023-24 NBA season is `2023`. This is the same
convention as the official `nba` provider, and the opposite of `apisports`' basketball
host, which wants the span string `"2023-2024"`.

## Reading a stat line

```json
{"min": "34:12", "pts": 28, "reb": 7, "ast": 11, "fg_pct": 0.526,
 "fg3m": 4, "turnover": 3}
```

`min` is a **"MM:SS" string** — sorting or averaging it needs a parse first. `turnover`
is singular. Percentages are decimals (0.526), not 52.6.

## Cursor pagination, concretely

```
GET /nba/v1/games?per_page=100
  → {"data": [...], "meta": {"next_cursor": 12345, "per_page": 100}}
GET /nba/v1/games?per_page=100&cursor=12345
```

When `meta.next_cursor` is absent, you have reached the end. Asking for `page=2` does
nothing at all — it is silently ignored, which looks like duplicate data rather than an
error.
