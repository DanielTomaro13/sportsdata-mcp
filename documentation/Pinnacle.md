# Pinnacle API Documentation

Unofficial reference for Pinnacle's **Arcadia "guest" API** —
`guest.api.arcadia.pinnacle.com/0.1`, the same open feed the pinnacle.com web
sportsbook reads. Anonymous, no key. Verified against live traffic (probed
2026-06-05). **Sports only** — Pinnacle is a sharp-odds sportsbook, no racing.

> Most endpoints return a **top-level JSON array**. Prices are **American odds**
> (e.g. `-128`, `+105`). The provider sends Pinnacle's public web-client
> **`X-API-Key`** (hardcoded in their front-end, not a user secret), which unlocks
> the full `/sports/{id}/matchups` and `/leagues/{id}/matchups` lists and the
> parlay markets — all of which 401 without it.

## Host

| Host | Role |
|---|---|
| `guest.api.arcadia.pinnacle.com/0.1` | The Arcadia guest API — sports, leagues, matchups, markets, reference. |

## Conventions

- **`sportId`** is an integer (e.g. 3 Baseball, 4 Basketball, 29 Soccer); from
  `pinnacle_sports`.
- **`matchupId`** is an integer; from any matchups feed (`pinnacle_sport_matchups`,
  `pinnacle_carousel`, …). Only matchups with `hasMarkets: true` have prices.
- **Market `key`** encodes the market, e.g. `s;1;tt;2.5;home` (segment/period +
  type `m` moneyline / `s` spread / `tt` team-total, line, side).
- **`price`** is American odds; `points` is the line (spread/total).

---

## Sports + matchups + markets — group `pinnacle.sports`

| Tool | Path | Capability |
|---|---|---|
| `pinnacle_sports` | `/sports` | `sport.competitions_list` |
| `pinnacle_sports_live` | `/sports/live` | `sport.in_play` |
| `pinnacle_sport_leagues` | `/sports/{sportId}/leagues` | `sport.competitions_list` |
| `pinnacle_sport_matchups` | `/sports/{sportId}/matchups/highlighted` | `sport.competition_screen` |
| `pinnacle_sport_matchups_all` | `/sports/{sportId}/matchups` | `sport.competition_screen` (full list, not just highlighted) |
| `pinnacle_league_matchups` | `/leagues/{leagueId}/matchups` | `sport.competition_screen` (every game in a competition) |
| `pinnacle_sport_matchups_live` | `/sports/{sportId}/matchups/live` | `sport.in_play` |
| `pinnacle_league_matchups_live` | `/leagues/{leagueId}/matchups/live` | `sport.in_play` |
| `pinnacle_carousel` | `/matchups/carousel` | — (featured) |
| `pinnacle_matchup` | `/matchups/{matchupId}` | `sport.match_detail` |
| `pinnacle_matchup_related` | `/matchups/{matchupId}/related` | — |
| `pinnacle_matchup_markets` | `/matchups/{matchupId}/markets/related/straight` | `sport.event_markets`, `sport.prices` |
| `pinnacle_matchup_parlay_markets` | `/matchups/{matchupId}/markets/related/parlay` | `sport.same_game_multi` |

### Discovery flow (odds)

```
pinnacle_sports           → sportId (e.g. 3 Baseball)
pinnacle_sport_matchups(sportId)            → matchupId (where hasMarkets=true)
pinnacle_matchup_markets(matchupId)         → straight markets + American-odds prices
  └ pinnacle_matchup(matchupId)             → participants, league, periods, start time
```

## Reference — group `pinnacle.reference`

| Tool | Path | Notes |
|---|---|---|
| `pinnacle_enums` | `/enums` | Countries, currencies, languages, timezones, … |
| `pinnacle_labels` | `/labels` | Per-sport market-label dictionary — **decodes the market `key`s** (moneyline → "Match Odds", etc.). |
| `pinnacle_teasers` | `/teasers` | Teaser bet definitions by sport group + team count. |
| `pinnacle_status` | `/status` | API system status + per-service health. |

## Cross-provider comparison

Pinnacle's sharp prices are valuable to compare against the other books via
`list_tools_by_capability`:

- `sport.event_markets` / `sport.prices` → `pinnacle_matchup_markets` alongside
  `tab_match`, `pointsbet_event`, `unibet_kambi_call`, `betr_sports_category`,
  `sportsbet_event_markets`, `fanduel_sb_call`.
- `sport.in_play` → `pinnacle_sports_live` / `pinnacle_sport_matchups_live` alongside
  the other books' in-play feeds.

## Not modelled

- `/matchups/{id}/markets/straight` (and `…/parlay` without `related`) — strict
  subsets of the modelled `…/markets/related/{straight,parlay}`, so not duplicated.
  (`/matchups/{id}/markets/related` with no `straight`/`parlay` suffix is invalid —
  the API requires one.)
- `pinnacle.com/config/*.json`, `/translations/*`, device/location/time/dataVersion
  endpoints — app config / infra, not sports data.
- Account / wagering surfaces — out of scope for a read-only data provider.
