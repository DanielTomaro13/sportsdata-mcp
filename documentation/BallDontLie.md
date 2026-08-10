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

| Tool | League |
|---|---|
| `balldontlie_nba_teams`, `_nba_players`, `_nba_games`, `_nba_stats`, `_nba_season_averages`, `_nba_standings` | NBA |
| `balldontlie_nfl_games` | NFL |
| `balldontlie_mlb_games` | MLB |
| `balldontlie_epl_teams`, `_epl_games` | Premier League |

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
