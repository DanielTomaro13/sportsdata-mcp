# Sportsbet API Documentation

Unofficial reference for the JSON endpoints served under `www.sportsbet.com.au/apigw/*`. Every endpoint, parameter, and response field in this document has been verified against live traffic (probed 2026-05-25). Field shapes are reproduced from the wire — fields that were not observed are not invented.

> **Base URL:** `https://www.sportsbet.com.au/apigw`
> All endpoints are `GET` unless explicitly marked otherwise. Public read endpoints accept anonymous requests and return `application/json`. Auth/wallet/CIAM endpoints are listed for completeness but not documented in detail (they require session state).

---

## Table of Contents

- [Service Map](#service-map)
- [Conventions](#conventions)
  - [IDs & enums observed on the wire](#ids--enums-observed-on-the-wire)
  - [Status codes](#status-codes)
  - [Price object](#price-object)
  - [Time format](#time-format)
  - [`topicLink` and `httpLink`](#topiclink-and-httplink)
  - [Error responses](#error-responses)
- [Racing endpoints](#racing-endpoints)
  - [AllRacing](#allracing)
  - [Event Meeting](#event-meeting)
  - [Racecard](#racecard)
  - [RacecardWithContext](#racecardwithcontext)
  - [MultipleRacecards](#multipleracecards)
  - [Competition (meeting summary)](#racing-competition-meeting-summary)
  - [ResultedEvents (racing)](#racing-resultedevents)
  - [Futures](#racing-futures)
  - [BestBets](#bestbets)
  - [BestBetsWithEvents](#bestbetswithevents)
  - [JockeyHub / TopJockeys](#jockeyhub--topjockeys)
  - [Challenges/All](#challengesall)
  - [Megabets](#megabets)
  - [RacingMultisEvents](#racingmultisevents)
  - [PopularSrms](#popularsrms)
- [Sport endpoints](#sport-endpoints)
  - [UpComingEvents](#upcomingevents)
  - [Sports Classes (active window)](#sports-classes-active-window)
  - [NavHierarchy](#navhierarchy)
  - [BetLive](#betlive)
  - [Event Commentary](#event-commentary)
  - [SportsCardOrResultedEvent](#sportscardorresultedevent)
  - [SportCard (legacy)](#sportcard-legacy)
  - [Event Markets](#event-markets)
  - [Event Results](#event-results)
  - [Competition](#sport-competition)
  - [Competition / Events / Matches](#competition--events--matches)
  - [Competition / Events / Outrights](#competition--events--outrights)
  - [Competition / ResultedEvents](#competition--resultedevents)
  - [Class Coupon flag](#class-coupon-flag)
- [Results browser](#results-browser)
  - [Results / Classes](#results--classes)
  - [Results / Sports / Classes / Competitions](#results--sports--classes--competitions)
- [Sports-form](#sports-form)
  - [event-status](#event-status)
  - [league-ladder-status](#league-ladder-status)
- [Media / Nomad](#media--nomad)
  - [trackreport](#trackreport)
  - [racePreview](#racepreview)
  - [matchPreview](#matchpreview)
- [Trending / Personalisation](#trending--personalisation)
  - [trendingsgm/event](#trendingsgmevent)
  - [preferred-promotions trending](#preferred-promotions-trending)
- [Page content](#page-content)
  - [homepage/sports](#homepagesports)
  - [homepage/racing](#homepageracing)
  - [safer_gambling_message](#safer_gambling_message)
- [CMS](#cms)
  - [cms/app/page](#cmsapppage)
  - [cms/app/settings](#cmsappsettings)
  - [cms/app/messages](#cmsappmessages)
  - [Other CMS endpoints](#other-cms-endpoints)
- [GraphQL gateway](#graphql-gateway)
- [Product catalogue](#product-catalogue)
- [Authentication & wallets (not documented)](#authentication--wallets-not-documented)
- [Endpoint quick reference](#endpoint-quick-reference)

---

## Service Map

The `/apigw/` prefix fronts an API gateway that routes by sub-path to discrete back-end services:

| Sub-path | Service | Purpose |
|---|---|---|
| `sportsbook-racing/...` | Racing service | Racecards, meetings, futures, jockey hub, tips |
| `sportsbook-sports/...` | Sports service | Sport events, markets, results, navigation |
| `sportsbook-results/...` | Results service | Resulted browser |
| `sports-form/...` | Form/stats service | Event status, ladder URLs (uses GTG iSportGenius as upstream) |
| `media/nomad/...` | Editorial content service | Track reports, previews, video |
| `cms/app/...` | CMS | Pages, menus, settings, promo cards |
| `page-content/...` | Page-content service | Homepage layout JSON |
| `trendingsgm/...` | Trending SGM service | Popular Same-Game Multis (sport) |
| `preferred-promotions/...` | Promotions personalisation | Per-user/anonymous promo lists |
| `sportsbook/graph` | GraphQL gateway | Apollo persisted queries |
| `sportsbook-product-catalog/...` | Product catalogue | Pricing metadata |
| `auth/...`, `ciam*/...` | Identity | Auth / CIAM flows |
| `wallets/...` | Payments | Card/wallet operations |

---

## Conventions

### IDs & enums observed on the wire

#### Class IDs

| `classId` | `className` | `groupName` |
|---|---|---|
| 1 | Horses - Aus/NZ | Racing |
| 2 | Horses - International | Racing |
| 4 | Greyhound Racing | Racing |
| 5 | Horse Racing: Futures - AUS/NZ | Racing |
| 108 | Jockey Challenge | Racing |
| 112 | Greyhound Racing | Racing |
| 161 | Racing Extras | Racing |
| 8 | Golf | Sports |
| 9 | Motor Racing | Sports |
| 13 | Tennis | Sports |
| 14 | Darts | Sports |
| 16 | Basketball - US | Sports |
| 17 | American Football | Sports |
| 18 | Baseball | Sports |
| 25 | Cricket | Sports |
| 29 | Soccer | Sports |
| 37 | GAA Matches | Sports |
| 38 | Ice Hockey - US | Sports |
| 58 | Handball | Sports |
| 61 | Volleyball | Sports |
| 63 | Basketball - Aus/Other | Sports |
| 64 | Ice Hockey - Other | Sports |
| 71 | UFC - MMA | Sports |
| 81 | Table Tennis | Sports |
| 206 | e-Sports | Sports |
| 443 | e-Basketball | Sports |
| 455 | e-Soccer | Sports |

> Source: `/apigw/sportsbook-results/Sportsbook/Results/Classes?date=today` plus observed events. Sportsbet also exposes rugby league, AFL, etc.; those classIds were not in today's results sample.

#### `bettingStatus`

Observed values: `PRICED`, `OFF`. (`OFF` is used for in-running and suspended-pricing events.)

#### `statusCode` (selection / market)

| Code | Meaning |
|---|---|
| `A` | Active / available |
| `B` | (Race) bookmaker priced — appears on resulted-but-pending races |
| `W` | Winner / settled-won |
| `R` | Resulted (when seen on a market) |

> Observed values only. Additional codes likely exist for losing/voided selections; they were not present in the sampled payloads.

#### `eventSort`

Observed values: `MTCH` (match), `GRP1`/`GRP2`/...` (futures groupings). Drives front-end card layout.

#### `marketSort`

Compact two-character market-classification code. Examples observed:

| `marketSort` | Meaning |
|---|---|
| `HH` | Head to Head |
| `--` | Generic / no special sort |
| `RH` | Racing Head-to-Head |
| `RO` | Odds vs Evens |
| `EX` | Exotic (Diamond in the Roughies, Back the Field) |
| `I2`, `I3` | Insure 2 / Insure 3 |
| `WO` | Betting Without |

#### `priceCode`

Observed on selection `prices[]`:

| Code | Meaning |
|---|---|
| `L` | Live (current) price — sport markets |
| `MDP` | Mid-Day Price — racing |
| `TMD` | Top of Mid-Day — racing |
| `T` | Tote (in `availablePriceTypes` strings) |
| `S`, `R`, `G`, `V`, `P`, `M`, `E` | Power Play promo price-codes (seen as keys in `powerPlayPricing`) |

### Status codes

| HTTP | Meaning observed |
|---|---|
| 200 | Success (even when body is `[]` / empty content for media endpoints) |
| 400 | Missing/invalid query parameter (CMS seo) |
| 404 | Wrong path/ID, or no resulted events for the requested (competition, classId, date) combination |

### Price object

Two shapes appear, depending on context:

```jsonc
// Live decimal price (sport)
{
  "winPrice": 2.88,
  "winPriceNum": 1880,
  "winPriceDen": 1000,
  "priceCode": "L",
  "topicLink": "Sportsbet/Sportsbook/Sports/.../Selections/.../Prices/L"
}

// Racing fixed-odds with each-way
{
  "priceCode": "L",
  "winPriceNum": 11,
  "winPriceDen": 20,
  "winPrice": 1.55,
  "placePriceNum": 1,
  "placePriceDen": 20,
  "placePrice": 1.05,
  "topicLink": "..."
}
```

Fractional fields (`winPriceNum`/`winPriceDen`) express the same decimal: `winPrice = 1 + winPriceNum / winPriceDen`.

### Time format

All timestamps are **Unix epoch seconds (UTC)**, integer. Example: `"startTime": 1779667980` → 2026-05-25 04:13:00 UTC.

Where the URL takes a `date`, the format is `YYYY-MM-DD` (Sportsbet local timezone, AEST/AEDT). `fromDate`/`toDate` use `YYYY-MM-DDTHH:MM:SS` with **no timezone suffix** (local time).

### `topicLink` and `httpLink`

Every event/market/selection includes both:

- **`topicLink`** — internal pub/sub topic (e.g. for the WebSocket pricing feed), of the form `Sportsbet/Sportsbook/Sports/{classId}/Competitions/{compId}/Events/{eventId}/Markets/{marketId}/Selections/{selId}/Prices/{priceCode}`.
- **`httpLink`** — relative HTTP path to fetch the next level, e.g. `Sportsbook/Racing/Events/10513900/Racecard` or `Sportsbook/Sports/Events/10502542/SportCard`. Prefix with `/apigw/sportsbook-racing/` or `/apigw/sportsbook-sports/` respectively.

### Error responses

Two error envelopes observed:

```jsonc
// "ResourceNotFound" from racing service
{ "code": "ResourceNotFound", "message": "/Sportsbook/Racing/TrackSummaries does not exist" }

// Generic 4xx envelope (used by sports/results gateway)
{ "message": "404 - \"\"", "code": "ERR_BAD_REQUEST", "uniqueIdentifier": "11f33ee8-..." }
{ "message": "404 - undefined", "code": "ERR-IS", "uniqueIdentifier": "cdfe7408-..." }
```

---

## Racing endpoints

All under `/apigw/sportsbook-racing/Sportsbook/Racing/`.

### AllRacing

The master meetings/events listing for a date. Backs the racing tab.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/AllRacing/{eventDate}` |
| **Auth** | None |

**Path parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `eventDate` | `YYYY-MM-DD` | ✅ | Meeting date (local). |

**Verified call:** `/apigw/sportsbook-racing/Sportsbook/Racing/AllRacing/2026-05-25` → HTTP 200, ~328 KB.

**Response shape**

```jsonc
{
  "dates": [
    {
      "meetingDate": 1779633000,            // unix seconds (local midnight)
      "sections": [
        {
          "displayName": "Horses",
          "displayOrder": 100,
          "raceType": "horse",              // horse | harness | greyhound
          "meetings": [
            {
              "id": 487,                    // competition (meeting) ID
              "name": "Mornington",
              "geolocationExclusion": [],
              "classId": 1,
              "isInternational": false,
              "className": "Horses - Aus/NZ",
              "regionName": "Australia",
              "streamingAvailable": false,
              "availableStreamingType": "sky",
              "mbsAvailable": false,
              "events": [
                {
                  "id": 10513900,           // event (race) ID
                  "raceNumber": 1,
                  "startTime": 1779679800,
                  "name": "R1 Asset Painting Services Mdn Plate",
                  "hasBIR": true,
                  "hasBIRStarted": false,
                  "sort": 10,
                  "statusCode": "A",
                  "streaming": {
                    "liveStream": { "provider": "sky", "channel": "1" },
                    "replay":     { "provider": "sky" }
                  },
                  "streamingAvailable": false,
                  "availableStreamingType": "sky",
                  "mbsAvailable": false,
                  "httpLink": "Sportsbook/Racing/Events/10513900/Racecard",
                  "regionGroup": "Aus/NZ",
                  "type": "horse",
                  "category": "standard",
                  "bettingStatus": "PRICED",
                  "isInternational": false,
                  "distance": "1200",
                  "displayName": "R1 Mornington"
                }
                // ... more races
              ]
            }
            // ... more meetings
          ]
        }
        // ... Greyhounds / Harness sections
      ]
    }
  ]
}
```

`displayOrder` controls UI sort, with `100` for Horses, lower numbers for Greys/Harness sections.

### Event Meeting

Returns the parent meeting for any event, including the full list of races and (if available) tote pool data.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/Events/{eventId}/Meeting` |
| **Auth** | None |

**Verified call:** `/apigw/sportsbook-racing/Sportsbook/Racing/Events/10513900/Meeting` → 200, ~25 KB.

**Response shape**

```jsonc
{
  "classId": 1,
  "className": "Horses - Aus/NZ",
  "displayOrder": -90,
  "id": 487,                      // meeting (competition) ID
  "meetingType": "horses",
  "name": "Mornington",
  "resulted": false,
  "totalEventsInMeeting": 7,
  "regionName": "Australia",
  "sameGameMultiEnabled": true,
  "events": [
    {
      "id": 10513900,
      "classId": 1,
      "raceNumber": 1,
      "startTime": 1779679800,
      "hasBIR": true,
      "hasBIRStarted": false,
      "numMarkets": 12,
      "className": "Horses - Aus/NZ",
      "competitionId": 487,
      "competitionName": "Mornington",
      "track": "Good (4)",
      "bettingStatus": "PRICED",
      "eventResulted": false,
      "distance": "1200",
      "name": "R1 Asset Painting Services Mdn Plate",
      "sort": 10,
      "statusCode": "A",
      "streamingAvailable": false,
      "availableStreamingType": "sky",
      "mbsAvailable": false,
      "region": "Australia",
      "regionGroup": "Aus/NZ",
      "isInternational": false,
      "topicLink": "Sportsbet/Sportsbook/Sports/1/Competitions/487/Events/10513900",
      "httpLink": "Sportsbook/Racing/Events/10513900/Racecard",
      "markets": [],
      "type": "horse",
      "category": "standard",
      "streaming": { "liveStream": { "provider": "sky", "channel": "1" }, "replay": { "provider": "sky" } },
      "grade": "UNKNOWN_GROUP",
      "isFeatureRace": false
    }
    // ... more races
  ],
  "pools": [ /* tote pool data, observed empty for AU events */ ]
}
```

### Racecard

The full racecard for one race — runners, markets, prices, jockey/trainer.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/Events/{eventId}/Racecard` |
| **Auth** | None |

**Path parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `eventId` | `integer` | ✅ | Race event ID. |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `selectionNames` | `string` (URL-encoded) | ❌ | Restrict the response to one runner. Apostrophes etc. must be URL-encoded. Example: `selectionNames=Can%27t%20Be%20Reel`. |

**Verified calls**

- `/apigw/sportsbook-racing/Sportsbook/Racing/Events/10513900/Racecard` → 200, ~198 KB.
- `/apigw/sportsbook-racing/Sportsbook/Racing/Events/10513900/Racecard?selectionNames=Can%27t%20Be%20Reel` → 200, ~94 KB.

**Response shape** — a single `racecardEvent` object. The wrapping `{racecardEvent, racecardContext}` is only returned by the `RacecardWithContext` endpoint below. Top-level keys observed:

```text
id, raceNumber, distance, className, competitionId, competitionName, startTime,
quinellaAvailable, exactaAvailable, trifectaAvailable, showFoldIcon,
hasBIR, hasBIRStarted, eventSort, bettingStatus,
livePriceResultConfirmed, livePriceSettled, nonLivePriceSettled,
powerPlayExtra, country, sameGameMultiEnabled, overview, name, displayName,
statusCode, classId, sort, trackStatus, streamingAvailable, availableStreamingType,
raceReplayAvailable, firstFourAvailable, srmExoticsConfig, mbsAvailable,
longFormAvailable, competitionStartTime, topicLink, externalId,
topXFinishMarketList, srmExoticsMarketList, sgmMarketList,
markets, results, exoticResults, deductions,
type, category, streaming, longFormLink, grade, isFeatureRace,
tippedSelectionProvider, tippedSelectionsWithTypes,
tippedSelection1, tippedSelection2, tippedSelection3, tippedSelection4,
tempo
```

`markets[]` element shape:

```text
id, name, marketType, marketSort, BIR, availablePriceTypes, blurb,
livePriceAvailable, powerPlay, homeTote, accMax, accRestriction,
trifectaAvailable, firstFourAvailable, quinellaAvailable, exactaAvailable,
cashoutAvailablePriceTypes, cashoutIcon, geolocationExclusion,
statusCode, sort, numPlaces, eachwayAvailable, placeAvailable, international,
mbsAvailable, isDisplayed, topicLink, httpLink, selections
```

Observed market names: `Win or Place`, `Head to Head`, `Odds vs Evens`, `Diamond in the Roughies`, `Back the Field`, `Insure 2`, `Insure 3`, `Betting Without`.

Selection (runner) shape — **the racecard exposes far more runner metadata than a sport selection**:

```jsonc
{
  "id": 1207239129,
  "name": "Can't Be Reel",
  "runnerNumber": 1,
  "drawNumber": 3,                           // barrier
  "shortForm": "2",                          // recent placings string
  "jockey": "Patrick Moloney",
  "weightGram": 59500,
  "trainer": "M M Laurie",
  "isOut": false,                            // scratched flag
  "recentOddsFluctuations": [1.6, 1.65, 1.7, 1.75, 1.8, 1.85, 1.9, 2, 2.05, 2.1],
  "powerPlayPricing": {                       // promo prices keyed by price-code
    "sPrice": 1.63, "rPrice": 1.63, "gPrice": 1.63, "vPrice": 1.63,
    "pPrice": 1.63, "lPrice": 1.63, "mPrice": 1.63, "ePrice": 1.63
  },
  "marketMover": false,
  "prices": [
    { "priceCode": "MDP", "winPrice": 2.1, "topicLink": "..." },
    { "priceCode": "TMD", "winPrice": 2.2, "topicLink": "..." },
    {
      "priceCode": "L",
      "winPriceNum": 11, "winPriceDen": 20, "winPrice": 1.55,
      "placePriceNum": 1, "placePriceDen": 20, "placePrice": 1.05,
      "topicLink": "..."
    }
  ],
  "result": "-",                             // "-" until placed
  "multiplesKey": "Can't Be Reel",
  "sort": 10,
  "statusCode": "A",
  "mobileSilkImage": "https://assets.sbstatic.com.au/silks/AAP/.../....png",
  "statistics": { /* career stats */ },
  "longFormLink": "...",
  "topicLink": "...",
  "trainerLocation": "...",
  "racingIQShortformAvailable": true,
  "runnerCountry": "..."
}
```

### RacecardWithContext

Same race data **plus** the surrounding `meetings`/`events`/`pools` for nav.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/Events/{eventId}/RacecardWithContext` |
| **Auth** | None |

**Path parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `eventId` | `integer` | ✅ | Race event ID. |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `classId` | `integer` | ✅ | Sport class for the event (e.g. `1` for Horses Aus/NZ, `5` for racing futures). Wrong values return an error envelope. |

**Verified call:** `/apigw/sportsbook-racing/Sportsbook/Racing/Events/10513900/RacecardWithContext?classId=1` → 200, ~201 KB.

**Response shape**

```jsonc
{
  "racecardEvent": { /* identical to Racecard payload above */ },
  "racecardContext": {
    "meetings": [ /* sibling meetings on the same date */ ],
    "events":   [ /* sibling events (other races) for in-meeting navigation */ ],
    "pools":    [ /* tote pool context if any */ ]
  }
}
```

### MultipleRacecards

Batched racecards for a comma-separated set of events.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/Events/MultipleRacecards` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `eventIds` | `string` | ✅ | Comma-separated race event IDs. |

**Verified call:** `/apigw/sportsbook-racing/Sportsbook/Racing/Events/MultipleRacecards?eventIds=10513900,10513897` → 200, ~364 KB.

Response is structured the same way as `Racecard` per event, returned in a parallel listing (exact wrapping varies by client build — observed payload is a wrapped collection of `racecardEvent` objects).

### Racing Competition (meeting summary)

A meeting's metadata + flat event list. Cheaper than `Meeting` (smaller payload, no pools).

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/Competitions/{competitionId}` |
| **Auth** | None |

**Verified call:** `/apigw/sportsbook-racing/Sportsbook/Racing/Competitions/614` → 200, ~5 KB.

```jsonc
{
  "id": 614,
  "name": "Taree",
  "classId": 1,
  "className": "Horses - Aus/NZ",
  "region": "Australia",
  "startTime": 1779675000,
  "topicLink": "Sportsbet/Sportsbook/Sports/1/Competitions/614",
  "events": [
    {
      "id": 10509758,
      "raceNumber": 1,
      "startTime": 1779675000,
      "result": "",
      "distance": "1262",
      "name": "R1 Xxxx Country Boosted Mdn Hcp",
      "classId": 1,
      "className": "Horses - Aus/NZ",
      "competitionId": 614,
      "competitionName": "Taree",
      "sort": 10,
      "statusCode": "B",                           // see status codes
      "streamingAvailable": false,
      "availableStreamingType": "sky",
      "mbsAvailable": false,
      "topicLink": "Sportsbet/Sportsbook/Sports/1/Competitions/614/Events/10509758",
      "httpLink": "Sportsbook/Racing/Events/10509758/Racecard",
      "trackStatus": "Heavy (10)",
      "type": "horse",
      "category": "standard",
      "streaming": { "replay": { "provider": "sky" } }
    }
    // ...
  ],
  "type": "horse",
  "category": "standard"
}
```

### Racing ResultedEvents

Historical resulted events for a single racing competition (meeting) on a given date.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/Competitions/{competitionId}/ResultedEvents` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `classId` | `integer` | ✅ | Must match the competition's class. |
| `date` | `YYYY-MM-DD` | ✅ | Local date. |

**Verified:** `/apigw/sportsbook-racing/Sportsbook/Racing/Competitions/614/ResultedEvents?classId=1&date=2026-05-25` → 200, ~4 KB. Same date that yields no completed races also returns 200 with the upcoming events; mismatched (classId, competitionId, date) returns 404.

Response is a JSON **array** of event summaries identical in shape to `Racing Competition.events[]` above, plus a `result` string ("" until placings settled).

### Racing Futures

All current racing-futures markets across the codes.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/Futures` |
| **Auth** | None |

**Verified call** → 200, ~63 KB.

Response is a JSON array of future event objects:

```jsonc
[
  {
    "id": 10449523,
    "classId": 5,
    "startTime": 1780065000,
    "hasBIR": false,
    "hasBIRStarted": false,
    "numMarkets": 1,
    "className": "Horse Racing: Futures - AUS/NZ",
    "competitionId": 7706,
    "competitionName": "Kingsford-Smith Cup - 1300m",
    "bettingStatus": "PRICED",
    "name": "Kingsford-Smith Cup - All In - Win Or Place",
    "sort": 0,
    "statusCode": "A",
    "streamingAvailable": false,
    "availableStreamingType": "sky",
    "mbsAvailable": false,
    "region": "Australia",
    "regionGroup": "Aus/NZ",
    "isInternational": false,
    "topicLink": "Sportsbet/Sportsbook/Sports/5/Competitions/7706/Events/10449523",
    "httpLink": "Sportsbook/Racing/Events/10449523/Racecard",
    "markets": [
      {
        "id": 242514424,
        "name": "Win or Place",
        "marketType": "-",
        "marketSort": "--",
        "BIR": false,
        "blurb": "Market is all, no refunds",
        "livePriceAvailable": true,
        "powerPlay": true,
        "accMax": 25,
        "accRestriction": "-",
        "cashoutIcon": false,
        "geolocationExclusion": [],
        "statusCode": "A",
        "sort": 0,
        "mbsAvailable": false,
        "topicLink": ".../Markets/242514424",
        "httpLink": "Sportsbook/Racing/Events/10449523/Markets/242514424"
      }
    ],
    "type": "horse",
    "category": "future",
    "streaming": { "replay": { "provider": "sky" } }
  }
]
```

### BestBets

Editorial "best bets" listed per meeting with tipster picks (BEST / VALUE).

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/BestBets` |
| **Auth** | None |

**Verified call** → 200, ~38 KB.

```jsonc
{
  "meetings": [
    {
      "meetingId": 638,
      "name": "Townsville",
      "date": "2026-05-25",
      "events": [
        {
          "eventId": 10510201,
          "raceNumber": 1,
          "startTime": 1779678600,
          "tipsters": [
            {
              "name": "Scott McDonell",
              "type": "MAIN",
              "tips": [
                {
                  "type": "BEST",       // or "VALUE" / null
                  "sort": 1,
                  "runnerNumber": 2,
                  "name": "Bush Etiquette",
                  "outcomeId": 1206780383,
                  "mobileSilkImage": "https://assets.sbstatic.com.au/silks/AAP/.../....png"
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

### BestBetsWithEvents

Combined tipster picks **and** the full event records for the tipped meetings.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/BestBetsWithEvents` |
| **Auth** | None |

**Verified call** → 200, ~505 KB.

```jsonc
{
  "tipsModules": [
    {
      "tipsterName": "Scott McDonell",
      "meeting": "Townsville",
      "meetingId": 638,
      "startTime": 1779678600,
      "tips": [
        {
          "type": "BEST",
          "sort": 1,
          "runnerNumber": 2,
          "outcomeId": 1206780383,
          "name": "Bush Etiquette",
          "eventId": 10510201,
          "startTime": 1779678600,
          "raceNumber": 1,
          "mobileSilkImage": "https://..."
        }
      ]
    }
    // 5 tipster modules observed
  ],
  "events": [ /* 5 events with full market/selection trees */ ]
}
```

### JockeyHub / TopJockeys

A flat list of jockeys and the rides they have today.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/JockeyHub/TopJockeys` |
| **Auth** | None |

**Verified call** → 200, ~55 KB.

```jsonc
{
  "jockeyList": [
    {
      "jockeyName": "Aaron Bullock",
      "country": "",
      "rideCards": [
        {
          "eventId": 10509760,
          "eventOutcome": "Oakfield Mars",        // horse the jockey is on
          "startTimeInUnix": 1779677100,
          "raceNumber": 2,
          "trackName": "Taree",
          "trainer": "D Lane"
        }
      ]
    }
  ]
}
```

### Challenges/All

Active Jockey Challenge / Driver Challenge meta-events.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/Challenges/All` |
| **Auth** | None |

**Verified call** → 200, ~1.2 KB.

```jsonc
[
  {
    "id": 10523663,
    "startTime": 1779678600,
    "hasBIR": false,
    "hasBIRStarted": false,
    "numMarkets": 1,
    "name": "Jockey Challenge - Townsville",
    "classId": "108",                       // Jockey Challenge
    "className": "Jockey Challenge",
    "competitionId": 23532,
    "competitionName": "Jockey Challenge ",
    "sort": 10,
    "competitionDisplayOrder": -8000,
    "statusCode": "A",
    "streamingAvailable": false,
    "availableStreamingType": "sky",
    "mbsAvailable": false,
    "topicLink": "Sportsbet/Sportsbook/Sports/108/Competitions/23532/Events/10523663",
    "httpLink": "Sportsbook/Racing/Events/10523663/Racecard",
    "type": "horse",
    "category": "jockey_challenge",
    "streaming": { "replay": { "provider": "sky" } }
  }
]
```

### Megabets

Active racing-extras meta-events (Jockey Extras, Harness Driver Challenge, etc.) — `classId: 161`.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/Megabets` |
| **Auth** | None |

**Verified call** → 200, ~1.6 KB.

Response is a JSON array of event objects identical in shape to the racing Competition event entries, with `classId: "161"` ("Racing Extras") and `category: "jockey_challenge"` / similar.

### RacingMultisEvents

Surfaces the racing events eligible for racing-multi bets — namely the next-to-jump queue.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/RacingMultisEvents` |
| **Auth** | None |

**Verified call** → 200, ~75 KB.

```jsonc
{
  "nextToJump": [
    {
      "id": 10510427,
      "competitionId": 58,
      "competitionName": "Shepparton",
      "startTime": 1779671280,
      "bettingStatus": "PRICED",
      "competitionDisplayOrder": -301,
      "status": "A",
      "country": "Australia"
    }
  ]
  // additional fields may include groupings for racingMultis/multibetSlip — not observed in this sample
}
```

### PopularSrms

Crowd-popular Same Race Multi suggestions for a race (or set of races).

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-racing/Sportsbook/Racing/PopularSrms` |
| **Auth** | None |

**Query parameters** (all required for the event-scope query observed):

| Name | Type | Required | Description |
|---|---|---|---|
| `hierarchyLevel` | `string` | ✅ | Observed: `event`. (`competition` / `class` likely also work, by analogy to the JS calling code.) |
| `ids` | `string` | ✅ | Comma-separated IDs at the chosen hierarchy level. |
| `maxItems` | `integer` | ❌ | Cap on suggestions returned. |
| `minUniqueCount` | `integer` | ❌ | Minimum distinct selections per SRM. |
| `sortBy` | `string` | ❌ | Observed: `popularity`. |
| `popularsrms` | `boolean` | ❌ | `true` to restrict to popular (vs. personalised). |

**Verified call:** `/apigw/sportsbook-racing/Sportsbook/Racing/PopularSrms?hierarchyLevel=event&ids=10513900&maxItems=5&minUniqueCount=5&sortBy=popularity&popularsrms=true` → 200, ~34 KB.

```jsonc
{
  "popularSRMs": [
    {
      "ranking": 1,
      "backers": 5,
      "lastPrices": [6.2, 6.7],
      "eventId": 10513900,
      "marketIds": [243987138, 243987139],
      "selections": [1207239096, 1207239118, 1207239121, 1207239122]
    }
  ],
  "events": [
    {
      "id": 10513900,
      "name": "R1 Asset Painting Services Mdn Plate",
      "startTime": 1779679800,
      "raceNumber": 1,
      "statusCode": "A",
      "mbs": false,
      "competitionId": 487,
      "competitionName": "Mornington",
      "classId": 1,
      "className": "Horses - Aus/NZ",
      "streamingChannel": "1",
      "topicLink": "Sportsbet/Sportsbook/Sports/1/Competitions/487/Events/..."
      // ... plus full markets/selections needed to render the suggestion
    }
  ]
}
```

> A path candidate `/sportsbook-racing/Sportsbook/Racing/TrackSummaries` exists in JS source but returns `404 ResourceNotFound` directly. It is likely a stale or internal-only route; do not rely on it.

---

## Sport endpoints

All under `/apigw/sportsbook-sports/Sportsbook/Sports/`.

### UpComingEvents

Cross-sport "what's on next" feed for the sports landing page.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/UpComingEvents` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `includePrimaryMarket` | `boolean` | ❌ | If `true`, embed the event's primary market (Head-to-Head, Match Betting, etc.) with prices. |
| `maxEvents` | `integer` | ❌ | Cap on number of events. Web client requests 50. |

**Verified call** → 200, ~143 KB.

Response is a JSON array of event objects. First event of the sample (`bettingStatus: PRICED`, no BIR started):

```jsonc
[
  {
    "id": 10521784,
    "name": "Denver Nuggets (TAAPZ) At Charlotte Hornets (LANES)",
    "className": "e-Basketball",
    "competitionId": 31105,
    "competitionName": "eBasketball H2H GG League 4x5mins",
    "startTime": 1779670260,
    "hasBIR": true,
    "hasBIRStarted": false,
    "eventSort": "MTCH",
    "numMarkets": 10,
    "liveStream": true,
    "liveStreamingInfo": [
      { "providerName": "PERFMOB", "streamStartTime": 1779704460, "streamTypes": [] }
    ],
    "powerPlay": false,
    "bettingStatus": "PRICED",
    "participant1": "Denver Nuggets (TAAPZ)",
    "participant2": "Charlotte Hornets (LANES)",
    "vs": "vs",
    "classId": 443,
    "personalisedMarketsEnabled": false,
    "displayName": "Denver Nuggets (TAAPZ) At Charlotte Hornets (LANES)",
    "externalId": 15805951,
    "statusCode": "A",
    "sort": 0,
    "classDisplayOrder": "6",
    "competitionDisplayOrder": "1",
    "featuredEvent": false,
    "birPriority": false,
    "streamingAvailable": true,
    "mbsAvailable": false,
    "isDisplayed": true,
    "topicLink": "Sportsbet/Sportsbook/Sports/443/Competitions/31105/Events/10521784",
    "liveTopicLink": "Sportsbet/Sportsbook/Sports/443/Competitions/31105/Events/10521784",
    "httpLink": "Sportsbook/Sports/Events/10521784/SportCard",
    "competitionExternalId": 100402,
    "classExternalId": "105",
    "sameGameMultiEnabled": false,
    "isFuture": false,
    "geolocationExclusion": ["SA"],
    "primaryMarket": {
      "id": 244228085,
      "externalId": 580968253,
      "name": "Match Betting",
      "statusCode": "A",
      "sort": 15100,
      "marketType": "-",
      "marketSort": "HH",
      "BIR": false,
      "blurb": "Includes Overtime (if played)",
      "powerPlay": false,
      "mbsAvailable": false,
      "cashoutAvailable": true,
      "eachwayAvailable": false,
      "topicLink": "...",
      "selections": [
        {
          "id": 1208410347,
          "name": "Denver Nuggets (TAAPZ)",
          "resultType": "A",
          "externalId": 2772003519,
          "sort": 10,
          "statusCode": "A",
          "price": {
            "winPrice": 1.36, "winPriceNum": 360, "winPriceDen": 1000,
            "priceCode": "L", "topicLink": "..."
          },
          "topicLink": "...",
          "outcomeVariants": [],
          "multiplesKey": "1558393"
        }
      ],
      "sameGameMultiEnabled": false
    }
  }
]
```

### Sports Classes (active window)

Lists sport classes with at least one event in a date window. Used by the side nav and BetLive landing.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Classes` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `fromDate` | `YYYY-MM-DDTHH:MM:SS` | ✅ | Local datetime, no timezone suffix. |
| `toDate` | `YYYY-MM-DDTHH:MM:SS` | ✅ | Local datetime. |
| `includeLiveEvents` | `boolean` | ❌ | Include classes with live events. |
| `excludeNonLiveEvents` | `boolean` | ❌ | When `true`, only classes with **at least one currently live event** are returned. |

**Verified call:** `/apigw/sportsbook-sports/Sportsbook/Sports/Classes?fromDate=2026-05-25T10:03:00&toDate=2026-05-26T10:03:59` → 200, ~1 KB. (Sample window in the question — small payload because many classes had no events that hour.)

```jsonc
{
  "classList": [
    { "className": "Basketball - Aus/Other", "classId": "63", "classDisplayOrder": "-25" },
    { "className": "Ice Hockey - US",         "classId": "38", "classDisplayOrder": "-4" },
    { "className": "Cricket",                 "classId": "25", "classDisplayOrder": "-60" },
    { "className": "Tennis",                  "classId": "13", "classDisplayOrder": "-63" },
    { "className": "Soccer",                  "classId": "29", "classDisplayOrder": "-64" },
    { "className": "Basketball - US",         "classId": "16", "classDisplayOrder": "-65" },
    { "className": "Handball",                "classId": "58", "classDisplayOrder": "10" }
    // ...
  ]
}
```

### NavHierarchy

Full hierarchical navigation tree across sports / competitions / sub-pages — used to build menus.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/NavHierarchy` |
| **Auth** | None |

**Verified call** → 200, ~120 KB.

```jsonc
{
  "id": -2,
  "idType": "CONST",
  "level": 1,
  "name": "Sports",
  "urlName": "betting",
  "subMenuHeader": "Sports",
  "navItems": [
    {
      "id": 17,
      "idType": "class",              // class | competition | CONST
      "typeIds": "17",
      "level": 2,
      "name": "American Football",
      "urlName": "american-football",
      "subMenuHeader": "American Football",
      "GMB": false, "MBS": false, "MMB": false, "PRI": false,
      "SMB": false, "UPP": false, "WBT": false,
      "geolocationExclusion": [],
      "navItems": [
        {
          "id": 0,
          "idType": "CONST",
          "level": 3,
          "name": "Futures/Outrights",
          "urlName": "futures-outrights",
          "subMenuHeader": "Futures/Outrights",
          "geolocationExclusion": [],
          "navItems": [
            {
              "id": 31944,
              "idType": "competition",
              "typeIds": "31944",
              "level": 4,
              "name": "NFL Futures",
              "urlName": "nfl-futures",
              "subMenuHeader": "NFL Futures",
              "geolocationExclusion": []
            }
          ]
        }
      ]
    }
  ]
}
```

`level` is the depth in the menu tree; `idType` discriminates the link target (`class` → class page, `competition` → competition page, `CONST` → static rollup such as "Futures/Outrights"). The booleans (GMB, MBS, MMB, PRI, SMB, UPP, WBT) gate UI features per class/competition.

### BetLive

Currently in-play events feed.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/BetLive` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `birType` | `string` | ❌ | Observed value: `BETLIVE`. |
| `excludeNonLiveEvents` | `boolean` | ❌ | When `true`, only live events. |
| `includePrimaryMarket` | `boolean` | ❌ | Embed primary market with prices. |

**Verified call** → 200, ~87 KB.

Response is a JSON array of event objects (same shape as `UpComingEvents`), but here events have `hasBIRStarted: true` and `bettingStatus: OFF` (suspended-for-pricing) during in-running. Example: NBA WCF Game 4 (`id: 10502542`, OKC at SAS), `bettingStatus: "OFF"`, `numMarkets: 200`, `liveStream: true`.

### Event Commentary

Settled-and-running scores / period state for one or many events.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Events/Commentary` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `eventIds` | `string` | ✅ | Comma-separated event IDs (web client requests up to ~25 per call). |

**Verified call:** `/apigw/sportsbook-sports/Sportsbook/Sports/Events/Commentary?eventIds=10502542` → 200, ~11 KB.

```jsonc
[
  {
    "id": 10502542,
    "name": "Oklahoma City Thunder At San Antonio Spurs",
    "geolocationExclusion": [],
    "eventParticipants": [
      { "id": 6895898, "name": "Oklahoma City Thunder", "type": "", "isActive": "true", "roleCode": "TEAM_1", "role": "Generic first team listed" },
      { "id": 6895899, "name": "San Antonio Spurs",     "type": "", "isActive": "true", "roleCode": "TEAM_2", "role": "Generic second team listed" }
    ],
    "eventPeriods": [
      {
        "id": 15696701,
        "order": 0,
        "periodCode": "ALL",
        "startTime": 1779667981,
        "description": "All",
        "eventPeriodClockState": {},
        "eventFacts": [
          { "eventParticipantId": 6895898, "fact": "26", "factCode": "SCORE", "id": 29399810, "name": "Score" },
          { "eventParticipantId": 6895899, "fact": "33", "factCode": "SCORE", "id": 29399811, "name": "Score" }
        ]
      },
      {
        "id": 15696702,
        "order": 1,
        "periodCode": "QUARTER_1",
        "startTime": 1779667981,
        "endTime": 1779669685,
        "description": "1st quarter",
        "eventFacts": [ /* per-quarter scores */ ]
      }
    ]
  }
]
```

Observed `periodCode` values: `ALL`, `QUARTER_1` (and by analogy `QUARTER_2`–`QUARTER_4`; sport-specific extensions like `HALF_1`/`SET_1` likely exist).

### SportsCardOrResultedEvent

Unified event-detail endpoint. Returns the live/upcoming **sports card** with grouped markets, OR (if the event is finished and `fallbackToResults: true`) the resulted view.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Events/{eventId}/SportsCardOrResultedEvent` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `displayWinnersPriceMkt` | `boolean` | ❌ | Include the resulted winner price market. |
| `includeLiveMarketGroupings` | `boolean` | ❌ | Include live-only market groupings (period-specific, in-running markets). |
| `includeFirstMarketGroupingDetails` | `boolean` | ❌ | Eagerly embed the markets of the first grouping (saves a follow-up call). |
| `includeCollection` | `boolean` | ❌ | Include curated market collections (e.g. "Player Stats"). |
| `fallbackToResults` | `boolean` | ❌ | If `true`, automatically fall back to the resulted view if the event has ended. |

**Verified call** → 200, ~161 KB.

Top-level returns an event object (similar to UpComingEvents entries) **plus** a `marketGrouping` array describing how the markets are tab-organised:

```jsonc
{
  "id": 10502542,
  "name": "Oklahoma City Thunder At San Antonio Spurs",
  "className": "Basketball - US",
  "competitionId": 6927,
  "competitionName": "NBA",
  "startTime": 1779667980,
  "hasBIR": true,
  "hasBIRStarted": true,
  "eventSort": "MTCH",
  "numMarkets": 199,
  "liveStream": true,
  "liveStreamingInfo": [
    { "providerName": "BET_RADAR", "streamStartTime": 1779667200, "streamTypes": ["video"] }
  ],
  "powerPlay": true,
  "bettingStatus": "OFF",
  "participant1": "Oklahoma City Thunder",
  "participant2": "San Antonio Spurs",
  "vs": "at",
  "classId": 16,
  "personalisedMarketsEnabled": true,
  "displayName": "Oklahoma City Thunder At San Antonio Spurs",
  "externalId": 15772756,
  "statusCode": "A",
  "sort": 10,
  "classDisplayOrder": "-65",
  "competitionDisplayOrder": "-999",
  "featuredEvent": false,
  "birPriority": false,
  "streamingAvailable": true,
  "mbsAvailable": false,
  "isDisplayed": true,
  "topicLink": "Sportsbet/Sportsbook/Sports/16/Competitions/6927/Events/10502542",
  "httpLink": "Sportsbook/Sports/Events/10502542/SportCard",
  "competitionExternalId": 19476,
  "classExternalId": "16",
  "sameGameMultiEnabled": true,
  "isFuture": false,
  "geolocationExclusion": [],
  "canDisplayChat": false,
  "marketGrouping": [
    {
      "id": ...,
      "name": "Popular",
      "marketList": [ /* markets, each with selections+prices */ ],
      "sort": 0,
      "mbsAvailable": false,
      "topicLink": "...",
      "httpLink": "...",
      "marketGroup": "..."
    }
    // 22 groupings observed for an NBA finals game
  ],
  "isSportsCard": true
}
```

### SportCard (legacy)

A leaner predecessor still served. Returns the event metadata **without** `marketGrouping`, only the small `marketGrouping`-light field used by older clients. Use `SportsCardOrResultedEvent` for new work.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Events/{eventId}/SportCard` |
| **Auth** | None |

**Verified call** → 200, ~1.3 KB.

### Event Markets

A flat list of all markets for one event, each with selections + prices. Same shape as the embedded markets in `SportsCardOrResultedEvent`.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Events/{eventId}/Markets` |
| **Auth** | None |

**Verified call:** `/apigw/sportsbook-sports/Sportsbook/Sports/Events/10502542/Markets` → 200, ~544 KB; returned `list[202]` markets.

```jsonc
[
  {
    "id": 243720293,
    "externalId": 579611284,
    "name": "Match Betting",
    "statusCode": "A",
    "sort": -1000,
    "marketType": "-",
    "marketSort": "HH",
    "BIR": true,
    "powerPlay": true,
    "mbsAvailable": false,
    "cashoutAvailable": true,
    "sgmCashoutAvailable": false,
    "eachwayAvailable": false,
    "topicLink": ".../Markets/243720293",
    "selections": [
      {
        "id": 1205998754,
        "name": "Oklahoma City Thunder",
        "resultType": "A",
        "externalId": 2765517955,
        "sort": 10,
        "statusCode": "A",
        "price": { "winPrice": 3, "winPriceNum": 2000, "winPriceDen": 1000, "priceCode": "L", "topicLink": "..." },
        "topicLink": "...",
        "outcomeVariants": [],
        "multiplesKey": "oklnba"
      }
    ],
    "sameGameMultiEnabled": true,
    "sameGameMultiExpanded": true,
    "sameMarketMultiEnabled": false,
    "samePodiumMultiEnabled": false,
    "accMax": ...,
    "accRestriction": ...,
    "geolocationExclusion": [],
    "MBS": false,
    "displayOrder": ...
  }
]
```

### Event Results

Settled markets for a finished sport event — final scores, winning selections, deductions.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Events/{eventId}/Results` |
| **Auth** | None |

**Verified call:** `/apigw/sportsbook-sports/Sportsbook/Sports/Events/10502542/Results` → 200, ~32 KB.

```jsonc
{
  "id": 10502542,
  "name": "Oklahoma City Thunder At San Antonio Spurs",
  "className": "Basketball - US",
  "competitionId": 6927,
  "competitionName": "NBA",
  "startTime": 1779667980,
  "participant1": "Oklahoma City Thunder",
  "participant2": "San Antonio Spurs",
  "vs": "at",
  "classId": 16,
  "personalisedMarketsEnabled": true,
  "displayName": "Oklahoma City Thunder At San Antonio Spurs",
  "sort": 10,
  "featuredEvent": false,
  "birPriority": false,
  "topicLink": ".../Events/10502542",
  "httpLink": "Sportsbook/Sports/Events/10502542/Results",
  "geolocationExclusion": [],
  "markets": [
    {
      "id": 244158380,
      "name": "Method of First Basket",
      "sort": 10,
      "marketType": "-",
      "marketSort": "--",
      "eachwayAvailable": false,
      "topicLink": ".../Markets/244158380",
      "selections": [
        {
          "id": 1208103133,
          "name": "Victor Wembanyama - Three Point Field Goal",
          "resultType": "-",
          "oddsDecimal": 19,
          "place": "1",
          "sort": 50,
          "statusCode": "W",                       // W = winning selection
          "topicLink": ".../Selections/1208103133"
        }
      ],
      "geolocationExclusion": [],
      "displayOrder": 10
    }
  ]
}
```

> The corresponding racing endpoint `/sportsbook-racing/Sportsbook/Racing/Events/{eventId}/Results` returns 404 for events that have not yet been resulted; only test it against events with `result` populated in their meeting listing.

### Sport Competition

The full competition payload — events list with optional embedded top markets, optional filter by event type.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Competitions/{competitionId}` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `displayType` | `string` | ❌ | Observed: `default`. |
| `eventFilter` | `string` | ❌ | `matches`, `outrights`, or omit for "all eligible events". |
| `includeTopMarkets` | `boolean` | ❌ | Embed top markets for each event. |
| `includeAllEvents` | `boolean` | ❌ | Bypass default date-window filters. |
| `numMarkets` | `integer` | ❌ | Cap embedded markets per event (e.g. `1` for compact tiles). |

**Verified calls**

- Matches (NBA): `/apigw/sportsbook-sports/Sportsbook/Sports/Competitions/6927?displayType=default&includeTopMarkets=true&eventFilter=matches` → 200, ~53 KB.
- Outrights (Men's French Open): `/apigw/sportsbook-sports/Sportsbook/Sports/Competitions/1466?displayType=default&eventFilter=outrights&numMarkets=1` → 200, ~84 KB.

> Specifying `eventFilter=outrights` against a competition that has none (e.g. NBA `6927`) returns HTTP 404 with `code: ERR_BAD_REQUEST`.

```jsonc
{
  "id": 6927,
  "name": "NBA",
  "classId": 16,
  "className": "Basketball - US",
  "powerPlay": true,
  "startTime": 1779667980,
  "hasBIR": true,
  "mbsAvailable": false,
  "topicLink": "Sportsbet/Sportsbook/Sports/16/Competitions/6927",
  "events": [
    // event objects like UpComingEvents entries; primaryMarket/marketList included if requested
  ]
}
```

### Competition / Events / Matches

Events grouped by display-group label, restricted to match-type events.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Competitions/{competitionId}/Events/Matches` |
| **Auth** | None |

**Verified call:** `/apigw/sportsbook-sports/Sportsbook/Sports/Competitions/6927/Events/Matches` → 200, ~5 KB.

```jsonc
[
  {
    "groupName": "Match Betting",
    "events": [ /* event objects */ ]
  }
]
```

### Competition / Events / Outrights

Events grouped by outrights group label.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Competitions/{competitionId}/Events/Outrights` |
| **Auth** | None |

**Verified call:** `/apigw/sportsbook-sports/Sportsbook/Sports/Competitions/1466/Events/Outrights` → 200, ~84 KB.

```jsonc
[
  {
    "groupName": "To Reach The Semi Finals - Quarter 1",
    "events": [
      {
        "id": 10484943,
        "name": "To Reach The Semi Finals - Quarter 1",
        "className": "Tennis",
        "competitionId": 1466,
        "competitionName": "Mens French Open",
        // ...
        "primaryMarket": { /* ... */ }
      }
    ]
  }
]
```

### Competition / ResultedEvents

Historical resulted events for a sports competition on a date.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Competitions/{competitionId}/ResultedEvents` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `classId` | `integer` | ✅ | Class ID matching the competition. |
| `date` | `YYYY-MM-DD` | ✅ | Local date. |

**Verified call:** `/apigw/sportsbook-sports/Sportsbook/Sports/Competitions/6927/ResultedEvents?classId=16&date=2026-05-24` → 200, ~597 B (one resulted NBA game).

```jsonc
[
  {
    "id": 10502534,
    "name": "New York Knicks At Cleveland Cavaliers",
    "className": "Basketball - US",
    "competitionId": 6927,
    "competitionName": "NBA",
    "startTime": 1779581640,
    "participant1": "New York Knicks",
    "participant2": "Cleveland Cavaliers",
    "vs": "at",
    "classId": 16,
    "personalisedMarketsEnabled": true,
    "displayName": "New York Knicks At Cleveland Cavaliers",
    "sort": 10,
    "featuredEvent": false,
    "birPriority": false,
    "mbsAvailable": false,
    "topicLink": "Sportsbet/Sportsbook/Sports/16/Competitions/6927/Events/10502534",
    "httpLink": "Sportsbook/Sports/Events/10502534/SportCard",
    "isFuture": false,
    "geolocationExclusion": []
  }
]
```

### Class Coupon flag

Indicates whether a class has any active coupon listings.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-sports/Sportsbook/Sports/Class/{classId}/Coupon` |
| **Auth** | None |

**Verified call:** `/apigw/sportsbook-sports/Sportsbook/Sports/Class/16/Coupon` → 200, 34 B.

```json
{ "classId": 16, "couponsExist": true }
```

> This endpoint only confirms existence. The actual coupon data is loaded through nav and competition endpoints driven off the user's interactions. There is no separate `Coupon/{couponId}` path in the public gateway.

---

## Results browser

Under `/apigw/sportsbook-results/Sportsbook/Results/`.

### Results / Classes

Classes (across racing and sports) with at least one resulted event on the date.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-results/Sportsbook/Results/Classes` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `date` | `YYYY-MM-DD` \| `today` | ✅ | Date or the literal string `today`. |

**Verified call:** `?date=today` → 200, ~1.5 KB.

```jsonc
[
  { "classId": 4,   "className": "Greyhound Racing",       "groupName": "Racing" },
  { "classId": 2,   "className": "Horses - International", "groupName": "Racing" },
  { "classId": 112, "className": "Greyhound Racing",       "groupName": "Racing" },
  { "classId": 1,   "className": "Horses - Aus/NZ",        "groupName": "Racing" },
  { "classId": 17,  "className": "American Football",      "groupName": "Sports" }
  // ...
]
```

### Results / Sports / Classes / Competitions

Competitions within a class that have resulted events on a given date.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sportsbook-results/Sportsbook/Results/Sports/Classes/{classId}/Competitions` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `date` | `YYYY-MM-DD` | ✅ | Local date. |

**Verified call:** `/apigw/sportsbook-results/Sportsbook/Results/Sports/Classes/16/Competitions?date=2026-05-24` → 200, ~191 B.

```json
[
  { "id": 6927,  "name": "NBA",  "classId": 16, "className": "Basketball - US", "geolocationExclusion": [] },
  { "id": 29909, "name": "WNBA", "classId": 16, "className": "Basketball - US", "geolocationExclusion": [] }
]
```

> Once you have a competition ID, drill into [Competition / ResultedEvents](#competition--resultedevents) and finally [Event Results](#event-results).

---

## Sports-form

Service hosting form/stats meta. Currently observed to proxy URLs for the third-party iSportGenius (GTG Network) widgets, plus standings.

### event-status

Returns a JSON envelope listing the embeddable resource URLs (Preview, Stats, Ladder, Betting Insights) for the event, plus structured **fun facts** with linked betting outcomes, and team form.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sports-form/event-status/{eventId}` |
| **Auth** | None |

**Verified call:** `/apigw/sports-form/event-status/10502542` → 200, ~25 KB.

```jsonc
{
  "license": "Copyright 2026 GTG Network. All rights reserved.",
  "statusCode": 200,
  "eventID": "10502542",
  "eventStatus": "preview",                  // preview | review (and probably "live")
  "content": [
    {
      "page": "Preview/Review",
      "resources": [
        { "device": "iOS",     "url": "https://sbios.isportgenius.com.au/10502542" },
        { "device": "Android", "url": "https://sband.isportgenius.com.au/10502542" },
        { "device": "Mobile",  "url": "https://sbmob.isportgenius.com.au/10502542" },
        { "device": "Desktop", "url": "https://sblr-desktop.isportgenius.com.au/10502542" },
        { "device": "Mweb",    "url": "https://sblr-mweb.isportgenius.com.au/10502542" },
        { "device": "iOSv2",   "url": "https://sbios.isportgenius.com.au/10502542?v=iosv2" }
      ]
    },
    { "page": "Betting Insights", "resources": [ /* same shape */ ] },
    { "page": "Stats",            "resources": [ /* same shape */ ] },
    { "page": "Ladder",           "resources": [ /* same shape */ ] },
    { "match_preview": "<long-form editorial preview string>" },
    {
      "home": { "id": "rrsb954k", "name": "San Antonio Spurs",      "short_teamname": "Spurs",   "form": "WWWLL" },
      "away": { "id": "6ky76fxw", "name": "Oklahoma City Thunder",  "short_teamname": "Thunder", "form": "WWLWW" }
    },
    {
      "funfacts": [
        {
          "market_group_isgapi_id": "h2h",
          "fact": "The Thunder have won each of their last nine Game 4s of a playoff series.",
          "tag": ["San Antonio Spurs", "Oklahoma City Thunder", "Win/Loss"],
          "target_bet": {
            "result": "Oklahoma City Thunder",
            "market": "Match",
            "market_id": "243720293",
            "outcomeid": "1205998754",
            "icon": "https://cdn.gtgnetwork.com/icons/teams/basketball/sportsbet/oklahoma_city_thunder.png",
            "price": 2.23,
            "price_american": "+123",
            "market_isg_api_id": "win"
          },
          "fact_type": "preview"
        }
        // many more — each linked to a specific market/outcome
      ]
    }
  ]
}
```

### league-ladder-status

Returns ladder/standings resource URLs (proxied to iSportGenius) for a competition.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/sports-form/league-ladder-status/{competitionId}` |
| **Auth** | None |

**Verified call:** `/apigw/sports-form/league-ladder-status/6927` → 200, ~329 B.

```json
{
  "license": "Copyright 2026 GTG Network. All rights reserved.",
  "statusCode": 200,
  "content": {
    "name": "Basketball",
    "resources": [
      { "device": "Desktop", "url": "https://sblr-desktop.isportgenius.com.au/league/ladder/6927" }
    ]
  }
}
```

---

## Media / Nomad

Editorial content. All return empty bodies (`[]` or `{"videoUrl":"","subtitleUrl":""}`) when no content is configured for the requested target.

### trackreport

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/media/nomad/trackreport` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `eventDate` | `YYYY-MM-DD` | ✅ | Meeting date. |
| `raceType` | `string` | ❌ | `horse` / `harness` / `greyhound`. |
| `trackName` | `string` | ❌ | URL-encoded specific track. Must be paired with `raceType`. |

**Verified calls** → 200; both `?eventDate=2026-05-25` and `?raceType=horse&trackName=Caulfield%20Heath&eventDate=2026-05-27` returned `[]` (no editorial copy in the sample). When populated, each entry contains track condition, rail position, weather, and editorial comments.

### racePreview

Per-race video / subtitle preview pointers (Nomad-hosted).

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/media/nomad/racePreview` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `raceType` | `string` | ✅ | `horse` / `harness` / `greyhound`. |
| `trackName` | `string` | ✅ | URL-encoded track name. |
| `raceNumber` | `integer` | ✅ | Race number. |
| `eventDate` | `YYYY-MM-DD` | ✅ | Meeting date. |

**Verified call** → 200, 32 B.

```json
{ "videoUrl": "", "subtitleUrl": "" }
```

### matchPreview

Per-match video / subtitle preview pointers.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/media/nomad/matchPreview` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `sportsClass` | `string` | ✅ | Lowercase class slug (e.g. `tennis`, `basketball-us`). |
| `sportsCompetitionName` | `string` | ✅ | Slugged competition name (e.g. `nba`, `mens-french-open`). |
| `eventName` | `string` | ✅ | Slugged event name (e.g. `oklahoma-city-thunder-at-san-antonio-spurs`). |
| `eventDate` | `YYYY-MM-DD` | ✅ | Event date. |

**Verified call** → 200, 32 B (`{"videoUrl":"","subtitleUrl":""}`).

---

## Trending / Personalisation

### trendingsgm/event

Popular Same-Game Multi combinations for a single sports event.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/trendingsgm/event` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `id` | `integer` | ✅ | Event ID. |
| `no-of-items` | `integer` | ❌ | Max suggestions. Note the hyphen — `noOfItems` does not work. |
| `min-unique-count` | `integer` | ❌ | Minimum distinct selections per SGM. |

**Verified call:** `/apigw/trendingsgm/event?id=10502542&no-of-items=20&min-unique-count=5` → 200, ~78 KB.

```jsonc
{
  "item-id": 10502542,
  "item-list": [
    {
      "ranking": 1,
      "selections": [1207672652, 1207673734, 1207676239, 1207676268],
      "markets":    [244071401,  244071608,  244072199,  244072204],
      "bet-count": 1826,
      "unique-customer-count": 1778,
      "last-prices": [9.75, 10.75, 9.75, 10.75, /* …historical price snapshots… */]
    }
  ]
}
```

### preferred-promotions trending

Anonymous-user trending promotions keyed by a Google Analytics client ID.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/preferred-promotions/v2/models/trending/user-ids/{provider}/client-id/{clientId}/promotions` |
| **Auth** | None |

**Path parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `provider` | `string` | ✅ | Observed: `google`. |
| `clientId` | `string` | ✅ | GA client ID, e.g. `GA1.1.1664998928.1779668005`. |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `limit` | `integer` | ❌ | Max promotions. |
| `loggedIn` | `boolean` | ❌ | Personalisation flag. `false` returns the anonymous-trending mix. |

**Verified call** → 200, ~54 KB.

```jsonc
{
  "promotions": [
    {
      "cardType": "promotionCard",
      "title": "State of Origin Jackpot.",
      "isProspectPromo": false,
      "displayOnTabs": ["sports"],
      "classId": 2,
      "competitionIds": [],
      "featureImageCXPDesktop": "https://assets.sbstatic.com.au/cms/.../...desktop@2x.jpg",
      "featureImageCXPMobile":  "https://assets.sbstatic.com.au/cms/.../...mobile@3x.jpg",
      "links": [
        {
          "type": "Modal",
          "url": "sportsbet://webview?url=...",
          "displayType": "shadedButton",
          "label": "Bet Now",
          "alternateUrl": "https://www.sportsbet.com.au/betting/rugby-league/state-of-origin/...",
          "classId": 3
        }
      ],
      "description": "...",
      "isAnnouncement": false,
      "isPinned": true,
      "creative": "dc_pinned",
      "hideForBTLOfferIds": [],
      "id": 290
    }
  ]
}
```

---

## Page content

### homepage/sports

Server-rendered card layout for the sports homepage.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/page-content/homepage/sports` |
| **Auth** | None |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `loggedIn` | `boolean` | ❌ | Personalisation flag. |
| `popularsrms` | `boolean` | ❌ | Include popular Same-Game Multi card group. |

**Verified call** → 200, ~681 KB.

```jsonc
{
  "tabs": [
    { "id": 38, "name": "Racing", "path": "home/racing" },
    { "id": ...,"name": "Sports", "path": "home/sports" }
  ],
  "tab": {
    "id": ...,
    "name": "Sports",
    "path": "home/sports",
    "type": "page",
    "cardGroups": [
      {
        "cardType": "menuCard",
        "title": "Sports Quicklinks",
        "menu": [ /* link items: title, iconFontReference, link.{type,alternateUrl,displayType} */ ]
      }
      // ... more card groups
    ]
  }
}
```

### homepage/racing

Same shape, racing tab.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/page-content/homepage/racing` |
| **Auth** | None |

**Verified call:** `?loggedIn=false&popularsrms=true` → 200, ~1.35 MB.

The `/page-content/homepage` root (with no sub-path) returns 404 — the sub-path (`sports` or `racing`) is required.

### safer_gambling_message

The rotating safer-gambling strapline displayed in the footer/banner.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/page-content/safer_gambling_message` |
| **Auth** | None |

**Verified call** → 200, 324 B.

```json
{
  "id": "3",
  "phrase": "WHAT ARE YOU PREPARED TO LOSE TODAY? SET A DEPOSIT LIMIT.",
  "cta": [
    { "text": "For free and confidential support call" },
    { "text": "1800 858 858", "link": "tel:1800858858" },
    { "text": "or visit" },
    { "text": "gamblinghelponline.org.au", "link": "https://www.gamblinghelponline.org.au/" }
  ],
  "mobileCta": "Set a deposit limit"
}
```

---

## CMS

Headless CMS pages, menus, settings, promo cards.

### cms/app/page

CMS-rendered page payload — either competition-scoped or path-scoped.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/cms/app/page` |
| **Auth** | None |

**Query parameters** (exactly one of `competitionId` / `pagePath` must be provided)

| Name | Type | Required | Description |
|---|---|---|---|
| `competitionId` | `integer` | ⚠️ one of two | Render the CMS page tied to a specific competition (e.g. `1466` Men's French Open, `6927` NBA). |
| `pagePath` | `string` | ⚠️ one of two | Render the page at a given slug. Observed: `specials`. |
| `loggedIn` | `boolean` | ❌ | Personalisation flag. |

**Verified calls**

- `?pagePath=specials&loggedIn=false` → 200, ~34 KB.
- `?competitionId=6927&loggedIn=false` → 200, ~3.3 KB.

Path-scoped (specials) response:

```jsonc
{
  "id": 37,
  "sections": [
    {
      "id": 40,
      "name": "View All",
      "path": "specials/view-all",
      "type": "tab",
      "cards": [
        {
          "cardType": "promotionCard",
          "title": "State of Origin Jackpot.",
          "id": 290,
          "displayOnTabs": ["sports"],
          "classId": 23,
          "competitionIds": [],
          "isPinned": true,
          "isProspectPromo": false,
          "featureImageCXPDesktop": "...",
          "featureImageCXPMobile":  "...",
          "links": [ /* ... */ ],
          "description": "...",
          "termsConditions": "1. This offer commences..."
        }
      ]
    }
  ]
}
```

Competition-scoped response:

```jsonc
{
  "id": 16927,
  "competitionId": 6927,
  "name": "NBA",
  "path": "nba",
  "type": "page",
  "cards": [
    {
      "cardType": "promotionCard",
      "title": "NBA Fair Go Refund ",
      "id": 248,
      "displayOnTabs": ["sports"],
      "classId": 0,
      "competitionIds": [],
      "isPinned": true,
      "isProspectPromo": false,
      "featureImageCXPDesktop": "...",
      "featureImageCXPMobile": "...",
      "links": [ /* ... */ ],
      "description": "...",
      "termsConditions": "1. Where a player suffers a game ending injury..."
    }
  ]
}
```

### cms/app/settings

Application-level configuration — side menu, footer menu, feature toggles. Large payload (~20 KB).

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/cms/app/settings` |
| **Auth** | None |

**Verified call** → 200, ~20 KB.

Top-level keys observed: `menus` (containing `sidemenu`). Each menu item:

```jsonc
{
  "id": 79,
  "title": "Home",
  "iconFontReference": "home",
  "link": { "type": "Internal", "label": null, "alternateUrl": "/" },
  "platforms": ["cxp_desktop", "cxp_mobile"],
  "submenus": [],
  "type": "EXPANDABLE_GROUP",
  "defaultCollapsed": true
}
```

### cms/app/messages

System-wide messages (banners). Returns `[]` when none active.

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `/cms/app/messages` |
| **Verified** | 200, 2 B (`[]`). |

### Other CMS endpoints

Discovered in the JS bundles but not exhaustively probed:

| Path | Notes |
|---|---|
| `/apigw/cms/app/menus` | Returned 404 in the sample (likely requires an unknown parameter, or is internal-only). |
| `/apigw/cms/app/home_of_games` | Casino landing page payload — not probed. |
| `/apigw/cms/app/seo` | Returns 400 without correct query parameters; appears to serve SEO meta for a given URL. |
| `/apigw/cms/app/seo_meta_tag_manager` | SEO admin endpoint — not probed. |

---

## GraphQL gateway

Single GraphQL endpoint, Apollo persisted-query semantics.

| | |
|---|---|
| **Method** | `GET` (persisted) or `POST` (fallback with full query body) |
| **Path** | `/sportsbook/graph` |
| **Auth** | None for public operations |

### Query parameters (persisted GET)

| Name | Type | Required | Description |
|---|---|---|---|
| `operationName` | `string` | ✅ | Server-registered operation name. Observed: `EventStats`. |
| `variables` | `string` (JSON, URL-encoded) | ✅ | Operation variables. |
| `extensions` | `string` (JSON, URL-encoded) | ✅ | `{"persistedQuery": {"version": 1, "sha256Hash": "<hex>"}}`. |

### `EventStats` operation

**Variables**

```json
{ "openbetLinkingId": "15772756", "competitionId": 6927, "buildNumber": 10000000 }
```

`openbetLinkingId` corresponds to the event's `externalId`. `buildNumber` is a client identifier used for cache busting.

**Extensions**

```json
{ "persistedQuery": { "version": 1, "sha256Hash": "30ea12f65f0f7d0a67bf79555b4ad514d9b0fdef3c9848759b322ac6bf6ddd87" } }
```

**Full URL example**

```
/apigw/sportsbook/graph
  ?operationName=EventStats
  &variables=%7B%22openbetLinkingId%22%3A%2215772756%22%2C%22competitionId%22%3A6927%2C%22buildNumber%22%3A10000000%7D
  &extensions=%7B%22persistedQuery%22%3A%7B%22version%22%3A1%2C%22sha256Hash%22%3A%2230ea12f65f0f7d0a67bf79555b4ad514d9b0fdef3c9848759b322ac6bf6ddd87%22%7D%7D
```

If the gateway responds `PersistedQueryNotFound`, retry as a POST with the full GraphQL document as `query` plus the same `variables`. The Apollo `persistedQueries` extension is the production path; that POST fallback is rarely used by the web client.

> Other `operationName` values exist (the bundle minifies them down to single-letter accessors), but no other shas were extractable from the minified source. Probe by intercepting browser traffic.

---

## Product catalogue

| Path | Method | Observed |
|---|---|---|
| `/apigw/sportsbook-product-catalog/sportsbook/market-pricing` | `GET` | 200, 2 B (empty body — likely a `POST` endpoint that expects a body of selections to price; the `GET` response is essentially a no-op). |

Used to fetch live multi-pricing for a set of selections. The web client also calls `/apigw/multi-pricer-racing/...` paths (see [Endpoint quick reference](#endpoint-quick-reference)) for racing-specific multi pricing.

---

## Authentication & wallets (not documented)

Endpoints exist for identity (`/apigw/ciam/...`, `/apigw/ciamcore/...`, `/apigw/auth/realms/sportsbet/...`) and wallet operations (`/apigw/wallets/*`). These require session/CIAM tokens and are not part of the public read surface. Paths discovered in the JS bundle:

```
/apigw/ciam/{authType, authenticate, checkOtp, continueAuthentication,
             resendOtp, selectDevice, submitUserAttributes, authorise,
             token, revoke-token, initiatePasswordChange, checkNewPassword}/
/apigw/ciamcore/{register, register/status, changepassword, verification,
                 duplicates/status, register/v2/step1, register/v2/step2,
                 register/v2/mobile-verification-status}
/apigw/auth/realms/sportsbet/{register, contact-options, protocol/openid-connect/token}
/apigw/wallets/{applepay/deposit, applepay/v2/deposit, banks, config-flags,
                creditcards, googlepay/deposit, payid, paypal/, paypal/deposit,
                rti/events, sportsbetcard, wallets}
```

---

## Endpoint quick reference

| # | Group | Method | Path | Verified |
|---|---|---|---|---|
| 1 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/AllRacing/{date}` | ✅ |
| 2 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/Events/{eventId}/Meeting` | ✅ |
| 3 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/Events/{eventId}/Racecard` | ✅ |
| 4 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/Events/{eventId}/RacecardWithContext?classId=` | ✅ |
| 5 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/Events/MultipleRacecards?eventIds=` | ✅ |
| 6 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/Competitions/{competitionId}` | ✅ |
| 7 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/Competitions/{competitionId}/ResultedEvents?classId=&date=` | ✅ |
| 8 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/Futures` | ✅ |
| 9 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/BestBets` | ✅ |
| 10 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/BestBetsWithEvents` | ✅ |
| 11 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/JockeyHub/TopJockeys` | ✅ |
| 12 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/Challenges/All` | ✅ |
| 13 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/Megabets` | ✅ |
| 14 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/RacingMultisEvents` | ✅ |
| 15 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/PopularSrms?hierarchyLevel=&ids=&...` | ✅ |
| 16 | Racing | GET | `/sportsbook-racing/Sportsbook/Racing/TrackSummaries` | ❌ 404 |
| 17 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/UpComingEvents` | ✅ |
| 18 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Classes?fromDate=&toDate=` | ✅ |
| 19 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/NavHierarchy` | ✅ |
| 20 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/BetLive?birType=BETLIVE&...` | ✅ |
| 21 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Events/Commentary?eventIds=` | ✅ |
| 22 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Events/{eventId}/SportsCardOrResultedEvent` | ✅ |
| 23 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Events/{eventId}/SportCard` | ✅ |
| 24 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Events/{eventId}/Markets` | ✅ |
| 25 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Events/{eventId}/Results` | ✅ |
| 26 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Competitions/{competitionId}` | ✅ |
| 27 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Competitions/{competitionId}/Events/Matches` | ✅ |
| 28 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Competitions/{competitionId}/Events/Outrights` | ✅ |
| 29 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Competitions/{competitionId}/ResultedEvents?classId=&date=` | ✅ |
| 30 | Sport | GET | `/sportsbook-sports/Sportsbook/Sports/Class/{classId}/Coupon` | ✅ |
| 31 | Results | GET | `/sportsbook-results/Sportsbook/Results/Classes?date=` | ✅ |
| 32 | Results | GET | `/sportsbook-results/Sportsbook/Results/Sports/Classes/{classId}/Competitions?date=` | ✅ |
| 33 | Form | GET | `/sports-form/event-status/{eventId}` | ✅ |
| 34 | Form | GET | `/sports-form/league-ladder-status/{competitionId}` | ✅ |
| 35 | Media | GET | `/media/nomad/trackreport?eventDate=` | ✅ |
| 36 | Media | GET | `/media/nomad/racePreview?...` | ✅ |
| 37 | Media | GET | `/media/nomad/matchPreview?...` | ✅ |
| 38 | Trending | GET | `/trendingsgm/event?id=&no-of-items=&min-unique-count=` | ✅ |
| 39 | Promos | GET | `/preferred-promotions/v2/models/trending/user-ids/{provider}/client-id/{cid}/promotions` | ✅ |
| 40 | Pages | GET | `/page-content/homepage/sports` | ✅ |
| 41 | Pages | GET | `/page-content/homepage/racing` | ✅ |
| 42 | Pages | GET | `/page-content/safer_gambling_message` | ✅ |
| 43 | CMS | GET | `/cms/app/page?competitionId=` or `?pagePath=` | ✅ |
| 44 | CMS | GET | `/cms/app/settings` | ✅ |
| 45 | CMS | GET | `/cms/app/messages` | ✅ (empty) |
| 46 | CMS | GET | `/cms/app/menus` | ❌ 404 in sample |
| 47 | CMS | GET | `/cms/app/home_of_games` | ❓ not probed |
| 48 | CMS | GET | `/cms/app/seo` | ❌ 400 without correct params |
| 49 | CMS | GET | `/cms/app/seo_meta_tag_manager` | ❓ not probed |
| 50 | GraphQL | GET/POST | `/sportsbook/graph` (persisted: `EventStats`) | ✅ |
| 51 | Catalogue | GET | `/sportsbook-product-catalog/sportsbook/market-pricing` | ⚠️ probably POST |

### Additional paths present in JS source (not probed)

These were extracted from the production JS bundles but were either non-`GET`, gated by auth, or specific to internal flows. They are listed verbatim for traceability:

```
/apigw/sportsbook-racing/Sportsbook/Racing/Challenges/All
/apigw/multi-pricer-racing/bet/
/apigw/multi-pricer-racing/combinations/price/racing
/apigw/multi-pricer-racing/quotation/
/apigw/multibuilder/notification
/apigw/multibuilder/notification/alert
/apigw/fastcode/betlive/fastcode
/apigw/fastcode/betlive/fastcodes
/apigw/feed/home/racing
/apigw/feed/home/sports
/apigw/feed/search
/apigw/feed/search/complete-profile
/apigw/feed/search/reactivate-profile
/apigw/preferred-sportsbook/events
/apigw/notification/crm/
/apigw/huddle/author/
/apigw/racing-event/srm
/apigw/racing-event/srm/popular
/apigw/racing-event/srm/prepackaged
/apigw/racing-meeting/feed
/apigw/racing-schedule/{horse,greyhound,harness}/today
/apigw/account/bet_history
/apigw/account/deposit/paypal
/apigw/account/deposit_limit
/apigw/account/deposit_match
/apigw/account/settings
/apigw/account/sportsbet_cash
/apigw/account/withdraw/paypal
/apigw/my-account/my-bets[/pending-bets|/resulted-bets|/share-a-bet]
```

---

*Verified 2026-05-25 against `https://www.sportsbet.com.au/apigw/...` from a logged-out anonymous client. Field shapes are reproduced from observed responses; absence of a field in this document means it was not observed in the sample payloads. Endpoint behaviour and field shapes are subject to change.*

## Tool reference

Every tool this provider registers. The sections above describe the underlying
services; this is the lookup from a tool name to what it does.


### `sportsbet.cross`

| Tool | What it does |
|---|---|
| `sportsbet_cms_messages` | Sitewide CMS messages (banners, notices). |
| `sportsbet_cms_page` | CMS page block by competition id or page path (one of the two is required). |
| `sportsbet_cms_settings` | Global CMS settings / feature flags for the app. |
| `sportsbet_event_status` | Live status flags for a sport event (suspended, in-play, settled). |
| `sportsbet_league_ladder` | League ladder / standings for a sport competition. |
| `sportsbet_match_preview` | Editorial match preview (text + video) for one sport event. |
| `sportsbet_page_content` | Homepage tab content (sports or racing landing modules). |
| `sportsbet_popular_promotions` | Trending / popular promotions for a promo provider + client. |
| `sportsbet_race_preview` | Editorial race preview (text + video) for one race. |
| `sportsbet_safer_gambling_message` | Current safer-gambling message block for the site. |
| `sportsbet_track_report` | Track report (going, rail, weather) for a racing meeting on a date. |
| `sportsbet_sgm_price` | **Prices a Same Game Multi you choose** — legs in, correlated price out. See below. |
| `sportsbet_trending_sgm` | Trending Same Game Multi (SGM) combinations for one sport event (pre-built by the book). |

### `sportsbet.graphql`

| Tool | What it does |
|---|---|
| `sportsbet_graphql_call` | Call any of Sportsbet's persisted GraphQL operations against
www.sportsbet.com.au/apigw/sportsbook/graph by name + variables. Hashes
are managed… |

### `sportsbet.racing`

| Tool | What it does |
|---|---|
| `sportsbet_multiple_racecards` | Racecards for several races in one call (batch by event ids). |
| `sportsbet_racecard` | Racecard for one race: runners, prices, scratchings. |
| `sportsbet_racecard_with_context` | Racecard plus surrounding context (meeting, results, related markets) for one race. |
| `sportsbet_racing_allracing` | All race meetings (every code) for one date, grouped by meeting. |
| `sportsbet_racing_best_bets` | Editorially-selected best bets across racing. |
| `sportsbet_racing_best_bets_with_events` | Best bets with their full parent event objects inlined. |
| `sportsbet_racing_challenges` | All racing challenges / promotions feed. |
| `sportsbet_racing_competition` | Racing competition (meeting) detail by competition id. |
| `sportsbet_racing_event_meeting` | Meeting context for one racing event (parent meeting + sibling races). |
| `sportsbet_racing_futures` | Racing futures markets (Cup outrights and other long-running racing markets). |
| `sportsbet_racing_megabets` | Racing Megabets (large multi suggestions across races). |
| `sportsbet_racing_multis_events` | Events available for racing multis, ordered by start (next-to-jump style feed). |
| `sportsbet_racing_popular_srms` | Popular Same Race Multi (SRM) combinations for races / meetings. |
| `sportsbet_racing_resulted_events` | Resulted races (placings + dividends) for a racing competition + class + date. |
| `sportsbet_racing_top_jockeys` | Top jockeys hub (leading jockeys and their rides today). |

### `sportsbet.results`

| Tool | What it does |
|---|---|
| `sportsbet_results_classes` | Sport classes that have results available for a date. |
| `sportsbet_results_competitions` | Competitions with results for a sport class on a date. |

### `sportsbet.sports`

| Tool | What it does |
|---|---|
| `sportsbet_bet_live` | BetLive feed — events currently in-play and bettable live. |
| `sportsbet_class_coupon` | Coupon (grouped markets) for a whole sport class. |
| `sportsbet_competition_matches` | Match-type events for a sport competition. |
| `sportsbet_competition_outrights` | Outright (futures) events for a sport competition. |
| `sportsbet_event_commentary` | Live score + text commentary for one or more sport events. |
| `sportsbet_event_markets` | All markets + selections + live prices for one sport event. |
| `sportsbet_event_results` | Results for a finished sport event (final score + settled markets). |
| `sportsbet_nav_hierarchy` | Sports navigation hierarchy (class → competition tree for menus). |
| `sportsbet_sport_card_legacy` | Legacy single sport event card (event + primary markets). |
| `sportsbet_sport_competition` | Sport competition page: matches, outrights and optional top markets. |
| `sportsbet_sport_resulted_events` | Resulted (finished) events for a sport competition + class + date. |
| `sportsbet_sports_card` | Full sport event card (all markets + selections) or the resulted event if finished. |
| `sportsbet_sports_classes` | Sport classes (sports) with their competitions for a date window. |
| `sportsbet_upcoming_events` | Upcoming sport events across all codes (homepage upcoming feed). |


---

## Pricing a Same Game Multi you chose

`sportsbet_sgm_price` is the only tool in this catalogue that prices a combination the
book has not already built. `sportsbet_trending_sgm` and the equivalents at other books
return *their* suggestions; this one takes your legs.

```
POST /apigw/multi-pricer/combinations/price
{
  "classExternalId": 103,          // Australian Rules
  "competitionExternalId": 17131,  // AFL
  "eventExternalId": 16374542,
  "outcomesExternalIds": [
    {"marketExternalId": 602153262, "outcomeExternalId": 2870628965},
    {"marketExternalId": 602153262, "outcomeExternalId": 2870628954}
  ]
}
→ {"price": {"quoteId": "…", "numerator": 7, "denominator": 5}}
```

Verified live 2026-08-25 against AFL Western Bulldogs v Collingwood: two legs 7/5, three
legs 10/3, one leg refused. **No authentication** — it answers a plain unauthenticated
POST.

### It wants EXTERNAL ids, and this is the trap

Sportsbet exposes **two id spaces**, and every other tool in this spec speaks the internal
one. The pricer speaks the other. Passing an internal id returns a bare `ERR-VE` that
names no field.

| the pricer wants | where it comes from | ⚠ not this |
|---|---|---|
| `classExternalId` | `sportsbet_nav_hierarchy` → class node `classExternalId` (103) | the node's `id` (50) |
| `competitionExternalId` | `sportsbet_nav_hierarchy` → competition node `competitionExternalId` (17131) | the node's `id` (4165) |
| `eventExternalId` | `sportsbet_competition_matches` → event `externalId` (16374542) | the event's `id` (10850856) |
| `marketExternalId` | `sportsbet_event_markets` → market `externalId` (602153262) | market `id` (251983151) |
| `outcomeExternalId` | `sportsbet_event_markets` → selection `externalId` (2870628954) | selection `id` (1244168027) |

### The price is fractional

`{numerator: 7, denominator: 5}` is **$2.40** — decimal is `1 + numerator/denominator`.
Reading it as 1.4, or as 7.5, reports a price well under the real one and would make a
poor SGM look good.

It is **not** the product of the legs. Sportsbet applies a correlation adjustment, which
is the whole reason to ask rather than multiply.

### Quotes expire

`quoteId` is a per-request token with a short life. Treat the answer as a quote, not a
cached fact — re-request rather than reusing one from minutes ago.

### Errors

Both observed live, both HTTP 400:

| code | meaning |
|---|---|
| `ERR-MP-001` | fewer than two outcomes — the pricer refuses a single leg |
| `ERR-VE` | body failed schema validation, usually an `id` where an `externalId` belongs |

Legs the book will not combine are refused rather than priced.
