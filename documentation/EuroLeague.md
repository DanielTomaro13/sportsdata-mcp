# EuroLeague Basketball API Documentation

Reference for **`api-live.euroleague.net/v2`** — the official feed behind
euroleaguebasketball.net. No key, no signup. Probed live 2026-08-10.

Completes the basketball picture: the server had the NBA (`nba`, `espn`) and
Australia's NBL, but nothing for Europe's top competition.

## Two competitions, one API

A single letter selects the competition, and every tool takes it:

| Letter | Competition |
|---|---|
| `E` | EuroLeague |
| `U` | EuroCup |

## Three conventions that break calls

**1. Season codes are letter + starting year.** `E2024` is the 2024-25 EuroLeague
season; `U2024` the matching EuroCup. A bare `2024` fails.

**2. `gameCode`, not `id`.** A game object carries both a UUID `id` and an integer
`gameCode` (per-season sequential: 1, 2, 3 …). The per-game paths take **`gameCode`**.
Passing the UUID 404s.

**3. Home and away are `local` and `road`** — everywhere, including box scores.

## The envelope is inconsistent

List endpoints wrap results:

```jsonc
{"total": 342, "data": [ … ]}
```

Single-object endpoints (`euroleague_game`) return the object **directly**, with no
`data` key. Assuming one shape for both is the usual error.

## Tools

| Tool | Returns | Capability |
|---|---|---|
| `euroleague_seasons` | Season codes for a competition | `ref.seasons` |
| `euroleague_clubs` | Clubs with city, country, venue | `ref.teams` |
| `euroleague_people` | Players + coaches (**~600 KB** — page it) | `ref.players` |
| `euroleague_rounds` | Rounds with date windows | — |
| `euroleague_games` | Games with scores (**~800 KB** unpaged) | `sport.fixtures_by_date`, `sport.match_score` |
| `euroleague_game` | One game by `gameCode` | `sport.match_detail` |
| `euroleague_game_stats` | Box score, both teams | `sport.match_boxscore`, `stats.player_match` |

## Reading a box score

`euroleague_game_stats` splits by side, each with player lines, a team total and the
coach — and **a player line is nested**, identity separate from numbers:

```jsonc
{ "local": {
    "team": …, "coach": …, "total": { …team totals… },
    "players": [
      { "player": { "person": …, "dorsal": 7, "position": …, "club": … },
        "stats":  { "timePlayed": 1088.0, "valuation": 12.0, "points": 5.0,
                    "fieldGoalsMade2": 1.0, "fieldGoalsMade3": 1.0, … } }
    ] },
  "road": { … } }
```

Reading `players[0].points` gets nothing — it's `players[0].stats.points`.

Three EuroLeague-specific things:

- **`valuation`** is PIR (Performance Index Rating), European basketball's standard
  efficiency metric. It has no equivalent in the `nba` provider.
- **`timePlayed` is SECONDS as a float** — `1088.0` is 18:08. Not a `"MM:SS"` string.
- Field goals are split `fieldGoalsMade2` / `fieldGoalsMade3` with a separate
  `fieldGoalsMadeTotal`, rather than the NBA's FG + 3P convention.

## Gotchas

| Symptom | Cause |
|---|---|
| **404 on a game** | You used the UUID `id` instead of the integer `gameCode`. |
| **404 on a season** | Season needs the competition letter: `E2024`, not `2024`. |
| **No `data` key** | Single-object endpoints return the object directly. |
| **~800 KB response** | The unpaged season game list. Pass `limit` or `roundNumber`. |
| **Can't find home/away** | They're `local` and `road`. |
| **Minutes won't sum** | `"MM:SS"` strings. |
| **404 on standings** | The website's standings/statistics paths are **not** on this host — see below. |

## Not modelled

- **Standings and season statistics.** The website shows both, but the paths that serve
  them are not on `api-live.euroleague.net/v2` (verified 404 for
  `/standings`, `/statistics/teams/traditional`, `/statistics/players/traditional`).
  They're served by a different backend. A standings table can be derived from
  `euroleague_games` in the meantime — every played game carries both scores.
- **Play-by-play and shot charts** — on a separate live host with its own shape.
- **Historical seasons before the v2 API's coverage** — `euroleague_seasons` reports
  what's actually available.

## Cross-provider comparison

- `sport.match_boxscore` / `stats.player_match` → `euroleague_game_stats` alongside
  `nba_boxscore`, `nhl_boxscore`, `mlb_boxscore`. Note the metrics differ: PIR here,
  NBA-style efficiency there — don't present them as the same number.
- `ref.teams` / `ref.players` → clubs and people alongside the NBA/NBL catalogues.
  Players move between EuroLeague and the NBA, but ids don't join; match on name.
- Bookmaker composition: EuroLeague is priced by most AU and European books, so a game
  here lines up against `sportsbet` / `pinnacle` / `betfair` markets.
