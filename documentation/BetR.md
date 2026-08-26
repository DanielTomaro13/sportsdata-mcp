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
| `betr_sgm_price` | `POST /SameGameMultiPrice` | `sport.same_game_multi`, `sport.prices` |
| `betr_statwars_events` | `/StatwarsMasterEvents` | — |

### Discovery flow (sport)

```
betr_event_types                                  → EventTypeId (e.g. 107)
betr_master_category(EventTypeId=107)             → CategoryId (e.g. 39251 = NBA)
betr_sports_category(CategoryId=39251)            → events + markets
betr_pop_sgm_bet_data(MasterEventId, CategoryId)  → same-game-multi suggestions
betr_master_event(MasterEventId=2255977)          → Events[].EventId + Outcomes[].OutcomeId
  └ those two + MarketTypeCode                    → legs for betr_sgm_price
```

### Same game multi pricing

`betr_sgm_price` takes two or more selections from one match and returns BetR's own
correlation-adjusted price. No account, no key.

```
POST https://web20-api.bluebet.com.au/SameGameMultiPrice
{"MasterEventID": 2255977,
 "Markets": [{"EventId": 91686300, "OutcomeId": 1,     "MarketType": "WIN"},
             {"EventId": 91712212, "OutcomeId": 13910, "MarketType": "WIN"}]}

→ {"Price": 2.2, "ErrorNo": 0}
```

That is the whole success body — there is no echo of the legs.

Leg ids come from `betr_master_event`. Note that **`EventId` is a market group, not the
match**: on the verified fixture `91686300` is "Match Result" and `91712212` is "Total
Points", both inside MasterEventId `2255977`. `OutcomeId` is that group's own
`Outcomes[].OutcomeId`, and `MarketType` is the outcome's `MarketTypeCode`.

**The price is not the product of the legs.** Verified live on 2026-08-27 against AFL
Western Bulldogs v Collingwood, where the adjustment ran both directions:

| Combination | Naive product | BetR | Adjustment |
|---|---|---|---|
| Bulldogs (1.95) + Under 139.5 (6.25) | 12.19 | **11.00** | −9.7% |
| Bulldogs (1.95) + Over 179.5 (2.60) | 5.07 | **4.80** | −5.3% |
| Bulldogs (1.95) + Over 139.5 (1.10) | 2.145 | **2.20** | +2.6% |
| Bulldogs (1.95) + Under 201.5 (1.10) | 2.145 | **2.25** | +4.9% |

**Do not send `FixedWin`.** This is the one that matters. The site includes the leg's
price in each market object, and the server treats it as a **floor on the answer**:

```
… "FixedWin": 99.0 …   → {"Price": 99.0, "ErrorNo": 0}
… "FixedWin": 5.0  …   → {"Price": 5.0,  "ErrorNo": 0}
… "FixedWin": 1.01 …   → {"Price": 2.2,  "ErrorNo": 0}   ← below the real price, ignored
… omitted           →   {"Price": 2.2,  "ErrorNo": 0}
```

A wrong price in the request is a wrong price in the response, reported as a clean
success. With honest values the floor never binds — a two-leg multi always pays more than
its best leg — so omitting the field costs nothing and removes the failure mode entirely.
The spec does not expose it.

**Three more things to know.**

1. **`MarketType` is required but unvalidated.** Drop it and the verified pair returns
   `{"Price": 21, "ErrorNo": 0}` instead of 2.20 — a wrong answer, not an error. It is the
   second silent-wrongness path in this endpoint, and the reason to copy the outcome's own
   fields rather than assemble legs by hand.
2. **`MasterEventID` is ignored.** Omitting it, sending `0`, and misspelling the key all
   returned the same price. It does not scope or validate the legs; cross-match legs are
   caught by the leg resolver instead. Note the capital `D`, which differs from
   `MasterEventId` on every other BetR endpoint.
3. **BetR refuses a redundant leg rather than dropping it** — the safe behaviour, and the
   opposite of TAB's and PointsBet's. You cannot end up holding a shorter bet than you
   asked for. But `ErrorNo 4527` is a **catch-all** whose wording names one of its three
   causes: a leg another leg implies, the same leg twice, and legs from two different
   matches all come back as `Invalid price response - redundant leg in bet`.

Error codes seen live, all at HTTP 200 (the spec declares an `error_signals` rule on
`ErrorNo` so `Price: 0` never reaches a caller as a quote):

| `ErrorNo` | Meaning |
|---|---|
| `0` | success |
| `4500` | fewer than two legs — unlike Sportsbet and PointsBet, BetR will not price one |
| `4503` | a leg could not be resolved, usually a missing `EventId` or `OutcomeId` |
| `4526` | impossible combination (Over 139.5 with Under 139.5) |
| `4527` | redundant leg, duplicate leg, or legs from different matches |

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
- `sport.same_game_multi` + `sport.prices` → `betr_sgm_price` alongside
  `sportsbet_sgm_price`, `tab_sgm_price` and `pointsbet_sgm_price`. All four price a
  combination you choose, so the same legs can be quoted at four books and compared —
  see `docs/SGM-AND-PLACEMENT-SCOPE.md`.

## Not modelled

- `betr.com.au/_next/data/{buildHash}/…json` — Next.js SSR blobs keyed by a per-deploy
  build hash (fragile); the `web20-api` endpoints serve the same data.
- The `FixedWin`, `BetDetailTypeCode`, `MarketTypeDesc`, `GroupByHeader`, `Points`,
  `FixedMarketId` and `OutcomeName` fields the site sends on every SGM leg. All were
  verified to have no effect on the price except `FixedWin`, whose only effect is to make
  a wrong answer possible — see above.
- `home/FeatureFlags` (config), `bluebet.azureedge.net/jersey-mapping` (silk images),
  `events.betr.com.au/flags` + Evergage analytics — not sports data.
- Account / wagering surfaces — out of scope for a read-only data provider.
