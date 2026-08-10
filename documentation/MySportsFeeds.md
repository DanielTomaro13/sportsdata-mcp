# MySportsFeeds (`mysportsfeeds`) — US majors, free for personal use

**5 tools · BYO key · shapes unverified**

NFL, NBA, MLB and NHL from [mysportsfeeds.com](https://www.mysportsfeeds.com).

## Why it is here

It is the only provider in this catalogue with a **non-commercial free tier across all
four major US leagues**. `sportsdataio` overlaps on scope but is trial-only. The
official `mlb`, `nhl` and `nba` providers are deeper, but none of them offer per-game
player logs in this uniform a shape.

## Auth is HTTP Basic, and asymmetric

The **username** is your API key. The **password** is the literal constant
`MYSPORTSFEEDS` — the same string for every account. That is not a placeholder in their
documentation.

```bash
export MYSPORTSFEEDS_API_KEY=your_key_here
```

This server encodes the pair for you; you never touch base64. (This is the only provider
here using HTTP Basic, which is why the engine grew a `static_basic` auth type for it —
the alternative was asking you to base64-encode a credential by hand, where a typo is
indistinguishable from a wrong password until the 401 arrives.)

## Season strings are their own language

The most common 404 here is a malformed season, and **the format differs by sport**:

| Sport | Format | Example |
|---|---|---|
| NFL, MLB | single year | `2023-regular`, `2023-playoff` |
| NBA, NHL | year span | `2023-2024-regular` |

The keywords `current`, `latest` and `upcoming` work everywhere and are what you want
most of the time.

## Tools

| Tool | What it gives you |
|---|---|
| `mysportsfeeds_games` | Games for a season, with scores and venue |
| `mysportsfeeds_boxscore` | Team and player box score for one game |
| `mysportsfeeds_player_gamelogs` | Per-game player statistics — the cleanest surface here |
| `mysportsfeeds_standings` | Standings with division, conference and overall rank |
| `mysportsfeeds_injuries` | Current injury list (no season segment — always "now") |

## A game is two nested objects

Identity lives under `schedule`, the result under `score`:

```json
{"schedule": {"id": 12345, "startTime": "...", "homeTeam": {"abbreviation": "BOS"}},
 "score": {"homeScoreTotal": 112, "awayScoreTotal": 108, "quarters": [...]}}
```

Code that expects a flat game object will find neither the teams nor the score.

## A convenient game id

`mysportsfeeds_boxscore` accepts a date-team identifier as well as a numeric id:

```
20240115-LAL-BOS
```

Usually easier than looking one up first.

## Filtering, which is where the value is

The endpoints take the same filter vocabulary, and applying it server-side is what makes
this API pleasant compared to paging a whole season:

| Filter | Accepts | Example |
|---|---|---|
| `date` | a day, or a range | `20240115`, `from-20240101-to-20240131` |
| `team` | team abbreviations | `LAL`, `BOS,NYK` |
| `player` | ids **or name slugs** | `stephen-curry` |
| `status` | game state | `unplayed`, `in-progress`, `final` |

Name slugs are the nicest touch here — `player=stephen-curry` works without a lookup
call, which no other US-sports provider in this catalogue offers.

## The stats groups differ per sport

`mysportsfeeds_player_gamelogs` returns a `stats` object whose groups depend on the
league: `passing` / `rushing` / `receiving` for the NFL, `offense` / `rebounds` /
`defense` for the NBA, `batting` / `pitching` for MLB. Do not write one parser for all
four.

## Injuries have no season segment

`mysportsfeeds_injuries` is always "now" — the path takes a league and nothing else.
That is deliberate on their side, and it means you cannot ask who was injured in week 3
of last season from this endpoint.

## See also

- [SportsDataIO.md](SportsDataIO.md) — the same leagues, plus DFS salaries, trial-only
- [MLB.md](MLB.md), [NHL.md](NHL.md), [NBA.md](NBA.md) — official, keyless, deeper
