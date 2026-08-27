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

**First check it isn't transient.** The gateway's APQ cache flaps: a hash can
return `PERSISTED_QUERY_NOT_FOUND` intermittently (some cache nodes evicted,
others not) and self-heal from organic browser traffic re-registering the pair
via the standard APQ retry. Observed 2026-07-07: `MeetingsByDateRange` failed
on 19 ingest cycles scattered across 04:18–17:09 AEST with successes in
between, then recovered — the hash never changed. Before recapturing, re-probe
the existing hash a few times (a plain GET with the spec's hash + valid
variables); if it resolves, the spec is fine and the errors were flapping.
Only recapture when the miss is persistent across probes AND the front-end
bundle actually shipped.

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
| `unibet_sgm_price` | `/onDemandPricing/event/{eventId}/outcome/{outcomeIds}.json` | **Prices a same game multi you choose.** Correlation-adjusted. See below. |

### Discovery flow (sport)

```
unibet_kambi_call(group)                                   → groupId (sport/competition tree)
unibet_kambi_call(sport_matches, {sport:"basketball"})     → eventId
unibet_kambi_call(event_betoffer, {eventId})               → all markets + prices
unibet_kambi_call(inplay)                                  → live events
  └ betOffers[].outcomes[].id                              → legs for unibet_sgm_price
```

### Same game multi pricing

`unibet_sgm_price` takes two or more outcome ids from one event and returns Unibet's
Bet Builder price for the combination — Kambi's `onDemandPricing`. No account, no key.
A plain **GET**, unlike every other book's pricer.

```
GET /offering/v2018/ubau/onDemandPricing/event/1028856020/outcome/4306981996,4309057043.json
    ?lang=en_AU&market=AU&channel_id=1

→ {"eventId": 1028856020,
   "selectedOutcomeIds": [4309057043, 4306981996],
   "selectedOdds": {"decimal": 3400, "american": "240", "fractional": "12/5"},
   "combinableOutcomeIds": [ … 939 ids … ]}
```

Outcome ids come from `unibet_kambi_call(operation="event_betoffer")` —
`betOffers[].outcomes[].id` — and go in the path joined by commas.

> **`decimal: 3400` means 3.40.** Kambi reports odds and lines in thousandths
> everywhere: an outcome at `odds: 1920` is 1.92 and `line: 1500` is +1.5. This is the
> single loudest wrong answer available in this catalogue — a price reported 1000x too
> large. Divide by 1000.

**The price is not the product of the legs.** Verified live 2026-08-27 against AFL
Western Bulldogs v Collingwood (event `1028856020`): head-to-head Bulldogs (1.92) with
Over 170.5 (1.88) prices **3.40**, against a naive 3.6096.

**Why Unibet is the best-behaved of the five.** Two properties no other book has:

1. **It echoes what it priced.** `selectedOutcomeIds` names the legs the price applies
   to. TAB tells you which legs it dropped; PointsBet tells you nothing; Unibet tells you
   the whole set. Duplicate ids are deduplicated *silently*, so this echo is how you
   notice.
2. **It refuses with a real HTTP 400 and a typed body**, rather than HTTP 200 carrying a
   zero in the price field. It is the only one of the five that needs no `error_signals`
   declaration.

| Refusal | Body | What to do |
|---|---|---|
| legs that clash or imply one another | `400 {"message":"Combination is not supported by the selected strategy."}` | drop one leg |
| a leg that is not **bet-builder eligible** | `400 {"message":"Invalid outcomes","invalidOutcomes":[…]}` | pick another market — check `combinableOutcomeIds` first |
| a combination that **cannot happen** | `409 {"message":"Impossible outcome selection","invalidOutcomes":[]}` | abandon the combination |
| an id that is not an event | `400 {"message":"Unknown event"}` | — |

The `invalidOutcomes` list being **empty on the 409** is not a bug to route around: the
impossibility is in the *combination*, so no single id is at fault. And note the second
row — an ordinary outcome straight out of the betoffer feed can be rejected this way,
which is exactly what `combinableOutcomeIds` is for.

**Three things to watch.**

1. **1001.0 is a ceiling, not a price.** Adding legs stops moving the number: six, eight,
   ten, twelve and fourteen legs all returned exactly `1001000` on the verified fixture
   while the naive product kept climbing. A capped price read as a real one looks like
   enormous edge.
2. **A single leg returns no price at all.** `selectedOdds` is simply *absent* — not an
   error, not a zero. The same happens when duplicate ids collapse to one leg.
3. **`combinableOutcomeIds` is eligibility, not compatibility.** It lists what can *ever*
   appear in a Bet Builder on this event (940 of the event's 1137 outcomes on the verified
   fixture, so it does filter), but it does **not** drop what clashes with your current
   selection: both the opposite head-to-head side and the line the head-to-head already
   implies stayed in the list, and both then 400ed. Its real use is telling an *ineligible*
   leg apart from a merely *conflicting* one, which the error message does not do.

The upstream response also repeats the event's entire bet-offer book — 626 offers, 647 KB
of a 610 KB response — which `event_betoffer` already returns. The spec projects it away
with `response_pick`, leaving ~11 KB.

## Cross-provider comparison

Unibet reuses the racing + sport capability tags, so it composes with the other
AU books via `list_tools_by_capability`:

- `racing.meetings_by_date` → `unibet_racing_call` (MeetingsByDateRange) alongside
  `tab_racing_meetings`, `sportsbet_racing_allracing`, `pointsbet_racing_meetings`.
- `racing.race_card` → `unibet_racing_call` (EventQuery) alongside `tab_racing_race`,
  `pointsbet_racing_race`, `fanduel_racing_call`.
- `sport.event_markets` → `unibet_kambi_call` (event_betoffer) alongside
  `tab_match`, `sportsbet_event_markets`, `pointsbet_event`.
- `sport.same_game_multi` + `sport.prices` → `unibet_sgm_price` alongside
  `sportsbet_sgm_price`, `tab_sgm_price`, `pointsbet_sgm_price` and `betr_sgm_price`.
  All five price a combination you choose, so the same legs can be quoted at five books
  and compared — see `docs/SGM-AND-PLACEMENT-SCOPE.md`. Remember to scale Unibet's
  thousandths before comparing.

## Placing bets — the Kambi Player API

Unibet runs on **Kambi**, so placement is Kambi's contract, not Unibet's, and it looks
nothing like the other three books. Captured live 2026-08-27 from a real 2-leg SGM the
account holder placed (the agent recorded the request; it did not place).

Two calls, both `POST`, on the **Player API** host `cf-al-auth-api.kambicdn.com` (the
`player/` path segment marks the logged-in surface, vs the anonymous `offering/` read
feed):

| Tool | Path | Auth | Purpose |
|---|---|---|---|
| `unibet_validate_coupon` | `/player/api/v2019/ubau/coupon/validate.json` | **anonymous** | pre-placement go/no-go: re-price and reject an impossible/clashing coupon |
| `unibet_place_bet` | `/player/api/v2019/ubau/coupon.json` | account (`unibet.write`) | **place a real bet with real money** |

Query on both is just `lang` / `market` / `channel_id` — no ticket, no secret in the URL.

**The coupon body** (shared by both calls):

- `couponRows[]` — one row per line. A **single** is a row whose `group` holds one leg; an
  **SGM** is ONE row with `group.operation: "COMBINATION"` and `group.groups[]` listing
  each leg's `outcomeIds[]`. `odds` on the row is the combined price **in Kambi
  thousandths** (`3400` = 3.40 — the same scaling `unibet_sgm_price` returns).
- `bets[]` — the money: `{couponRowIndexes, eachWay, stake}`, `stake` in major units
  (`1` = $1).
- `allowOddsChange` / `allowOddsChangeLive` / `allowOddsChangePreMatch` — the drift policy.
- `requestId` (client-generated per attempt), `channel` (`"Internet"`), and `trackingData`
  (analytics; `selectedOutcomes[]` mirrors the legs, not load-bearing).

**Verified vs not.** The request *shape* above is verbatim from a successful browser
placement. What was **not** done: a **headless** placement — driving `coupon.json` from
outside the browser with only the session cookie — because that moves real money. So
`unibet_place_bet` is **shape-verified but auth-unverified**; confirm one controlled
minimum-stake bet before trusting it. On rejection Kambi returns `{status, message}`
(seen live on `validate.json`), and **HTTP 200 is not proof** — read `status` in the body,
as with Entain. `requestId` is not a proven idempotency key, so **never retry** a timed-out
placement; confirm by reading the account instead.

### Authentication — `Authorization: Bearer`, corrected 2026-08-27

Kambi authenticates the punter with **`Authorization: Bearer <uuid>`**, observed on a live
request (`POST coupon/validate.json` → 200, `validSession: true`). The token is an opaque
UUID, not a JWT, so its expiry cannot be read locally — a dead one surfaces as a 401.
Supply it via `UNIBET_ACCESS_TOKEN`.

> **This page previously said the credential was a session cookie on `.kambicdn.com`.**
> That was an inference — no bearer was visible in Unibet's own storage, and the path
> carries a `player/` segment — and it was never checked against the request, because the
> capture recorder redacted every `authorization|cookie|token` header to a length. The
> clue that should have caught it: Kambi is a **cross-origin** host
> (`Sec-Fetch-Site: cross-site`), and a browser does not send cookies there by default.

Because pricing/validation is anonymous (verified: `validate.json` answered **400, not
401**, cross-origin with no credential), only the actual placement needs the token — the
go/no-go check works with no login at all.

### The coupon body, as observed

```json
{"couponRows":[{"index":0,"odds":3300,
  "group":{"operation":"AND","groups":[
    {"operation":"AND","outcomeIds":[4306981997]},
    {"operation":"AND","outcomeIds":[4309036845]}]},
  "type":"BET_BUILDER"}],
 "bets":[{"couponRowIndexes":[0],"eachWay":false}],
 "isUserLoggedIn":true}
```

`operation` is **`"AND"`** and `type` is **`"BET_BUILDER"`** — both were guessed as
`"COMBINATION"` in the first version of this page. `odds` is thousandths (3300 = 3.30).
Validate carries **no `stake`**; adding it is what makes the same body a placement. The
guessed `allowOddsChange` / `requestId` / `channel` fields do **not** appear on the
verified request.

### What validate answers

```json
{"status":"SUCCESS","validSession":true,"rewardInfo":{...}}
```

**It does not echo a price.** There are no `couponRows` in the reply, so this call cannot
check drift — use `unibet_sgm_price` for that. `validSession` is the cheapest way to tell
a dead token from a bad coupon. `rewardInfo.validGroupRewards[]` lists applicable
promotions (a `PROFIT_BOOST` was live on the verified call); a boost changes the payout,
not the odds struck, so it must not feed a price comparison. Rate limits ride in
`x-ratelimit-remaining` / `x-ratelimit-reset`.

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
