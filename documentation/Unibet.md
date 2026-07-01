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

### Recapturing a drifted hash

`sportsdata-mcp refresh-hashes` does **not** work here — the racing app is a
SystemJS micro-frontend whose hashes live in lazy-loaded chunks, not in a
discoverable bundle (no `hash_refresh` block in the spec). Recapture from live
traffic instead:

1. Open `https://www.unibet.com.au/racing` with devtools (or Playwright) and
   filter network requests to `rsa.unibet.com.au/api/v1/graphql`.
2. Trigger the operation — e.g. click into any race to fire `EventQuery`; the
   lobby fires `OddsLadderQuery` on load.
3. Copy `extensions.persistedQuery.sha256Hash` from the request URL and update
   the operation's `sha256` in `specs/unibet.yaml` (`graphql.operations`).

(EventQuery drifted and was recaptured this way on 2026-07-02.)

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

- `EventDetailExpertTipQuery` — **dead surface, do not chase** (investigated 2026-07-02).
  The expert-tips feature is switched off for Unibet AU (`showNewBadgePreviewAndTips:
  false` in `rsa/api/graphql/config`), so no client traffic ever registers the hash.
  The deployed racing client's own query doesn't even validate against the production
  schema (`mediaStreamFixtureId` isn't in the `EventDetailExpertTip` type), and a
  schema-fixed query registered via APQ full-text POST executes but returns
  `{viewer:{expertTips:[]}}` — no content. The gateway also does not retain APQ
  registrations across requests, so a pinned hash can never be kept alive by us.
- `LinkedEventScreenQuery` — fires on race pages alongside `EventQuery`
  (variables `eventKey, clientCountryCode, linkedEventKeys`; hash captured live
  2026-07-02: `d322aad1faedcbea7f86e14838f6ec5b9093ab536d0fab558999d3044c24e762`).
  Appears to return linked/same-meeting event context; add it if a use case shows up.
- **UI / app config** (probed, all 200 but not sports data): `rsa/api/v1/configuration/client`
  (analytics keys + internal beacon URLs), `rsa/api/graphql/config` (carousel/lobby
  display settings), `settings-api.kambicdn.com/ubau.json` + `ubau__microFrontends.json`
  (account UI links), `kambi/rewards.json` (empty loyalty rewards).
- **Non-data assets**: Kambi widget/bootstrap/router JS, `kwp-*` web config + i18n
  translations, `gameLauncher2.json`, OneTrust/geolocation, Abios esports stream config.
- Account / wagering surfaces — out of scope for a read-only data provider.
