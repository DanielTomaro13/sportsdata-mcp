# Unibet (Australia) API Documentation

Unofficial reference for the anonymous JSON endpoints behind Unibet AU. Verified
against live traffic (probed 2026-06-04). Two surfaces under one provider:

- **Racing** (`unibet.racing`) — **persisted-query GraphQL** at
  `rsa.unibet.com.au/api/v1/graphql` (the model sends an operation name + variables;
  the sha256 hash lives in the spec).
- **Sport** (`unibet.sport`) — the **Kambi** offering API (`*.kambicdn.com`), the
  same open REST feed the Unibet web sportsbook reads. Market `AU`, channel `1`.

> **No auth, no API key.** The racing GraphQL enforces Apollo **CSRF** protection,
> so a non-simple `Content-Type: application/json` header is required — carried in
> `provider.default_headers` (harmless on Kambi). Persisted-query hashes can drift
> when the front-end bundle ships; a `PERSISTED_QUERY_NOT_FOUND` error means a hash
> needs recapturing.

## Hosts

| Host | Role |
|---|---|
| `rsa.unibet.com.au/api/v1/graphql` | Racing persisted-query GraphQL. |
| `ap.offering-api.kambicdn.com/offering/v2018/ubau` | Kambi sport offering (groups, events, bet offers). |
| `ap1.offering-api.kambicdn.com` | Kambi live statistics. |
| `eu-offering-api.kambicdn.com` | Kambi odds-ladder reference. |

## Racing — `unibet_racing_call` (group `unibet.racing`)

A `graphql_persisted` dispatcher. Race identifiers are **`eventKey`s** like
`202606040200.T.AUS.hawkesbury.1` (`date.raceType.country.track.raceNumber`).
Browse `unibet://racing/operations`.

| Operation | Variables | Returns | Capability |
|---|---|---|---|
| `MeetingsByDateRange` | `startDateTime, endDateTime, countryCodes, clientCountryCode, raceTypes` | Meetings (+ their events) in a date range. | `racing.meetings_by_date` |
| `EventQuery` | `clientCountryCode, eventKey, fetchTRC` | One race's card — runners, prices, markets. | `racing.race_card` |
| `FormQuery` | `eventKey` | Form guide for a race. | — |
| `FuturesQuery` | *(none)* | Futures / ante-post markets. | `racing.futures` |
| `SpecialsQuery` | `locationClass` | Specials markets. | — |
| `OddsLadderQuery` | `skipCodePromotion, codeDefault, codePromotion` | The odds-ladder config. | — |

Dispatcher capabilities: `racing.meetings_by_date`, `racing.race_card`, `racing.futures`.

### Discovery flow (racing)

```
unibet_racing_call(MeetingsByDateRange, {startDateTime, endDateTime, countryCodes:"AUS",
                   clientCountryCode:"AU", raceTypes:["T"]})   → eventKey
unibet_racing_call(EventQuery, {clientCountryCode:"AU", eventKey, fetchTRC:false})  → race card
unibet_racing_call(FormQuery, {eventKey})                       → form guide
```

## Sport — `unibet_kambi_call` (group `unibet.sport`)

A `templated_rest` dispatcher over the Kambi offering API; `lang=en_AU`,
`market=AU`, `channel_id=1` default. Browse `unibet://sport/operations`.

| Operation | Path | Notes |
|---|---|---|
| `group` | `/group.json` | Full sport → competition tree (event counts per node). |
| `highlights` | `/group/highlight.json` | Featured groups (Unibet Featured, odds boosts, popular leagues). |
| `group_events` | `/group/{groupId}.json` | Events under one group id. |
| `sport_matches` | `/listView/{sport}/all/all/all/matches.json` | Match-list for a sport slug (`basketball`, `football`, …). |
| `sport_category` | `/category/pre_match_event,selected_pre_match/sport/{sport}.json` | Pre-match events for a SPORT enum (`FOOTBALL`, `ICE_HOCKEY`, …). |
| `inplay` | `/listView/all/all/all/all/in-play.json` | All events currently in-play. |
| `event_betoffer` | `/betoffer/event/{eventId}.json` | All bet offers (markets + outcomes + prices) for one event. |
| `event_prepack` | `/prepackcoupon/event/{eventId}.json` | Bet Builder pre-pack coupons (same-game multis) for one event. |

Dispatcher capabilities: `sport.competitions_list`, `sport.competition_screen`,
`sport.event_markets`, `sport.in_play`, `sport.same_game_multi`.

| Discrete tool | Host / Path | Notes |
|---|---|---|
| `unibet_kambi_live_stats` | `ap1` `/statistics/api/ubau/liveStatistics/event/{eventId}.json` | Live in-event statistics. |
| `unibet_kambi_odds_ladder` | `eu` `/offering/v2018/kambi/oddsLadder.json` | Decimal-odds increment ladder. |

### Discovery flow (sport)

```
unibet_kambi_call(group)                                   → groupId (sport/competition tree)
unibet_kambi_call(sport_matches, {sport:"basketball"})     → eventId
unibet_kambi_call(event_betoffer, {eventId})               → all markets + prices
unibet_kambi_call(inplay)                                  → live events
```

## Cross-provider comparison

Unibet reuses the racing + sport capability tags, so it composes with the other
AU books via `list_tools_by_capability`:

- `racing.meetings_by_date` → `unibet_racing_call` (MeetingsByDateRange) alongside
  `tab_racing_meetings`, `sportsbet_racing_allracing`, `pointsbet_racing_meetings`.
- `racing.race_card` → `unibet_racing_call` (EventQuery) alongside `tab_racing_race`,
  `pointsbet_racing_race`, `fanduel_racing_call`.
- `sport.event_markets` → `unibet_kambi_call` (event_betoffer) alongside
  `tab_match`, `sportsbet_event_markets`, `pointsbet_event`.

## Not modelled

- `EventDetailExpertTipQuery` — captured hash has **drifted** (`PERSISTED_QUERY_NOT_FOUND`);
  re-capture from the live bundle to add it.
- **UI / app config** (probed, all 200 but not sports data): `rsa/api/v1/configuration/client`
  (analytics keys + internal beacon URLs), `rsa/api/graphql/config` (carousel/lobby
  display settings), `settings-api.kambicdn.com/ubau.json` + `ubau__microFrontends.json`
  (account UI links), `kambi/rewards.json` (empty loyalty rewards).
- **Non-data assets**: Kambi widget/bootstrap/router JS, `kwp-*` web config + i18n
  translations, `gameLauncher2.json`, OneTrust/geolocation, Abios esports stream config.
- Account / wagering surfaces — out of scope for a read-only data provider.
