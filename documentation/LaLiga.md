# LaLiga — Reverse-Engineered API Documentation

Reference for the **LaLiga** read surface as modelled by the packaged provider
spec (`src/sportsdata_mcp/specs/laliga.yaml`). These are the private JSON APIs
behind the Next.js site at **laliga.com**, served by Azure API Management and read
directly.

> **Unofficial / undocumented.** Routes and the public key can change without
> notice. Re-probed live and confirmed `200` on **2026-06-15** (from country `AU`).
> Underlying stats are **Opta** (Stats Perform).

## Host & auth

| | |
|---|---|
| **Base** | `https://apim.laliga.com/public-service` |
| **Auth** | `Ocp-Apim-Subscription-Key: <key>` — a **public** Azure APIM subscription key |
| **Assets** | `https://assets.laliga.com/…` (badges, player photos — not modelled) |

The subscription key is lifted from the page bundle's
`runtimeConfig.backendSubscription`. It is **shipped as a working default** in the
spec, so the provider works out of the box — but **it rotates**. When reads start
returning `401`, override it:

| Env var (or `secrets:` entry) | Effect |
|---|---|
| `LALIGA_SUBSCRIPTION_KEY` | Overrides the bundled default key. Set this to the current key when it rotates. |

To re-harvest the current key, open laliga.com and read `__NEXT_DATA__` →
`props.runtimeConfig.backendSubscription`. (The engine resolves env → `secrets:` →
bundled literal, so env always wins when present.)

## Key concepts

- **Competition** — addressed by **slug** (numeric id 404s): `primera-division`
  (LALIGA EA SPORTS), `segunda-division`, `primera-division-femenina`.
- **Subscription** — a **season instance** of a competition. Slug
  `laliga-easports-{year}` (2023+) or `laliga-santander-{year}` (≤2022). **Most data
  hangs off a subscription.**
- **Season id = the starting year:** `2025` = the 2025/26 season → slug
  `laliga-easports-2025`.
- **opta_id** — the stable player/team join key across endpoints (`p60772`, `t186`).
  The numeric `id` differs per endpoint; **join on opta_id**.
- **position.id** — `1` Goalkeeper, `2` Defender, `3` Midfielder, `4` Forward
  (the `name`/`slug` are localised; the id is stable).
- **Detail endpoints are keyed by slug**, not numeric id — teams, players and
  matches all resolve via `/…/{slug}`. Discover slugs from the list feeds.

## Discovery flow

```
laliga_subscriptions                       →  subscription slug (laliga-easports-2025)
laliga_teams(subscription=slug)            →  team slug  →  laliga_team / laliga_squad
laliga_players_stats(slug)                 →  player slug →  laliga_player / laliga_player_stats
laliga_matches(subscription=slug)          →  match slug  →  laliga_match
laliga_standing(slug)                      →  the league table
```

## Core — group `laliga.core`

| Tool | Path | Capability |
|---|---|---|
| `laliga_competitions` | `/api/v1/competitions` | `sport.competitions_list` |
| `laliga_competition` | `/api/v1/competitions/{slug}` | — |
| `laliga_subscriptions` | `/api/v1/subscriptions?offset=` | `ref.seasons` |
| `laliga_subscription` | `/api/v1/subscriptions/{slug}` | `ref.seasons` |
| `laliga_standing` | `/api/v1/subscriptions/{slug}/standing` | `stats.ladder` |
| `laliga_rounds` | `/api/v1/subscriptions/{slug}/rounds` | — |

## Teams — group `laliga.teams`

| Tool | Path | Capability |
|---|---|---|
| `laliga_teams` | `/api/v1/teams?limit=&offset=` | `ref.teams` |
| `laliga_team` | `/api/v1/teams/{slug}` | `ref.teams` |
| `laliga_squad` | `/api/v1/teams/{slug}/squad?subscription=` | `ref.players` |

> **Scoping gotcha.** The `/api/v1/teams` and `/api/v1/matches` feeds and the squad
> roster are **not reliably season-scoped** — `laliga_teams` is a global directory
> (~1541 teams across all competitions, paginated) for resolving a team's
> slug/id/opta_id, and a squad returns the club's *current* roster regardless of the
> `subscription` passed. **For a season's actual data use the `/subscriptions/{slug}/…`
> path tools:** `laliga_standing` and `laliga_subscription` (its embedded `teams`) give
> the 20 teams; `laliga_players_stats` gives that season's players; `laliga_matches`
> needs `competition=` (see below).

## Players — group `laliga.players`

| Tool | Path | Capability |
|---|---|---|
| `laliga_players_stats` | `/api/v1/subscriptions/{slug}/players/stats?limit=&offset=` | `stats.player_season` |
| `laliga_player` | `/api/v1/players/{slug}` | `stats.player_profile` |
| `laliga_player_stats` | `/api/v1/players/{slug}/stats` | `stats.player_season` |

`laliga_players_stats` returns **every** player in the season (≈749) with full Opta
`stats[]` as `{name, stat}` pairs — `limit` maxes at 100, page with `offset`. Useful
stat names: `goals`, `goal_assists`, `appearances`, `time_played`, `clean_sheets`,
`shots_on_target_inc_goals`, `key_passes_attempt_assists`, `total_passes`,
`tackles_won`, `interceptions`, `goals_conceded`, `saves`, … (≈100 Opta metrics).

## Matches — group `laliga.matches`

| Tool | Path | Capability |
|---|---|---|
| `laliga_matches` | `/api/v1/matches?subscription=&competition=&gameweek=` | `sport.fixtures_by_date` |
| `laliga_match` | `/api/v1/matches/{slug}` | `sport.match_detail` |

**Pass `competition=` to get real LaLiga matches.** `subscription=` alone returns
a mixed bag (4581 rows, dominated by FIFA World Cup placeholders);
`competition=primera-division` filters to the **380** LALIGA EA SPORTS matches, and
adding `gameweek=N` returns one matchweek (10). `laliga_match` is keyed by the long
`temporada-…` **slug** (the numeric `id` 404s) and, for a played match, carries
`home_score`/`away_score` + `home_formation`/`away_formation`.

## Not modelled

- **Static assets** (`assets.laliga.com/.../shield`, player photos) — not JSON;
  fetch by URL. The squad/standing objects carry the asset URLs.
- **Match sub-resources** (`/matches/{id}/lineups|events|stats`) — return 404; the
  public surface exposes the matches feed + single-match detail only.
- **Subscription-scoped team/match paths** (`/subscriptions/{slug}/teams`,
  `/subscriptions/{slug}/matches`) — 404; use `/api/v1/teams?subscription=` and
  `/api/v1/matches?subscription=` instead (both modelled).

## Legal

laliga.com's terms restrict automated/commercial data use and redistribution. This
models how the public site works for read access; for production/commercial use
obtain a proper data licence (underlying provider: **Opta / Stats Perform**).
Respect a polite request rate and cache aggressively.

## Cross-provider comparison

LaLiga reuses the shared capability tags, so it composes with the other
league/data providers via `list_tools_by_capability` — and pairs naturally with the
**Premier League** provider for cross-league football comparisons:

- **`stats.ladder`** → `laliga_standing` next to `pl_standings` and the AFL/NRL ladders.
- **`sport.fixtures_by_date`** → `laliga_matches` alongside `pl_matches` / MLB / cricket schedules.
- **`stats.player_season`** → `laliga_players_stats` next to `pl_player_season_stats`
  and MLB / NBA / AFL season stats.
- **`ref.teams`** / **`ref.players`** / **`ref.seasons`** → the LaLiga catalogues join
  the Premier League / MLB / cricket reference data.
