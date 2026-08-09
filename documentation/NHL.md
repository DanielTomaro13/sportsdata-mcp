# NHL API Documentation

Unofficial reference for **`api-web.nhle.com/v1`**, the NHL's own web API — the one
nhl.com reads. No key, no signup, no bot challenge, no geo-block. Probed live
2026-08-10.

> **The old API is dead.** Anything referencing `statsapi.web.nhl.com/api/v1/...` is
> pre-2023 and no longer resolves. This is its replacement.

> **Why this exists alongside `espn`.** The [ESPN provider](ESPN.md) already serves NHL
> scores and standings through its slug-parametric dispatchers — `hockey/nhl` works
> today. This is the **depth** layer: real box scores with per-player ice time, full
> rosters with bio and draft detail, career splits, and league leaders. Use ESPN for
> "what's the score", this for "what happened".

## Contents

- [The two conventions that break calls](#the-two-conventions-that-break-calls)
- [The id model](#the-id-model)
- [Tools](#tools)
- [Reading a box score](#reading-a-box-score)
- [Standings sequencing](#standings-sequencing)
- [Gotchas](#gotchas)
- [Cross-provider comparison](#cross-provider-comparison)

## The two conventions that break calls

**1. Season ids are concatenated years.** 2024-25 is **`20242025`**, not `2024` or
`2024-25`. A wrong season id returns **404**, not an empty list — so a typo looks like
an outage.

**2. `/now` paths redirect.** `/standings/now`, `/schedule/now` and `/score/now` return
**307** to the concrete dated path. This provider follows redirects, so it's invisible
here — but a raw `curl` without `-L` shows `307` and an empty body, which looks broken
and isn't.

Teams are addressed by **three-letter abbreviation** (`TOR`, `COL`, `VGK`), never by
numeric id.

## The id model

```
nhl_seasons                        → seasons[].id        (20242025 — feed to roster / schedules / leaders)
nhl_roster(team, season)           → forwards/defensemen/goalies[].id   (playerId)
     └─ nhl_player(playerId)       → bio, draft, career totals
nhl_schedule / nhl_scores          → games[].id          (gameId)
     ├─ nhl_boxscore(gameId)       → per-player lines
     └─ nhl_game_landing(gameId)   → scoring summary, penalties, three stars
```

## Tools

### `nhl.reference`

| Tool | Returns | Capability |
|---|---|---|
| `nhl_seasons` | Every season with start/end dates and which rules applied | `ref.seasons` |
| `nhl_roster` | A club's roster for a season, by position group | `ref.players` |
| `nhl_player` | Bio, draft, season splits, career totals, awards | `stats.player_profile`, `stats.player_career`, `stats.player_season` |

### `nhl.schedule`

| Tool | Returns | Capability |
|---|---|---|
| `nhl_schedule` | League schedule for a week, grouped by day | `sport.fixtures_by_date` |
| `nhl_club_schedule` | One club's whole season with results (~200 KB) | `sport.fixtures_by_date`, `stats.team_game_log` |

### `nhl.game`

| Tool | Returns | Capability |
|---|---|---|
| `nhl_scores` | Live scoreboard with clock and period | `sport.match_score`, `sport.in_play` |
| `nhl_boxscore` | Both lineups: G, A, +/-, shots, hits, blocks, TOI | `sport.match_boxscore`, `stats.player_match` |
| `nhl_game_landing` | Scoring by period, penalties, three stars, team stats | `sport.match_detail`, `stats.play_by_play` |

### `nhl.stats`

| Tool | Returns | Capability |
|---|---|---|
| `nhl_standings` | Standings with division/conference/wildcard sequencing | `stats.ladder` |
| `nhl_skater_leaders` | Goals, assists, points, +/-, PP/SH goals, PIM, TOI | `stats.leaders_season` |
| `nhl_goalie_leaders` | Wins, save %, GAA, shutouts | `stats.leaders_season` |

## Reading a box score

Player lines are **not** a flat list. They're nested by team and position group:

```
playerByGameStats
├── homeTeam
│   ├── forwards[]   { playerId, name, goals, assists, points, plusMinus, sog, hits, blockedShots, toi }
│   ├── defense[]    { … }
│   └── goalies[]    { saveShotsAgainst, savePctg, toi, … }
└── awayTeam { … }
```

Two things to note: **goalies carry different fields** from skaters (save percentage,
not plus-minus), and **`toi` is a string** like `"18:42"`, not a number — summing ice
time means parsing it.

Names arrive as localisation objects: `firstName: {default: "Connor"}`. Reading
`firstName` directly gives you a dict, not a string — the same pattern appears in
standings (`teamName.default`) and leaders.

## Standings sequencing

`nhl_standings` gives three parallel orderings, and picking the wrong one produces a
table that looks subtly incorrect:

- `divisionSequence` — position within the division
- `conferenceSequence` — position within the conference
- `wildcardSequence` — position in the wildcard race

Playoff qualification in the NHL is division-first with wildcards, so "who's in" is
`divisionSequence <= 3` plus the top two `wildcardSequence` per conference — not
simply the top eight by points. `clinchIndicator` (`x`, `y`, `z`, `p`) marks teams
already qualified.

## Gotchas

| Symptom | Cause |
|---|---|
| **HTTP 404 on roster/schedule** | Season id isn't concatenated years — use `20242025`, not `2024`. |
| **307 with an empty body** | You called a `/now` path without following redirects. The provider follows them. |
| **`firstName` is a dict** | Names are localisation objects — read `.default`. Same for `teamName`, `placeName`. |
| **`toi` won't sum** | Ice time is a `"MM:SS"` string, not seconds. |
| **Empty `games` in the off-season** | Correct: there are no games. Check `regularSeasonStartDate` in the schedule response. |
| **Goalies missing expected stats** | Goalie rows have a different shape from skaters — don't assume one schema. |
| **~200 KB from club schedule** | A full season of games. Expected; narrow with the game-by-game tools if you only need one. |

## Cross-provider comparison

- `stats.ladder` → `nhl_standings` alongside `mlb_standings`, `premierleague`,
  `laliga`, `seriea`, `afl_ladders`, `squiggle_standings`.
- `sport.match_boxscore` / `stats.player_match` → `nhl_boxscore` alongside
  `mlb_boxscore`, `nba_boxscore`, `espn_game_summary`.
- `sport.in_play` → `nhl_scores` alongside the bookmakers' in-play feeds — the natural
  pairing is a live NHL score here against a live price at `pinnacle` or `betfair`.
- `ref.players` → `nhl_roster` alongside `mlb_player`, `espn` athletes. NHL player ids
  are NHL-specific and do **not** match ESPN athlete ids; join on name + team.
- ESPN Fantasy's `fhl` game covers **fantasy** hockey; this is the real competition
  behind it. Roster a player in `espnfantasy`, then read their real line here.

## Not modelled

- **Play-by-play** (`/gamecenter/{id}/play-by-play`) — large and event-shaped; the
  landing endpoint's scoring summary covers most questions. Worth adding if event-level
  analysis is wanted.
- **Shift charts** (`/shiftcharts`) — a different host with its own query grammar.
- **Draft, prospects and franchise history** — available but low-value next to the
  live competition surfaces.
- **Anything on `api.nhle.com/stats/rest`** — the separate reporting API, with its own
  filter language.
