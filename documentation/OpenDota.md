# OpenDota API Documentation

Reference for **`api.opendota.com/api`** — Dota 2 match data and derived analytics.
Free tier: **60 requests/minute, 50k/month, no key**. Probed live 2026-08-10.

The server's first esports provider.

## Size is the main constraint

Several endpoints return multi-megabyte documents. One is **deliberately not modelled**:

| Endpoint | Size | Status |
|---|---|---|
| `/proPlayers` | ~4.4 MB | **Not exposed** — every registered pro, almost never what you wanted |
| `/leagues` | ~1.0 MB | Exposed, flagged — filter by `tier` client-side |
| `/matches/{id}` | ~250 KB | Exposed — per-player, per-minute detail |
| `/teams` | ~250 KB | Exposed |
| `/heroStats` | ~165 KB | Exposed |

If a client's context is tight, cap this provider with
`providers.opendota.max_response_bytes`.

## Two id conventions that cause silent errors

**`account_id` is the Steam 32-bit id**, not the 64-bit `steamid` from a Steam profile
URL. A player object carries both: `profile.account_id` (32-bit — what every endpoint
here takes) and `profile.steamid` (64-bit). Passing the 64-bit one returns an empty
profile rather than an error.

**Sides are Radiant and Dire**, not home/away. In a match, `player_slot < 128` means
Radiant. So a player won when:

```python
(player_slot < 128) == radiant_win
```

Getting that backwards silently inverts every win rate you compute.

## Reading hero stats

`opendota_hero_stats` has no win-rate field. It has **paired counts per skill
bracket**, with numeric key prefixes (`1` lowest … `8` highest):

```jsonc
{"localized_name": "Anti-Mage", "pro_pick": 412, "pro_win": 201,
 "1_pick": 90210, "1_win": 45102, ... "8_pick": 5121, "8_win": 2707}
```

Win rate is `<n>_win / <n>_pick`. Comparing raw `_win` counts across brackets tells you
about bracket population, not hero strength.

`rank_tier` on a player is likewise two digits: tens = medal (1 Herald … 8 Immortal),
units = star. `75` is Divine 5.

## Tools

### `opendota.reference`

| Tool | Returns | Capability |
|---|---|---|
| `opendota_heroes` | Hero catalogue (~127) | `ref.players` |
| `opendota_hero_stats` | Pick/win counts per skill bracket | `stats.advanced_metrics` |
| `opendota_teams` | Pro teams by rating | `ref.teams` |
| `opendota_leagues` | Every league (~1 MB) | `sport.competitions_list` |

### `opendota.matches`

| Tool | Returns | Capability |
|---|---|---|
| `opendota_pro_matches` | Recent pro matches | `sport.fixtures_by_date`, `sport.match_score` |
| `opendota_match` | One match in full (~250 KB) | `sport.match_detail`, `sport.match_boxscore`, `stats.player_match` |
| `opendota_public_matches` | Ladder matches, hero ids only | `sport.match_score` |

### `opendota.players`

| Tool | Returns | Capability |
|---|---|---|
| `opendota_player` | Profile, rank tier, MMR estimate | `stats.player_profile` |
| `opendota_player_matches` | Recent matches with KDA | `stats.player_game_log` |
| `opendota_player_winloss` | Win/loss totals | `stats.player_season` |
| `opendota_player_heroes` | Hero pool and performance | `stats.player_career` |

Pagination on `opendota_pro_matches` is backwards-only: pass `less_than_match_id` with
the lowest id you've seen to walk into the past. There is no page number.

## Gotchas

| Symptom | Cause |
|---|---|
| **Empty player profile** | You passed a 64-bit `steamid`. Use the 32-bit `account_id`. |
| **Win rates look inverted** | `player_slot < 128` is Radiant; compare it to `radiant_win`. |
| **No win-rate field on heroes** | Compute `<n>_win / <n>_pick` per bracket. |
| **Huge response** | See the size table. `proPlayers` is not exposed for this reason. |
| **HTTP 429** | 60/min free tier. The provider is capped at 1 rps sustained. |
| **Missing player names in a match** | Anonymous accounts return `account_id: null`. Normal for public matches. |
| **`opendota_player_matches` returns everything** | Pass `limit`; unfiltered it's the player's whole history. |

## Cross-provider comparison

- `sport.match_score` / `sport.fixtures_by_date` → `opendota_pro_matches` alongside the
  traditional-sport fixture tools, so "what's on" can include esports.
- `stats.player_game_log` → `opendota_player_matches` alongside
  `chesscom_monthly_games` and the NHL/MLB game logs.
- `sport.competitions_list` → `opendota_leagues` alongside the bookmakers' competition
  trees. Several AU books price Dota 2 — pairing an OpenDota match with a book's
  esports market is the natural composition here.
- Ids are Dota-specific (Steam account ids, hero ids) and don't join to anything else
  in the catalogue.

## Not modelled

- **`/proPlayers`** — 4.4 MB (see above).
- **`/explorer`** — arbitrary SQL over OpenDota's database. Powerful, but accepting
  free-form SQL from a model is not something a read-only server should expose.
- **`/request/{match_id}`** — POSTs a parse job. This server is read-only.
- **Benchmarks, distributions, scenarios** — niche analytics, low value next to the
  match and player surfaces.
