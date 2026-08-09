# Sleeper API Documentation

Reference for **`api.sleeper.app/v1`** — the read API behind the Sleeper fantasy
platform. Probed live 2026-08-10 against league `289646328504385536` (Sleeper's own
documentation example: a completed 2018 season, so its shapes don't drift).

> **Pairs with [ESPN Fantasy](ESPNFantasy.md).** Same job, different ecosystem — and
> one important practical difference: **Sleeper's read API is completely public.** No
> key, no cookie, no account. Anyone holding a league id can read that league. ESPN
> needs a browser cookie for private leagues; Sleeper needs nothing.

> **Read-only by design.** Sleeper's public API has no write surface — roster moves
> happen in their app. That suits this server, which never mutates anything.

## Contents

- [The id chain](#the-id-chain)
- [The join nobody expects](#the-join-nobody-expects)
- [Tools](#tools)
- [Why there's no player-catalogue tool](#why-theres-no-player-catalogue-tool)
- [Reading a matchup](#reading-a-matchup)
- [Reading the playoff bracket](#reading-the-playoff-bracket)
- [Gotchas](#gotchas)
- [Cross-provider comparison](#cross-provider-comparison)

## The id chain

```
sleeper_user(username)              → user_id
   └─ sleeper_user_leagues(user_id, sport, season) → league_id
         ├─ sleeper_league            → scoring + roster rules
         ├─ sleeper_league_rosters    → roster_id, owner_id, player ids
         ├─ sleeper_league_users      → user_id → display_name / team name
         ├─ sleeper_matchups(week)    → matchup_id, points
         ├─ sleeper_transactions(week)
         ├─ sleeper_playoff_bracket
         └─ sleeper_league_drafts     → draft_id
               └─ sleeper_draft_picks → every pick, with player names
```

`sleeper_user_leagues` takes the **numeric `user_id`**, not the username. Passing the
username returns nothing rather than erroring — an empty list that looks like "this
person has no leagues".

A league id is also just visible in the Sleeper app URL, so a user can usually paste
it directly and skip the first two steps.

## The join nobody expects

Two different ids identify "a team", and **nothing carries both**:

- **`roster_id`** — league-local (`1..N`). Matchups, transactions and brackets all key
  off this.
- **`user_id`** — global, identifies a person. Only `sleeper_league_users` maps it to a
  display name or team name.

So turning "roster 7 scored 118.4" into "Dave's team scored 118.4" means:

```
sleeper_matchups        → roster_id
sleeper_league_rosters  → roster_id → owner_id
sleeper_league_users    → user_id (== owner_id) → display_name / metadata.team_name
```

Skipping the middle step is the single most common mistake against this API.

## Tools

### `sleeper.reference`

| Tool | Returns | Capability |
|---|---|---|
| `sleeper_state` | Current season, week, and whether scoring has started | `ref.seasons` |
| `sleeper_user` | Resolve a username → `user_id` | — |
| `sleeper_trending_players` | Most-added / most-dropped players platform-wide | `fantasy.free_agents` |

### `sleeper.league`

| Tool | Returns | Capability |
|---|---|---|
| `sleeper_user_leagues` | A user's leagues for a sport + season | — |
| `sleeper_league` | Scoring rules, roster slots, playoff and waiver settings | `fantasy.league_settings` |
| `sleeper_league_rosters` | Player ids held and started, plus W/L and points | `fantasy.rosters` |
| `sleeper_league_users` | The humans — display names, team names | — |
| `sleeper_matchups` | A week's matchups with per-player scoring | `fantasy.matchups` |
| `sleeper_transactions` | Adds, drops, waivers, trades | `sport.transactions` |
| `sleeper_playoff_bracket` | Championship or consolation bracket | `fantasy.matchups` |
| `sleeper_traded_picks` | Future picks that changed hands (dynasty) | `sport.transactions` |

### `sleeper.draft`

| Tool | Returns | Capability |
|---|---|---|
| `sleeper_league_drafts` | The drafts belonging to a league | `sport.draft` |
| `sleeper_draft` | One draft's type, rounds and slot order | `sport.draft` |
| `sleeper_draft_picks` | Every pick in order, **with player names** | `sport.draft` |

## Why there's no player-catalogue tool

Sleeper's `/players/nfl` returns the entire NFL player universe in one document:
**~15 MB**. Sleeper's own documentation asks callers to fetch it at most once a day
and cache it.

It is deliberately **not** exposed as a tool. Handing a 15 MB blob to a model would
blow its context window for no benefit, and calling it repeatedly abuses a free API.
Get player identity instead from:

- **`sleeper_draft_picks`** — each pick's `metadata` carries `first_name`,
  `last_name`, `position` and `team`.
- **`sleeper_trending_players`** — the waiver signal, without the catalogue.
- **A roster** — `players[]` gives ids you can resolve against another provider.

## Reading a matchup

`sleeper_matchups` returns one row per roster, **not one row per game**:

```jsonc
{ "roster_id": 3, "matchup_id": 1, "points": 118.4,
  "starters": ["4034", "1234"], "starters_points": [22.6, 14.1],
  "players_points": { "4034": 22.6, ... } }
```

Two rows sharing a `matchup_id` played each other. There is **no home/away** — pair
them yourself. A `matchup_id` of `null` means that roster had a bye.

`starters` is positional: `starters[i]` scored `starters_points[i]`, and the slot order
matches `roster_positions` from `sleeper_league`. An empty string in `starters` is an
unfilled slot, which is why a manager can start fewer players than the lineup allows.

## Reading the playoff bracket

The bracket uses aggressively terse keys:

| Key | Meaning |
|---|---|
| `r` | Round number |
| `m` | Match id within the bracket |
| `t1` / `t2` | The two `roster_id`s |
| `w` / `l` | Winner and loser (`null` until played) |
| `t1_from` / `t2_from` | Which earlier match feeds this slot |

`t1_from: {"w": 1}` means "the winner of match 1 lands here" — that's how you rebuild
the tree before the games are played.

## Gotchas

| Symptom | Cause |
|---|---|
| **Empty list from `sleeper_user_leagues`** | You passed the username instead of the numeric `user_id`, or the user genuinely has no league that season. |
| **Roster with no name** | Names live only in `sleeper_league_users`; join via `owner_id`. |
| **`matchup_id` is null** | That roster had a bye week. |
| **Transactions returns the whole season** | Some leagues return everything regardless of the `week` argument — filter client-side on `leg`. |
| **Player ids are opaque strings** | Sleeper ids (`"4034"`) are its own; they don't match ESPN or NFL ids. Join on name + team. |
| **Bracket keys unreadable** | See the table above — `r`/`m`/`t1`/`w` are round/match/team/winner. |
| **Considering `/players/nfl`** | 15 MB. Don't — see above. |

## Cross-provider comparison

- `fantasy.rosters`, `fantasy.matchups`, `fantasy.league_settings` → Sleeper joins
  `espnfantasy` on all three, so "show me my league" works across both platforms
  through one capability lookup. Sleeper is the easier of the two to reach: no cookie.
- `fantasy.free_agents` → `sleeper_trending_players` alongside
  `espnfantasy_player_info`. Sleeper's signal is *platform-wide* (what everyone is
  adding), ESPN's is *league-specific* (what's actually available in yours) — they
  answer different halves of the same question.
- `sport.draft` → `sleeper_draft_picks` alongside `espnfantasy_draft`.
- Player identity does **not** join automatically to the real-world providers: Sleeper
  ids are proprietary. Use `metadata` names from draft picks, then look the player up
  in `espn` or `nhl`/`mlb` by name.

## Not modelled

- **`/players/{sport}`** — the 15 MB catalogue (see above).
- **Writes** — none exist in the public API.
- **Avatars** (`/avatars/{id}`) — image bytes, not data.
- **LCS / NBA / Bundesliga fantasy** — the same endpoints accept other `sport` values,
  but only `nfl` is actively used; `sleeper_state` exposes the others if needed.
