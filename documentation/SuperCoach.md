# SuperCoach — `supercoach.com.au` (News Corp / Champion Data fantasy)

SuperCoach is News Corp / Champion Data's salary-cap fantasy game. Its public JSON
API exposes, for every player, the full fantasy picture — price, scoring,
projection, ownership, positions, availability, news and matchup context — plus
fixtures (with bookmaker odds) and the club catalogue. **No authentication** for
the feeds modelled here, and it is **not geo-blocked** (unlike the AU bookmakers),
so it runs in CI.

Probed live 2026-06-26 across all seven games. Provider id `supercoach`, group
`supercoach.fantasy` (6 tools).

### Two game modes

Every sport has **two modes** at `/{mode}/v1/`:

- **`classic`** (default) — the salary-cap game, all 7 sports.
- **`draft`** — the draft-league variant (afl / nrl / nba / epl). Players gain a
  top-level **`predraft_rank`** and `player_stats.position_ranks` (the draft
  rankings). Same response shape otherwise.

Pass `mode` to any tool (defaults to `classic`).

## One surface, seven games

Every feed lives under:

```
https://www.supercoach.com.au/{year}/api/{sport}/classic/v1/...
```

Only two things vary — and the response **shape is identical** across all seven
games (only the per-player stat columns inside `player_stats[]` differ):

| `sport` | Game | Players | Teams |
|---|---|---|---|
| `afl` | AFL | 812 | 18 |
| `nrl` | NRL | 583 | 17 |
| `epl` | Premier League | 817 | 20 |
| `nba` | NBA | 626 | 30 |
| `nbl` | NBL (Aus basketball) | 174 | 10 |
| `nfl` | NFL | 1032 | 32 |
| `bbl` | Big Bash League (cricket) | 174 | 8 |

### `year` is the season key, not always the calendar year

- **`afl` / `nrl`** — current **calendar year** (`2026` now; in-season Apr–Sep).
- **`epl` / `nba` / `nbl` / `nfl` / `bbl`** — the **season's year**, currently
  `2025` (these run across the new year; `2024` is still served as the prior
  archive).

When unsure, call `supercoach_settings` for the current year; if the feed is empty,
try the prior year.

Headers: a browser-like `User-Agent` + `Accept: application/json` (baked into the
spec). Nothing else. (AFL fetches with a plain client; the AU-modelling NRL
pipeline uses a TLS-impersonating client to match its other scrapers, but
SuperCoach itself does not require it.)

## Tools — group `supercoach.fantasy`

| Tool | Path (under `/{year}/api/{sport}/classic/v1/`) | Capability |
|---|---|---|
| `supercoach_settings` | `settings?min=false` | — (discovery) |
| `supercoach_players` | `players-cf?embed=&round=` | `stats.fantasy_projections`, `stats.player_season`, `stats.player_game_log`, `ref.players` |
| `supercoach_real_fixture` | `real_fixture?round=&page=&page_size=` | `sport.fixtures_by_date`, `sport.match_score` |
| `supercoach_teams` | `teams` | `ref.teams` |
| `supercoach_player` | `players/{id}` | `ref.players`, `stats.player_profile` |
| `supercoach_leagues` | `leagues` | — (the game's public/featured leagues) |

### Typical flow

1. `supercoach_settings` → `competition.current_round` (last scored) and
   `next_round` (the one to project).
2. `supercoach_players` with `round = next_round` → the forward-looking snapshot
   (price / projection / opponent for the upcoming round).
3. To build a per-round score series, loop `round = 1..current_round` with
   `embed=player_match_stats` and collect each `{round, points}`.

## `supercoach_players` — the money feed

`players-cf` is **per-round**: `player_stats` are scoped to the `round` you pass.
Omitting `round` does **not** return the whole season. The payload is large
(~1–3 MB; 174–1032 players).

**The `embed` set is CLOSED** — only these five add data; anything else is silently
ignored (returns the base size):

| embed | adds |
|---|---|
| `player_stats` | price / projection / ownership / season totals — **the main one** |
| `player_match_stats` | that round's per-game `{games, points}` — the score-series source |
| `positions` | `{position, position_long}` (MID/FWD/DEF/RUC for AFL; SG/SF/… for NBA; DPP = multiple) |
| `notes` | dated news blurbs `{note, created_on}` |
| `odds` | **AFL Brownlow odds only** |

Default embed is `positions,player_stats,notes`.

### Projection — use `ppts1`, not `ppts`

`player_stats[0]` carries two projection fields:

- ✅ **`ppts1`** — SuperCoach's real next-round projection (tracks form, ≈ `avg`).
  Present for **AFL / NRL**. **Use this.**
- ❌ **`ppts`** — erratic (inflated for some, ~0 for many). Do not use.
- **Fallback: `avg`** — and note `ppts1` is **not posted for every game** (e.g.
  `nba` returns price/`avg`/`avg3`/`avg5` but no `ppts1`), so always fall back to
  `avg` when `ppts1` is absent.

### Other key `player_stats[0]` fields

- **Pricing / scoring**: `price`, `price_change`, `total_price_change`, `avg`,
  `avg3`, `avg5`, `total_games`, `total_points`, `owned` (%).
- **Matchup**: `opp:{abbrev}`, `opph` (home flag), `oppavg`, `ven:{name}`,
  `venavg`, and `opp1/opp2/opp3` (+ `opp1h/2h/3h`) — the next three opponents.
- **Stat totals** (sport-specific, `total_` prefix): AFL `total_kicks`,
  `total_handballs`, `total_marks`, `total_tackles`, `total_goals`, …; NBA
  `total_rebounds`, `total_assists`, `total_blocks`, `total_steals`, …

Per-player (top level, not in `player_stats`): `positions[]`, `played_status.status`
(in / out / yet-to-play), `injury_suspension_status_text`, `notes[]`.

## `supercoach_real_fixture` — fixtures, scores **and** odds

Richer than the fantasy core: each row carries `kickoff`, both teams,
`venue`/`location`, final `team1_score`/`team2_score` (+ verbose), live
`match_status`/`period`, **and** the head-to-head bookmaker odds
(`team1_odds`/`team2_odds` + `team1_bookmaker_title`/`_link`). Pass `round` for one
round, or omit it for the whole season (AFL ≈ 207 rows). Paginate with
`page`/`page_size` (default `page_size=9998` ≈ all).

## Not modelled / not available

- **User-context endpoints** return `401` anonymously: `player-trades` (so
  "most traded in/out" is unavailable — but `owned` % is here), `userteams/{id}/*`,
  `rankings/*`, `achievements`, `leagues`.
- The `draft/v1` variant adds nothing (no ADP/rankings) and mostly 404s; the
  `subkey`/`subid` variant of `players-cf` returns empty. Use the plain
  `classic/v1` calls above.
- Everything outside the five endpoints 404s — this is the full public surface.

## Cross-provider comparison

SuperCoach is the **fantasy / projections** angle on the same fixtures the odds and
league providers cover:

- **`stats.fantasy_projections`** → `supercoach_players` alongside Data Golf's DFS
  pricing — projections + ownership for the salary-cap games.
- **`sport.fixtures_by_date`** → `supercoach_real_fixture` lines up with the AFL /
  NRL / EPL / NBA league feeds and the bookmaker fixture lists (and it even carries
  its own H2H odds for a quick sanity check).
- **`ref.players` / `ref.teams`** → the player and club catalogues per game.

## Quick test

```bash
Y=2026   # afl/nrl; use 2025 for epl/nba/nbl/nfl/bbl
UA='Mozilla/5.0'
# current round / next round
curl -s "https://www.supercoach.com.au/$Y/api/afl/classic/v1/settings?min=false" \
  -H "User-Agent: $UA" | jq '.competition | {current_round, next_round}'
# one player's projection
curl -s "https://www.supercoach.com.au/$Y/api/afl/classic/v1/players-cf?embed=player_stats&round=15" \
  -H "User-Agent: $UA" \
  | jq '.[0] | {name:(.first_name+" "+.last_name), proj:.player_stats[0].ppts1, avg:.player_stats[0].avg}'
# any other game — swap afl → nrl|epl|nba|nbl|nfl|bbl (and the year)
```
