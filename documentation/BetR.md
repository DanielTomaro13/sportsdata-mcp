# BetR (Australia) API Documentation

Unofficial reference for the anonymous JSON endpoints behind BetR. **BetR runs on
the BlueBet platform**, so the data API is `web20-api.bluebet.com.au` (no auth, no
key). Verified against live traffic (probed 2026-06-04).

> The `betr.com.au` front-end also serves Next.js `_next/data/{buildHash}/…json`
> blobs, but those are keyed by a per-deploy build hash (e.g. `UnYxgFIN9Z_…`) and
> carry the same data as the API — so only the stable `web20-api.bluebet.com.au`
> surface is modelled here.

## Host

| Host | Role |
|---|---|
| `web20-api.bluebet.com.au` | The BlueBet/BetR data API — racing, sport, promotions. |

## Conventions

- **Racing** is keyed by integer `EventId` (e.g. `88521917`); resolve current ids
  from `betr_next5_races`, `betr_grouped_racecard`, or `betr_todays_races`.
- **Sport** is a tree: `EventTypeId` (e.g. 107 Basketball, 101 AFL) → `CategoryId`
  (a competition, e.g. 39251 NBA) → events (`MasterEventId`). `betr_event_types`
  lists the event types; `betr_master_category` / `betr_sports_category` drill in.
- Times are ISO-8601 UTC. No auth.

---

## Racing — group `betr.racing`

| Tool | Path | Capability |
|---|---|---|
| `betr_next5_races` | `/Next5Races` | `racing.next_to_jump` |
| `betr_todays_races` | `/TodaysRacesForHomePageV2` | — |
| `betr_grouped_racecard` | `/GroupedRaceCard?DaysToRace=` | `racing.meetings_by_date` |
| `betr_race` | `/Race?eventId=` | `racing.race_card` |
| `betr_race_form` | `/RaceForm?EventId=` | — (form guide) |
| `betr_race_flucs` | `/flucs?EventId=` | — (price fluctuations) |
| `betr_market_movers` | `/MarketMovers` | — |
| `betr_fav4` | `/Fav4?EventTypeFilter=` | — |

### Discovery flow (racing)

```
betr_next5_races / betr_grouped_racecard(DaysToRace=0)   → EventId
betr_race(eventId)                                        → runners, prices, bet types
betr_race_form(EventId) / betr_race_flucs(EventId)        → form + price history
```

## Sport — group `betr.sport`

| Tool | Path | Capability |
|---|---|---|
| `betr_event_types` | `/EventTypes` | `sport.competitions_list` |
| `betr_master_category` | `/MasterCategory?EventTypeId=` | `sport.competition_screen` |
| `betr_sports_category` | `/SportsCategory?CategoryId=` | `sport.event_markets`, `sport.competition_screen` |
| `betr_master_event` | `/MasterEvent?MasterEventId=` | `sport.match_detail` (one match's header) |
| `betr_pop_sgm_category` | `/PopSGMCategory` | `sport.same_game_multi` |
| `betr_pop_sgm_bet_data` | `/PopSGMBetData?MasterEventId=` | `sport.same_game_multi` |
| `betr_statwars_events` | `/StatwarsMasterEvents` | — |

### Discovery flow (sport)

```
betr_event_types                                  → EventTypeId (e.g. 107)
betr_master_category(EventTypeId=107)             → CategoryId (e.g. 39251 = NBA)
betr_sports_category(CategoryId=39251)            → events + markets
betr_pop_sgm_bet_data(MasterEventId, CategoryId)  → same-game-multi suggestions
```

## Content — group `betr.content`

| Tool | Path | Capability |
|---|---|---|
| `betr_promotions` | `/UserContentfulPromotionsWithMetaData` | `content.promo` |
| `betr_all_promotions` | `/ContentfulVisibleAllPromotions` | `content.promo` |
| `betr_featured_racing` | `/ContentfulFeaturedEventRacing` | — |
| `betr_popular_market_links` | `/PopularMarketLinks` | — |

## Cross-provider comparison

BetR reuses the racing + sport capability tags, so it composes with the other AU
books via `list_tools_by_capability`:

- `racing.race_card` → `betr_race` alongside `tab_racing_race`, `pointsbet_racing_race`,
  `unibet_racing_call`, `sportsbet_racecard`.
- `racing.meetings_by_date` → `betr_grouped_racecard` alongside `tab_racing_meetings`,
  `pointsbet_racing_meetings`, `unibet_racing_call`, `sportsbet_racing_allracing`.
- `sport.event_markets` → `betr_sports_category` alongside `tab_match`, `unibet_kambi_call`,
  `pointsbet_event`, `sportsbet_event_markets`.

## Not modelled

- `betr.com.au/_next/data/{buildHash}/…json` — Next.js SSR blobs keyed by a per-deploy
  build hash (fragile); the `web20-api` endpoints serve the same data.
- `home/FeatureFlags` (config), `bluebet.azureedge.net/jersey-mapping` (silk images),
  `events.betr.com.au/flags` + Evergage analytics — not sports data.
- Account / wagering surfaces — out of scope for a read-only data provider.
