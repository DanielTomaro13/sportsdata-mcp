# WTA — `wtatennis.com` (Women's Tennis Association, official)

The WTA's **official** data API — the same backend that powers wtatennis.com. A
public Spring REST API at `api.wtatennis.com/tennis/…` with **no auth, no key, no
Origin/Referer gate** and no geo-block: it returns JSON to a plain request. Runs in
CI.

Probed live 2026-06-26. Provider id `wta`, group `wta.tennis` (8 tools).

## Shape

- **List endpoints** are paginated: `{pageInfo:{numPages, totalElements}, content:[…]}`,
  via `page` (0-based) + `pageSize`.
- **Rankings** (`wta_rankings`) returns a **bare array**, not the envelope.
- **Tournaments are keyed by `tournamentGroup.id` + `year`** — there's no flat
  tournament id. The Australian Open is group `901`, so `…/tournaments/901/2025`
  is AO 2025. Get the group id + year from `wta_tournaments`
  (`content[].tournamentGroup.id` + `.year`).

## Tools — group `wta.tennis`

| Tool | Path (`/tennis/…`) | Capability |
|---|---|---|
| `wta_rankings` | `players/ranked?type=&metric=&page=&pageSize=` | `sport.rankings` |
| `wta_players` | `players?name=&page=&pageSize=` | `ref.players` |
| `wta_player` | `players/{playerId}` | `ref.players`, `stats.player_profile` |
| `wta_player_matches` | `players/{playerId}/matches` | `stats.player_game_log`, `stats.player_career` |
| `wta_tournaments` | `tournaments?page=&pageSize=` | `sport.competitions_list` |
| `wta_tournament` | `tournaments/{groupId}/{year}` | `sport.competition_screen`, `sport.season_summary` |
| `wta_tournament_matches` | `tournaments/{groupId}/{year}/matches` | `sport.fixtures_by_date`, `sport.match_score` |
| `wta_tournament_players` | `tournaments/{groupId}/{year}/players` | `sport.competition_screen`, `ref.players` |

### Rankings — `type` + `metric` (must agree)

`wta_rankings` **requires both** `type` and `metric`, and they must match:

- `type=rankSingles` with `metric=singles`
- `type=rankDoubles` with `metric=doubles`

Each row: `{player:{id, fullName, countryCode, dateOfBirth}, ranking, points,
tournamentsPlayed, movement, rankedAt}`. `pageSize=100` → top 100.

### Typical flow

1. `wta_rankings` (singles) → the current top players + their `player.id`.
2. `wta_players?name=` to look someone up, or `wta_player`/`wta_player_matches`
   for a profile + match history.
3. `wta_tournaments` → a `tournamentGroup.id` + `year` → `wta_tournament` (detail),
   `wta_tournament_matches` (draws/results; AO 2025 ≈ 302 matches), or
   `wta_tournament_players` (the entry list + seeds; AO 2025 singles = 128 entrants
   with `seed`/`winner`/`runnerUp`/`eliminated`).

> Not modelled: **race-to-Finals** rankings (`type=raceSingles`) — the API returns
> 5xx for race types, so it's not a stable endpoint. There's no head-to-head, live-
> score, or stats-leaders endpoint on this API (those 404), and `countryCode` on the
> player list is silently ignored.

## Cross-provider comparison

Fills the **tennis** gap on the stats side, composing with the bookmakers' live
tennis markets:

- **`sport.rankings`** → `wta_rankings` (WTA singles/doubles).
- **`sport.fixtures_by_date`** / **`sport.match_score`** → `wta_tournament_matches`
  alongside the books' tennis fixtures + odds (Dabble, Sportsbet, Betfair, …).
- **`ref.players`** / **`stats.player_profile`** → official player catalogue + bios.

> A men's-tour (ATP) equivalent is a natural follow-up, but atptour.com is
> bot-protected (Cloudflare 403s) and doesn't expose an open API like the WTA's —
> so it's not modelled here.

## Quick test

```bash
# top 5 singles
curl -s "https://api.wtatennis.com/tennis/players/ranked?type=rankSingles&metric=singles&pageSize=5" \
  | jq '.[] | {rank: .ranking, player: .player.fullName, points}'
# Australian Open 2025 results
curl -s "https://api.wtatennis.com/tennis/tournaments/901/2025/matches" | jq '.matches | length'
```
