# Serie A — Reverse-Engineered API Documentation

Reference for the **Serie A** (Lega Serie A) read surface as modelled by the
packaged provider spec (`src/sportsdata_mcp/specs/seriea.yaml`). This is the
public **SDP** ("Sports Data Platform") JSON API behind **legaseriea.it**, read
directly.

> **Unofficial / undocumented**, **no authentication** (just a normal
> `User-Agent`). Re-probed live and confirmed `200` on **2026-06-15**. Underlying
> stats are **Opta**.

## Host

| | |
|---|---|
| **Base** | `https://api-sdp.legaseriea.it/v1/serie-a/football` |
| **Auth** | none |
| **Imagery** | `https://media-sdp.legaseriea.it/<imagery path>` (e.g. `clubLogos/{hex}.webp` — not modelled) |

Add `locale=en-GB` for English labels (baked as a default on every tool).

## Key concepts

- **Opaque SDP ids carry a literal `::`** (sent as-is in the path; the server
  accepts it, the engine needs no special handling):
  - season `serie-a::Football_Season::5f0e080fc3a44073984b75b3a8e06a8a`
  - team `serie-a::Football_Team::3294993c79b14d918ccdc78da0fb90c5`
  - Every entity also carries a raw `opta:*` `providerId`; **join on the SDP id**.
- **The Serie A competition id is fixed and baked into `seriea_seasons`** — you
  never type it. Start there to get a `seasonId`, then drill in.
- **Season id = a `seasonId` string**; `seasonName` is like `"2025/2026"` (starting
  year `2025` = 2025/26). 41 seasons available (1986/87 → 2026/27).
- **`role`** — `1` Goalkeeper, `2` Defender, `3` Midfielder, `4` Forward
  (`roleLabel` is localised; the numeric `role` is stable).
- **No squad endpoint** — the player-stats feed returns identity **and** stats in
  one call. **No single-match / rounds endpoint** — match data (scores, matchday,
  stadium) lives in the matches feed.

## Discovery flow

```
seriea_seasons                       →  seasonId (e.g. 2025/26)
seriea_standings(seasonId)           →  the league table (overall/home/away)
seriea_teams(seasonId)               →  the 20 teams
seriea_players(seasonId, category, page)  →  every player + ~279 Opta stats (30/page)
seriea_matches(seasonId)             →  all 380 matches (scores, matchday)
```

## Core — group `seriea.core`

| Tool | Path | Capability |
|---|---|---|
| `seriea_competitions` | `/competitions` | `sport.competitions_list` |
| `seriea_seasons` | `/competitions/{Serie A compId}/seasons` (compId baked) | `ref.seasons` |
| `seriea_season` | `/seasons/{seasonId}` | `ref.seasons` |

## Per-season data — group `seriea.season`

| Tool | Path | Capability |
|---|---|---|
| `seriea_standings` | `/seasons/{seasonId}/standings/overall` | `stats.ladder` |
| `seriea_teams` | `/seasons/{seasonId}/teams` | `ref.teams` |
| `seriea_players` | `/seasons/{seasonId}/stats/players?category=&page=` | `stats.player_season` |
| `seriea_matches` | `/seasons/{seasonId}/matches` | `sport.fixtures_by_date` |

### Notes

- **Standings** returns **three** tables — `standings[0]` overall, `[1]` home,
  `[2]` away — each with 20 teams. Each team carries `stats[]` keyed by `statsId`
  (`rank`, `points`, `matches-played`, `win`, `draw`, `lose`, `goals-for`,
  `goals-against`, `goal-difference`).
- **Players** is paginated **30/page** (`pagination.totalPages` / `isLastPage`; a
  `pageSize` param is **ignored**). `category` is **`General`** or **`Goalkeeping`**
  only — `Attack`/`Defence`/etc. return `400`. Each row has ~279 Opta
  `{statsId, statsValue}` pairs. Note the inconsistent stat-key casing — kebab-case
  (`games-played`, `goals`, `assists`, `tackles-won`, `saves` *(Goalkeeping only)*)
  and Title-case (`Interceptions`, `Total Passes`, `Goal Assists`,
  `Shots On Target ( inc goals )`) — read with fallbacks. There is no per-player
  clean-sheets/saves stat in `General`; clean sheets must be derived from
  `seriea_matches`.
- **Matches** is season-scoped (all 380, no competition mixing). Scores are
  `providerHomeScore`/`providerAwayScore`; `status` is `FINISHED` for played games;
  the matchweek is `matchSet` (its `providerId` is `opta:MatchDay:N`).

## Not modelled

- **Imagery** (`media-sdp.legaseriea.it/...webp`) — binary; the team/player objects
  carry the relative `imagery` paths, prepend the media host.
- **CMS / editorial** (`dapi.legaseriea.it/v2/content/...`) — a separate content
  host; the pipeline doesn't use it and its routes aren't documented here.
- **Single-match / rounds** endpoints — return `404`; match data is in the matches
  feed, and the matchweek is on each match's `matchSet`.

## Legal

legaseriea.it's terms restrict automated/commercial data use and redistribution.
This models how the public site works for read access; for production/commercial
use obtain a proper data licence (underlying provider: **Opta / Stats Perform**).

## Cross-provider comparison

Serie A reuses the shared capability tags, so it joins the **Premier League** and
**La Liga** providers for cross-league football comparison via
`list_tools_by_capability`:

- **`stats.ladder`** → `seriea_standings` next to `pl_standings` / `laliga_standing`.
- **`sport.fixtures_by_date`** → `seriea_matches` alongside `pl_matches` /
  `laliga_matches` and the MLB / cricket schedules.
- **`stats.player_season`** → `seriea_players` next to `pl_player_season_stats` /
  `laliga_players_stats`.
- **`ref.teams`** / **`ref.seasons`** → the Serie A catalogues join the other
  league reference data.
