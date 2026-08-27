# Ladbrokes (Entain / Neds Platform) API Documentation

Unofficial reference for the public JSON and GraphQL endpoints served by Ladbrokes Australia at `api.ladbrokes.com.au` and `www.ladbrokes.com.au/cdn/*`. Ladbrokes AU runs on the same back-end as Neds, Bookmaker.com.au and the BetStar / Neds Pro brands — error envelopes consistently leak `neds.api.{service}.{Service}.{Method}` upstream RPC names.

> **Base URLs:**
> - **REST/GraphQL API:** `https://api.ladbrokes.com.au`
> - **CDN proxies** (Contentful CMS, racing form, video streams): `https://www.ladbrokes.com.au/cdn/*` and `https://www.ladbrokes.com.au/videos/*`
>
> All endpoints and shapes here were verified against live traffic on 2026-05-25 from an anonymous client. Where a hash or operation could not be verified live, it is marked accordingly.

---

## Table of Contents

- [Required headers](#required-headers)
- [Architecture notes](#architecture-notes)
- [Conventions](#conventions)
  - [IDs](#ids)
  - [GraphQL ID prefixes](#graphql-id-prefixes)
  - [Sport category enum (`SportingCategory`)](#sport-category-enum-sportingcategory)
  - [Racing category enum (`RacingCategory`)](#racing-category-enum-racingcategory)
  - [Other GraphQL enums](#other-graphql-enums)
  - [Error envelopes](#error-envelopes)
  - [Time format](#time-format)
- [REST: Domain-featured](#rest-domain-featured)
- [REST: Racing](#rest-racing)
- [REST: Sport](#rest-sport)
- [REST: Event metadata](#rest-event-metadata)
- [REST: Metadata / SEO](#rest-metadata--seo)
- [REST: Video](#rest-video)
- [REST: Insights (telemetry)](#rest-insights-telemetry)
- [REST: Contentful CDN proxy](#rest-contentful-cdn-proxy)
- [REST: Form guide CDN proxy](#rest-form-guide-cdn-proxy)
- [GraphQL gateway (`/gql/router`)](#graphql-gateway-gqlrouter)
  - [Persisted-query semantics](#persisted-query-semantics)
  - [Hash drift — critical caveat](#hash-drift--critical-caveat)
  - [POST fallback (full query body)](#post-fallback-full-query-body)
- [GraphQL operations — verified in detail](#graphql-operations--verified-in-detail)
  - [SportingCategories](#sportingcategories)
  - [SportingCategoryScreen](#sportingcategoryscreen)
  - [SportingCompetitionScreen](#sportingcompetitionscreen)
  - [SportingEventScreen](#sportingeventscreen)
  - [SportingInPlayScreen](#sportinginplayscreen)
  - [SportingIconSets](#sportingiconsets)
  - [HomeSportsScreen](#homesportsscreen)
  - [RacingRaceCardScreenWeb](#racingracecardscreenweb)
  - [RacingListPopularSameRaceMultis](#racinglistpopularsameracemultis)
  - [RacingVideoChannels](#racingvideochannels)
- [GraphQL operations — full catalogue (127 entries)](#graphql-operations--full-catalogue-127-entries)
- [Endpoint quick reference](#endpoint-quick-reference)
- [Internal RPC names (not directly callable)](#internal-rpc-names-not-directly-callable)

---

## Required headers

Every request — including `GET` — **must send `Content-Type: application/json`**. Without it the gateway returns `HTTP 500` with body `unsupported content-type`. This applies uniformly to REST and GraphQL.

Minimum working header set:

```bash
curl 'https://api.ladbrokes.com.au/v2/sport/event-card?id=339e26d0-72a8-49bc-a85f-a2d02c0a1a70' \
  -H 'User-Agent: Mozilla/5.0' \
  -H 'Origin: https://www.ladbrokes.com.au' \
  -H 'Referer: https://www.ladbrokes.com.au/' \
  -H 'Content-Type: application/json'
```

CORS is whitelisted to `Access-Control-Allow-Origin: https://www.ladbrokes.com.au` (not `*`). Cloudflare bot-management cookie `__cf_bm` is dropped on every response. Rate-limit policy is not documented but read traffic appears generous (~1 MB responses are normal).

---

## Architecture notes

When upstream RPCs fail, the error envelope leaks the back-end:

```json
{
  "code": 500,
  "detail": "error during request: an error occurred while calling neds.api.racing.Racing.BatchGetMeetings: rpc: can't find method Racing.BatchGetMeetings",
  "id": "go.micro.api",
  "status": "Internal Server Error"
}
```

Confirmed:

- **Stack:** `go-micro` JSON-over-HTTP gateway (`id: go.micro.api`).
- **Service namespace:** `neds.api.*`. Services observed:
  - `neds.api.racing.Racing.*` — meetings, races, entrants, markets, prices.
  - `neds.api.racing.RacingV2.*` (and `RacingV3.*`) — newer variants seen in the JS bundle.
  - `neds.api.domain-featured.DomainFeatured.*` / `.DomainFeaturedV2.*` — homepage tiles.
  - `neds.api.metadata.Metadata.*` — SEO metadata.
  - `neds.api.video.VideoV2.*` — racing video.
  - `neds.api.event.Event.*` — sport markets, market rules, market-type groups.
  - `neds.api.sport.Sport.*` — sport event card, event request.
- **GraphQL gateway** (`/gql/router`) is an Apollo-style server with persisted queries, fronting all of the above. **127 named operations** are baked into the production JS bundle.
- **Form guides** are proxied through `www.ladbrokes.com.au/cdn/ladbrokes/form/...` (Racing & Sports).
- **CMS** is **Contentful** (space `5pu2kqpl2a5n`), proxied through `www.ladbrokes.com.au/cdn/contentful/...`.

---

## Conventions

### IDs

Every domain object (event, race, meeting, market, entrant, region, category, competition, team) is a **UUID v4** string. Examples from production:

| Domain | Example |
|---|---|
| Sport root category | `4d54ccd1-17b0-40c3-a7e2-be08ced1e7d0` |
| Racing root category | `2b665a75-16dd-4713-a85b-8e47631028b1` |
| Sport event (NBA) | `339e26d0-72a8-49bc-a85f-a2d02c0a1a70` |
| Race | `b740aecb-2010-47d3-a6c8-fc60ced4031d` |
| Meeting | `13a288c4-07f9-5cd3-8abe-d11e512b758c` |
| Competition (NBA) | `2d20a25b-6b96-4651-a523-442834136e2d` |
| Competition (AFL) | `ccff2e9a-5347-41aa-902a-bb6b1886d817` |
| Sport entrant (player) | `04ebf307-36d2-482a-a549-5384cd2214f6` |

Some IDs are **UUID v5** (recognisable by the `5` in the third group, e.g. `13a288c4-07f9-5cd3-8abe-d11e512b758c`) — those are content-derived (meetings, market type groups). Race IDs and event IDs are pure v4.

### GraphQL ID prefixes

The GraphQL gateway prefixes every UUID with a type tag, separated by `:`:

| Prefix | Example |
|---|---|
| `RacingRace:` | `RacingRace:b740aecb-2010-47d3-a6c8-fc60ced4031d` |
| `RacingRaceCard:` | `RacingRaceCard:179247bf-da00-41f8-b9c8-7a9da3e45f86` |
| `RacingMeeting:` | `RacingMeeting:13a288c4-07f9-5cd3-8abe-d11e512b758c` |
| `RacingEntrant:` | `RacingEntrant:736c3ce6-bdb2-4810-8242-d2cb89e44ccc` |
| `RacingMarket:` | `RacingMarket:ae198856-3cec-4165-9edc-b73ecfcbb99d` |
| `SportingEvent:` | `SportingEvent:339e26d0-72a8-49bc-a85f-a2d02c0a1a70` |
| `SportingCompetition:` | `SportingCompetition:2d20a25b-6b96-4651-a523-442834136e2d` |
| `SportingTeam:` | `SportingTeam:67dac75f-eb64-4b41-b7fa-e16519086d32` |
| `SportingMarket:` | `SportingMarket:295023bc-f67b-4d0c-bb36-59e733ecc1a2` |
| `SportingEntrant:` | `SportingEntrant:56c5a938-4ade-427a-b8f9-0e468ef6c280` |
| `QuickLink:` | `QuickLink:e3e2e76c-773d-4207-93a3-f06c67ce6208` |

REST endpoints generally take the bare UUID (no prefix); GraphQL operations almost always require the prefixed form. **Variable type `ID!` expects the prefixed form; type `UUID!` expects the bare UUID.** The schema-level distinction is sometimes blurry, so when in doubt try both — the gateway is explicit in its error messages (`Variable "$id" got invalid value "..."`).

### Sport category enum (`SportingCategory`)

Verified live via `SportingCategories` GraphQL operation. All 26 values currently registered:

| Enum value | Display name | UUID | hasRegions | Slug |
|---|---|---|---|---|
| `AMERICAN_FOOTBALL` | American Football | `a19fe930-3d0c-4f23-9cd4-12132fcc6b0a` | false | `american-football` |
| `AUSTRALIAN_RULES` | Australian Rules | `23d497e6-8aab-4309-905b-9421f42c9bc5` | false | `australian-rules` |
| `BASEBALL` | Baseball | `02721435-4671-4cd0-98f7-15d41ee4103e` | false | `baseball` |
| `BASKETBALL` | Basketball | `3c34d075-dc14-436d-bfc4-9272a49c2b39` | **true** | `basketball` |
| `BOXING` | Boxing | `a8217d48-3257-402b-b3b5-9db706fdc1e0` | false | `boxing` |
| `CRICKET` | Cricket | `94984918-dbac-432b-b420-c219ec9203f4` | false | `cricket` |
| `CYCLING` | Cycling | `a392063b-7be0-48c8-aa8b-2965e0508dba` | false | `cycling` |
| `DARTS` | Darts | `bfe01e5c-664b-4a3a-ba5a-ab15da108c7d` | false | `darts` |
| `ESPORTS` | Esports | `e89fbf3f-7ed4-47b4-923e-6febc6691ac9` | **true** | `esports` |
| `GOLF` | Golf | `24d4f135-aeec-4671-a4a3-f4cf555105ab` | false | `golf` |
| `HANDBALL` | Handball | `b66ac710-c8d3-4cf7-beb3-733f6dff6fa8` | **true** | `handball` |
| `ICE_HOCKEY` | Ice Hockey | `b7c1f944-d02b-4d9b-b6f3-cb31389cfe36` | **true** | `ice-hockey` |
| `MIXED_MARTIAL_ARTS` | Mixed Martial Arts | `2768e4b7-effa-4bd1-929d-2e27f46af4f6` | false | `mma` |
| `MOTOR_SPORT` | Motor Sport | `fff64442-44f4-40d2-b830-5fa9b1bdf9e4` | false | `motor-sport` |
| `NETBALL` | Netball | `105f897d-706b-4ff5-a753-80d08004f6d7` | false | `netball` |
| `NOVELTY` | Novelty | `728204b2-6420-4be9-beb5-1a31aabae6e7` | false | `novelty` |
| `POLITICS` | Politics | `36b54c85-d551-4150-9632-fd65f3acbc98` | **true** | `politics` |
| `POOL` | Pool | `4ed8329a-4f42-46ab-b204-b76fd5e2f37c` | false | `pool` |
| `RUGBY_LEAGUE` | Rugby League | `608a1803-45bc-465a-8471-c89dcb68a27d` | false | `rugby-league` |
| `RUGBY_UNION` | Rugby Union | `33b58e1b-fb14-4cd8-98a7-c03fe6a8ea57` | false | `rugby-union` |
| `SNOOKER` | Snooker | `9641d713-66ae-4e38-af55-c0249ec15e7a` | false | `snooker` |
| `SOCCER` | Soccer | `71955b54-62f6-4ac5-abaa-df88cad0aeef` | **true** | `soccer` |
| `TABLE_TENNIS` | Table Tennis | `b92b2d14-10f7-46c7-8655-16eeed36ec4b` | false | `table-tennis` |
| `TENNIS` | Tennis | `a0b910b8-85f0-4f6e-821d-c9fd9e3bdf93` | false | `tennis` |
| `VOLLEYBALL` | Volleyball | `c16422dc-2e08-4512-bd42-4ca72a3cdc35` | **true** | `volleyball` |

`hasRegions` flags whether the category is sub-divided by region in the URL/nav (e.g. Basketball → USA → NBA; Soccer → many regions). Categories with `hasRegions: false` jump straight from the category page to competitions.

### Racing category enum (`RacingCategory`)

Three values, inferred from REST `category` fields and JS source:

| Enum value | Display name | UUID |
|---|---|---|
| `HORSE` | Horse Racing | `4a2788f8-e825-4d36-9894-efd4baf1cfae` |
| `HARNESS` | Harness Racing | `9daef0d7-bf3c-4f50-921d-8e818c60fe61` |
| `GREYHOUND` | Greyhound Racing | `161d9be2-e909-4326-8c2c-35ed71fb460b` |

Some operations (`RacingHomeScreenWeb`, `RacingExtrasScreenWeb`) split these into three separate Boolean variables (`horse`, `harness`, `greyhound`) rather than the enum array — the JS does this so a single query can request a mixed set without expanding into an enum list.

### Other GraphQL enums

Extracted from variable-definition signatures across the 127 operations:

| Enum | Values observed |
|---|---|
| `SportingMarketStatus` | `OPEN`, `LIVE`, `CLOSED`, `SUSPENDED` |
| `SportingEventsGroup` | `UNSPECIFIED`, `CATEGORY`, `LEAGUE` |
| `SportingEventType` | `MATCH`, `OUTRIGHT`, `FUTURE` |
| `QuickLinkPlatform` | `NATIVE`, `MOBILE_WEB`, `DESKTOP`, `MOBILE` |
| `QuickLinkType` | (used by `SportingLandingScreen.featuredEventsType`) |
| `RacingCountryCode` | `AU`, `NZ`, `HK`, `UK`, `IRE`, `FR`, `SAF`, … |
| `Region` | (slugged regions; see Sport categories) |
| `RacingFuturesGroup` | `UNSPECIFIED`, `CATEGORY`, `MEETING`, `EVENT` |
| `RacingEntrantOrder` | sort options for entrants on extras markets |
| `BetStatus` | `WON`, `LOST`, `VOID`, `REFUND`, `PENDING`, `CASH_OUT`, … |
| `PendingBetsSortOrder` | sort options for pending-bets list |
| `BlackbookListEntriesOrderBy` | sort options for blackbook |
| `BlackbookListEntriesView` | view scopes for blackbook |
| `RacingClubPostType`, `RacingClubAuthorType`, `RacingClubBallotType`, `RacingClubBallotFilterStatus`, `RacingClubBallotOrder`, `RacingClubBallotEntryOutcome`, `RacingClubBallotEntryOrder`, `RacingClubListRunnerOrder` | racing club / loyalty / promotions |
| `GamingActivityResultType`, `GamingBonusType`, `GamingCategoryView`, `GamingGameOrder`, `GamingFeedPostType`, `GamingGameTileVariant` | casino / gaming |
| `Subdivision` | promo subdivision (per-state for AU) |
| `PromotionEligibility` | promo gating |
| `WalletType` | bonus / cash wallet distinction |
| `PromotionsPromotionType` | promo categorisation |
| `RacingExcludedCategoriesInput` | input object for SRM listings |
| `DateRange` | `{ start: DateTime!, end: DateTime! }` |
| `ToolboxExclusiveOddsRacingEntrantFilter` | trader-toolbox filter input |

Mutation input objects (also baked into the bundle):

```
BetslipInput, CreateBetStakeLimitInput, CreateBlackbookEntryInput, CreateExperienceBookingInput,
DeleteBlackbookEntryInput, DeclineExpressionOfInterestInput, EnterRacingClubBallotInput,
RegisterExpressionOfInterestInput, RacingClubFollowInput, RacingClubUnfollowInput,
UpdateBetStakeLimitInput, UpdateBlackbookEntryInput
```

### Error envelopes

```jsonc
// Missing required parameter
{ "code": 400, "detail": "filter is required", "id": "neds.api.domain-featured", "status": "Bad Request" }

// Wrong parameter type (e.g. filter passed as string when JSON object expected)
{ "code": 500, "detail": "error during request: ... json: cannot unmarshal string into Go struct field ...", "id": "go.micro.api", "status": "Internal Server Error" }

// Unrouted RPC
{ "code": 500, "detail": "error during request: ... rpc: can't find method ...", "id": "go.micro.api", "status": "Internal Server Error" }

// No upstream available
{ "id": "go.micro.api", "code": 500, "detail": "none available", "status": "Internal Server Error" }

// Missing Content-Type header
HTTP 500, content-type: text/plain, body: "unsupported content-type"

// GraphQL: persisted hash not currently registered
{ "errors": [{ "message": "PersistedQueryNotFound", "extensions": { "code": "PERSISTED_QUERY_NOT_FOUND" } }] }

// GraphQL: variable missing/invalid
{ "errors": [{ "message": "Variable \"$raceId\" of required type \"ID!\" was not provided." }] }
```

### Time format

- REST: **RFC 3339 UTC** (`2026-05-25T03:30:00.000Z`) **and** Protobuf-style `{"seconds": 1779671372}` (older `/rest/v1/...` endpoints).
- GraphQL: RFC 3339 UTC throughout.
- Date-only inputs: `YYYY-MM-DD`.
- Timezone parameter: IANA TZ database name URL-encoded (`Australia%2FMelbourne`, `Australia%2FSydney`, `Pacific%2FAuckland`).

---

## REST: Domain-featured

### `ListQuickLinks`

| | |
|---|---|
| **Method / Path** | `GET /v2/domain-featured/domain-featured-v2/ListQuickLinks` |
| **Upstream** | `neds.api.domain-featured.DomainFeaturedV2.ListQuickLinks` |

**Required query parameter**

| Name | Type | Description |
|---|---|---|
| `filter` | JSON-encoded `QuickLinkFilter` object | E.g. `{"type":"Racing"}`. Passing a string returns 500. |

Verified call (URL-encoded): `?filter=%7B%22type%22%3A%22Racing%22%7D` → 200, ~18 KB.

```jsonc
{
  "quick_links": [
    {
      "id": "9299fa27-...",
      "root_category_id": "2b665a75-...",
      "category_id": "4a2788f8-...",
      "url": "/racing",
      "title": "Racing",
      "start_time": "2020-04-06T23:06:00Z",
      "visible": true,
      "icon": "racing-horse-racing",
      "priority": 1,
      "is_quick_link": true,
      "title_desktop": "Racing",
      "title_mobile": "Racing",
      "event_id": "00000000-0000-0000-0000-000000000000",
      "platforms": ["QUICK_LINK_PLATFORM_NATIVE", "QUICK_LINK_PLATFORM_MOBILE_WEB", "QUICK_LINK_PLATFORM_DESKTOP"]
    }
  ]
}
```

`event_id == "00000000-0000-0000-0000-000000000000"` is the sentinel for "no event attached" (category-only links).

### `featured-slider-events`

| | |
|---|---|
| **Method / Path** | `GET /v2/domain-featured/DomainFeatured/featured-slider-events` |
| **Upstream** | `neds.api.domain-featured.DomainFeatured.FeaturedSliderEvents` |

Verified call → 200, ~6 KB.

```jsonc
{
  "items": [
    {
      "id": "e3e2e76c-...",
      "title": "Cleveland Cavaliers vs New York Knicks",
      "title_desktop": "Cleveland Cavaliers vs New York Knicks",
      "title_mobile": "Cleveland",
      "url": "/sports/basketball/usa/nba/cleveland-cavaliers-vs-new-york-knicks/339e26d0-...",
      "icon": "sports-basketball",
      "priority": 4,
      "root_category_id": "4d54ccd1-...",
      "category_id": "3c34d075-...",
      "event_id": "339e26d0-...",
      "is_featured_event": true,
      "event": {
        "id": "00000000-0000-0000-0000-000000000000",
        "advertised_start": "0001-01-01T00:00:00Z",
        "competition_id": "2d20a25b-...",
        "event_start": "2026-05-26T00:10:00Z",
        "visible": true
      },
      "is_featured_slider_event": true,
      "platforms": ["QUICK_LINK_PLATFORM_NATIVE", "QUICK_LINK_PLATFORM_MOBILE_WEB", "QUICK_LINK_PLATFORM_DESKTOP"]
    }
  ]
}
```

---

## REST: Racing

### `racing/meeting`

| | |
|---|---|
| **Method / Path** | `GET /v2/racing/meeting` |

**Required**

| Name | Type | Description |
|---|---|---|
| `date` | `YYYY-MM-DD` | Race date. |
| `timezone` | IANA TZ (URL-encoded) | E.g. `Australia%2FMelbourne`. |

Verified call → 200, ~415 KB. Returns five normalised UUID-keyed tables:

```jsonc
{
  "compounds":          { /* exotic / multi-race products */ },
  "domestic_countries": "AUS,NZ,HK",
  "meetings":           { /* meetings (UUID v5) */ },
  "races":              { /* races (UUID v4) */ },
  "venues":             { /* track / facility metadata */ }
}
```

`compounds[<id>]` shape — multi-race product (e.g. Quadrella, EarlyQuadrella, RunningDouble, BigSix, DailyDouble):

```jsonc
{
  "id":              "0d416b03-...",
  "meeting_id":      "13a288c4-...",
  "product_type_id": "e7388290-...",
  "name":            "Quadrella",
  "race_ids":        ["e53ac842-...", "04e1bcf3-...", "b0aa31c9-...", "302cdd57-..."]
}
```

### `racing/next-races-category-group`

| | |
|---|---|
| **Method / Path** | `GET /v2/racing/next-races-category-group` |

**Required**

| Name | Type | Description |
|---|---|---|
| `count` | int | Races per category. |
| `categories` | JSON UUID array (URL-encoded) | Racing categories. |

Verified call → 200, ~32 KB.

```jsonc
{
  "category_race_map": {
    "<category_id>": { "race_ids": ["<race_id>", "..."] }
  },
  "race_summaries": {
    "<race_id>": {
      "race_id":          "0b980d28-...",
      "race_name":        "Race 9",
      "race_number":      9,
      "meeting_id":       "c860b7bf-...",
      "meeting_name":     "Woodbine Mohawk Park",
      "category_id":      "161d9be2-...",
      "advertised_start": "2026-05-25T01:34:00Z",
      "race_form": {
        "distance":        1609,
        "distance_type":   { "name": "Metres",   "short_name": "m" },
        "track_condition": { "name": "Good",     "short_name": "good" },
        "weather":         { "name": "Overcast" },
        "race_comment":    "PASSARINO (2) produced a better effort last time out..."
      }
    }
  }
}
```

### `racing/search`

| | |
|---|---|
| **Method / Path** | `GET /v2/racing/search` |

Verified call (no parameters) → 200, ~4 KB. Returns aggregate facet buckets:

```jsonc
{
  "facets": {
    "barrier":  { "buckets": [ { "value": "4", "count": 233 }, { "value": "9+", "count": 161 }, ... ] },
    "country":  { "buckets": [ { "value": "AU", "count": 1578 }, { "value": "UK", "count": 276 }, ... ] },
    "jockey":   { "buckets": [ { "value": "DAMIEN THORNTON", "count": 8 }, ... ] },
    "trainer":  { "buckets": [ /* ... */ ] }
  }
}
```

Full-text search is supported by additional parameters (`q=`, `category_ids=`); JS references but exact contract was not verified.

### `rest/v1/racing/?method=future-markets`

Legacy v1 racing endpoint. `?method=...` selects the upstream RPC.

| | |
|---|---|
| **Method / Path** | `GET /rest/v1/racing/?method=future-markets` |

| Parameter | Type | Description |
|---|---|---|
| `method` | string | RPC method. Observed: `future-markets`. |
| `exclude` | JSON object | Field mask. Web client passes `{"markets":true,"prices":true,"entrants":true}`. |

Verified → 200, ~76 KB. Note the Protobuf timestamp shape.

```jsonc
{
  "status": 200,
  "data": {
    "races": {
      "<race_id>": {
        "id":                "023044b2-...",
        "meeting_id":        "944a509d-...",
        "name":              "Prix de Diane 2100m (All In)",
        "advertised_start":  { "seconds": 1781445600 },
        "actual_start":      { "seconds": 1781445600 },
        "feed_source_id":    "82ad9e41-...",
        "feed_id":           "023044b2-...",
        "visible":           true,
        "auto_result":       true,
        "reminders_available": true
      }
    }
  },
  "message": null
}
```

---

## REST: Sport

### `sport/event-card`

Complete event card — every market, every selection, every price for one event.

| | |
|---|---|
| **Method / Path** | `GET /v2/sport/event-card` |

| Parameter | Type | Description |
|---|---|---|
| `id` | UUID | Sport event ID (bare UUID, no prefix). |

Verified → 200, ~1.16 MB. Eight normalised UUID-keyed tables:

```text
entrants, event_participants, events, market_type_groups,
markets, markets_allow_cashout, prices, regions
```

`entrants[<id>]`:

```jsonc
{
  "id":         "04ebf307-...",
  "name":       "James Harden (Cleveland Cavaliers)",
  "visible":    true,
  "sort_order": 70,
  "market_id":  "748a80d0-..."
}
```

`prices` is keyed by `<entrant_id>:<product_type_id>:` (trailing colon present even when there is no third segment).

### `same-game-multi/GetOdds`

Prices a same game multi you build yourself. No auth, no key.

| | |
|---|---|
| **Method / Path** | `GET /v2/same-game-multi/GetOdds` |

| Parameter | Type | Description |
|---|---|---|
| `same_game_multies` | JSON | Map keyed by event id — see below. |

```jsonc
// same_game_multies (URL-encoded into the query string)
{"eccdc4f5-e01e-4aca-afab-570869b53702": {
   "event_id": "eccdc4f5-e01e-4aca-afab-570869b53702",   // MUST equal the key
   "selections": [
     {"market_id": "c73591e5-…", "entrant_id": "49475673-…"},
     {"market_id": "2bc6b298-…", "entrant_id": "8ada7d51-…"}]}}

→ {"prices": {"eccdc4f5-e01e-4aca-afab-570869b53702":
     {"available": true, "odds": {"numerator": 27, "denominator": 10}}}}
```

Both ids per selection come from `sport/event-card`: `market_id` is a key of `markets`,
`entrant_id` a key of `entrants`. The map key and the inner `event_id` are **not**
redundant — a mismatch returns `400 event id must match key`. The map shape is also the
batch: several events price in one call and each is answered independently under its own
key.

> **`27/10` is 3.70.** Prices are fractional and **decimal = numerator/denominator + 1**.
> Confirmed against the site's own displayed odds on the verified event: Melbourne showed
> 2.15 and returns `23/20`; Over showed 1.88 and returns `22/25`. Every price in
> `sport/event-card` uses the same shape, so this is the provider's convention rather than
> this endpoint's quirk. Dropping the `+1` understates every price — the quiet direction to
> be wrong in, because nothing looks alarming; the book just appears to price worse than it
> does.

**The price is not the product of the legs.** Verified live 2026-08-27 against AFL
Melbourne v Carlton: Melbourne (2.15) with Over 173.5 (1.88) prices **3.70**, against a
naive 4.042.

**The best refusal diagnostics of any book here.** When Entain detects a clash it names
the exact pair:

```jsonc
{"available": false,
 "conflicting_selections": [{"entrant_id": "49475673-…", "market_id": "c73591e5-…"},
                            {"entrant_id": "b7eeb49e-…", "market_id": "947b8133-…"}]}
```

It correctly refused Over with Under, both line sides, two margin bands, and cross-market
impossibilities such as *Melbourne to win* with *Carlton by 1-39*.

**…but the detector is not complete, and the gap is expensive.** Every exactly-two-entrant
SGM-available market on the verified event was tested — 41 of them. Thirty-five correctly
refused their mutually exclusive pair. **Five priced it:**

| Market | Impossible pair | Quoted |
|---|---|---|
| Match Betting | Melbourne + Carlton | **146.51** |
| 4th Quarter Match Betting | Carlton + Melbourne | 81.67 |
| 3rd Quarter Match Betting | Carlton + Melbourne | 74.50 |
| 1st Quarter Match Betting | Carlton + Melbourne | 72.29 |
| 2nd Quarter Match Betting | Carlton + Melbourne | 70.78 |

The failing set is the **win-market family with two entrants and an implicit draw**. The
three-entrant version that lists `Tie` as an entrant (`1st Half Betting`) is refused
correctly, which is what makes the pattern legible.

A bet that cannot win, quoted at 146.51 with availability saying yes, is indistinguishable
from a longshot with enormous edge — exactly what an automated value screener hunts for.
**Never treat `available: true` as proof a combination is coherent.**

#### Two client-side defences

Nothing in the payload marks mutual exclusivity, so there is no complete rule that keeps
every legitimate same-market pair. There are two things a caller can do, and together they
remove the class:

1. **Honour `same_game_multi_available`, because the pricer ignores its own flag.** The
   event card marks 21 of this event's markets as not SGM-available; pairing 14 of them
   with an ordinary Match Betting leg, **12 priced anyway**. Two of the worst impossible
   quotes come from exactly there — `Highest Scoring Half` at 143.65 and `1st Half Match
   Betting` at 110.18 are both flagged unavailable and both priced. Filtering on the flag
   before you build is free and catches them.
2. **Do not combine two legs from the same `market_id`** unless you understand that market.
   Every hole found is a same-market pair. Legitimate same-market pairs do exist — nested
   `Alternate Handicaps` / `Alternate Total Points` lines, and multi-winner props like
   `Player Goals - Anytime Goal Kicker` — so a blanket rule costs a little coverage. For a
   cross-book comparator, which combines *different* markets anyway, that cost is close to
   zero.

> **`num_winners` is not the answer — it was tried.** It looks exactly like an exclusivity
> flag and means neither thing reliably: `Melbourne Alternate Handicaps` is `num_winners: 1`
> with 96 nested lines that legitimately combine, while `Race To 15` is `num_winners: 3`
> with two mutually exclusive entrants. It appears to be a settlement field, not a logical
> one.

One near-miss worth recording so it is not re-flagged later: `To Win Either Half` with both
teams prices at 1.80 and that is **correct** — Melbourne can win the first half and Carlton
the second. Short prices on same-market pairs are usually legitimate; the impossible ones
all came back long (70–146).

**Two more.** A redundant leg is **silently collapsed** with `available` still true and no
echo of the legs: *Melbourne to win* plus *Melbourne on the line* returned `23/20` — 2.15,
the single-leg price. Repeating one selection does the same. And an unknown event returns
`available: false` with **no `odds` key at all**, quietly, alongside the events that did
price; there is no fake zero to guard against here, but a missing `odds` must not be read
as one.

Malformed requests are real HTTP 400s that name the problem — a selection missing
`market_id` or `entrant_id`, or the key/`event_id` mismatch above.

### `sport/event-request`

Bulk fetch for one or more sport categories — events, markets, prices and entities all returned in a single response.

| | |
|---|---|
| **Method / Path** | `GET /v2/sport/event-request` |

| Parameter | Type | Description |
|---|---|---|
| `category_ids` | JSON UUID array | Sport categories to include. |

Verified `?category_ids=["3c34d075-..."]` (Basketball) → 200, ~179 KB. Top-level keys:

```text
category_ids, entrants, event_participants, events,
markets, markets_allow_cashout, next_events, prices, regions
```

`next_events` is an additional list of 20 upcoming events for in-page navigation.

---

## REST: Event metadata

### `event/MarketRules`

Settlement rules for every named market, indexed by ID.

| | |
|---|---|
| **Method / Path** | `GET /v2/event/MarketRules` |

Verified → 200, ~83 KB.

```jsonc
{
  "market_rules": {
    "<rule_id>": {
      "id":          "020a6a35-...",
      "name":        "A Perfect 2026 For Keayang Zahara",
      "description": "Keayang Zahara to go undefeated throughout 2026. Requires 6 or more starts between 11/4/26 and 31/12/26 or bets void."
    },
    "<rule_id>": {
      "id":          "08016b1d-...",
      "name":        "Final Field",
      "description": "Bets struck after the final field is declared are eligible for a full refund on scratched horses or greyhounds"
    }
  }
}
```

### `event/MarketTypeGroupsByCategoryID`

Market-tab definitions for a category.

| | |
|---|---|
| **Method / Path** | `GET /v2/event/MarketTypeGroupsByCategoryID` |

| Parameter | Type | Description |
|---|---|---|
| `category_id` | UUID | Sport category. |

Verified (Basketball) → 200, ~9 KB.

```jsonc
{
  "market_type_group": [
    { "id": "2396ba5b-...", "category_id": "3c34d075-...", "name": "Player PR Markets",  "priority": 970, "type": "MARKET_TYPE_GROUP_TYPE_EVENT" },
    { "id": "9b4de0a7-...", "category_id": "3c34d075-...", "name": "Odd/Even Markets",   "priority": 70,  "type": "MARKET_TYPE_GROUP_TYPE_EVENT" },
    { "id": "23aa361f-...", "category_id": "3c34d075-...", "name": "1st Quarter Markets","priority": 60,  "type": "MARKET_TYPE_GROUP_TYPE_EVENT" }
  ]
}
```

Lower `priority` renders first.

### `event/MarketTypeGroupMapsByCategoryID`

The join table between market types and market type groups.

| | |
|---|---|
| **Method / Path** | `GET /v2/event/MarketTypeGroupMapsByCategoryID` |

| Parameter | Type | Description |
|---|---|---|
| `category_id` | UUID | Sport category. |

Verified → 200, ~834 KB (`market_type_group_map` list of 3602 entries — duplicates present, dedup by `(market_type_id, market_type_group_id)`).

```jsonc
{
  "market_type_group_map": [
    {
      "id":                   "19e45523-...",
      "market_type_id":       "a5a9e9c9-...",
      "market_type_group_id": "dd212e21-...",
      "category_id":          "00000000-0000-0000-0000-000000000000",
      "priority":             370
    }
  ]
}
```

---

## REST: Metadata / SEO

### `metadata/GetByURL`

SEO metadata (page title) for a given URL path.

| | |
|---|---|
| **Method / Path** | `GET /v2/metadata/GetByURL` |

| Parameter | Type | Description |
|---|---|---|
| `url` | string | URL path. |

Verified calls:

- `?url=/racing` → 200: `{"metadata":{"title":"Racing Betting Odds Today","url":"/racing"}}`
- `?url=/sports` → 200: `{}` (no override; front-end falls back to default).

---

## REST: Video

### `video/video-v2/ListChannels`

| | |
|---|---|
| **Method / Path** | `GET /v2/video/video-v2/ListChannels` |
| **Upstream** | `neds.api.video.VideoV2.ListChannels` |

Verified → 200, ~400 B.

```json
{
  "channels": [
    { "id": "2c184b7b-...", "name": "live-2", "url": "https://www.ladbrokes.com.au/videos/nep/channel2.m3u8?verify=1779671372-PVwfZd2yqk%2B04LVkSz9CRz1sK7pjF9Qp4XZNoXZ9SyY%3D" },
    { "id": "bd93ca0c-...", "name": "live-1", "url": "https://www.ladbrokes.com.au/videos/nep/channel1.m3u8?verify=1779671372-jEUcodxlKf81s3MS%2B7TQ546zRn68M8YlZ%2B1iiAbpeYw%3D" }
  ]
}
```

The `verify=<unix_expiry>-<base64-hmac>` parameter expires within minutes — re-call to refresh.

---

## REST: Insights (telemetry)

| Path | Method | Notes |
|---|---|---|
| `/insights/event` | `POST` | Telemetry pipeline. `GET` → 405; empty `POST` → 400. Accepts batched analytics events. |
| `/insights/error` | `POST` | Error-only variant. |
| `/insights/sync` | `POST` | Synchronous flush variant. |

Write-only — do not expect useful data as a consumer.

---

## REST: Contentful CDN proxy

Editorial / promotional content is served by Contentful at space `5pu2kqpl2a5n`, proxied through `www.ladbrokes.com.au`.

> **The proxy is on `www.ladbrokes.com.au`, not the API host.**

| | |
|---|---|
| **Method / Path** | `GET https://www.ladbrokes.com.au/cdn/contentful/api/spaces/5pu2kqpl2a5n/environments/master/entries` |

Standard Contentful Content Delivery API parameters:

| Parameter | Description |
|---|---|
| `content_type` | Content Type ID. Observed: `majorEventNavigation`, `promotions`, `nationallyApprovedPromotions`. |
| `fields.brand` | E.g. `Ladbrokes`. |
| `fields.startTime[lte]` | ≤ ISO timestamp. |
| `fields.dropTime[gt]` | > ISO timestamp. |
| `include`, `skip`, `limit`, `order` | Standard Contentful CDA. |

Verified `?content_type=promotions&fields.startTime[lte]=2026-05-25T01:20:00.000Z&fields.dropTime[gt]=2026-05-25T01:20:00.000Z&fields.brand=Ladbrokes` → 200, ~80 KB, `total: 20` items. Standard Contentful response envelope (`{ sys, total, skip, limit, items, includes }`).

---

## REST: Form guide CDN proxy

Racing form guides are served by Racing & Sports through `https://www.ladbrokes.com.au/cdn/ladbrokes/form/<race_id>`. The full form URL is also returned in `RacingRaceCardScreenWeb.raceCard.fullForm` (e.g. `https://ladbrokesform.com.au/form/179247bf-...`). HTML / asset bundle, not a JSON API.

---

## GraphQL gateway (`/gql/router`)

Single Apollo-style endpoint. Persisted queries are the primary front-end transport.

| | |
|---|---|
| **Method** | `GET` (persisted) or `POST` (full document fallback) |
| **Path** | `/gql/router` |
| **Host** | `api.ladbrokes.com.au` |
| **Content-Type** | `application/json` (required) |
| **Auth** | None for public operations; logged-in operations need a session cookie. |

### Persisted-query semantics

Three URL query parameters (URL-encoded JSON):

| Name | Type | Description |
|---|---|---|
| `operationName` | string | Registered operation name. |
| `variables`     | JSON object | Operation variables. |
| `extensions`    | JSON object | `{ "persistedQuery": { "version": 1, "sha256Hash": "<hex>" } }`. |

Full URL form:

```
https://api.ladbrokes.com.au/gql/router
  ?operationName=<OperationName>
  &variables=<URL-encoded JSON>
  &extensions=<URL-encoded JSON with persistedQuery hash>
```

### Hash drift — critical caveat

**The sha256 hash for each operation changes on every front-end deploy** (whenever the operation's document or any of its fragments change). The persisted-query layer caches **the hash currently registered by the deployed client** — so a fresh hash extracted from the latest JS bundle may return `PersistedQueryNotFound` (only the Apollo-gateway-registered set is accepted at any given moment).

Example observed on 2026-05-25:

- `RacingRaceCardScreenWeb` was registered with hash `7085b5bef9cd71304cbd8264c229ab347711e32e341d7eefd03920645eedff81` → call worked.
- The same operation's hash in the current `vendor-graphql-ops-web-*.js` bundle is `d59b563bacb7984ed87e6a843669aa7f02d03e93a0cc98f505f859c6190cbbc7` → call returned `PersistedQueryNotFound`.

Both hashes are valid documents — only one is currently registered. Worse, the gateway's APQ cache is **evictable**: on 2026-07-07 it flushed 113 of 127 registrations with no bundle change at all, so "the bundle's hash" and "the registered hash" can both go stale independently.

Since then the stack handles this end-to-end (an APQ pair only has to be *self-consistent* — `sha256Hash == sha256(query)` — not bundle-matching):

1. **Runtime self-heal**: the `graphql_persisted` dispatcher answers `PersistedQueryNotFound` by re-POSTing the operation's printed document from `specs/entain.documents.json` with its own sha256 (the standard Apollo APQ retry browsers do), which re-registers the pair and returns the data in the same call.
2. **`sportsdata-mcp refresh-hashes entain`** no longer trusts the bundle's manifest hashes: it extracts each operation's `Document` AST from the bundle, prints it with graphql-core, hashes the printed text, registers the pair with the gateway, and writes both the hashes (spec yaml) and the printed documents (`entain.documents.json` sidecar). It can therefore never "restore" dead evicted hashes.
3. `scripts/reseed_entain_apq.py` remains as a manual probe/bulk-reseed tool (`--dry-run` reports how many yaml hashes the gateway currently recognises).
4. The hashes listed in the [full operation catalogue](#graphql-operations--full-catalogue-127-entries) below are what the **JS bundle** registered at capture time — the live spec yaml is the source of truth.

### POST fallback (full query body)

When the persisted hash is unknown or rejected:

```http
POST /gql/router HTTP/1.1
Host: api.ladbrokes.com.au
Content-Type: application/json

{
  "operationName": "HomeSportsScreen",
  "query": "query HomeSportsScreen($includeFeaturedEvents: Boolean, ...) { featuredEvents(...) { nodes { ... } } ... }",
  "variables": { ... }
}
```

The query document and fragment set can be extracted from the JS bundle by parsing each operation's `Document` AST (the bundle stores them inline as `OperationDefinition` plus their referenced `FragmentDefinition` siblings).

---

## GraphQL operations — verified in detail

Each section below was live-verified on 2026-05-25 with the hash currently in the bundle.

### `SportingCategories`

The catalogue of all sport categories. Drives the sports nav side-menu.

| | |
|---|---|
| **Hash** | `e32cd40f8962491f27966f35327ea1f32de8603c2c39f50269232713e18ebd62` |
| **Variables** | `marketControlExclude: Boolean` |

```jsonc
// Variables
{ "marketControlExclude": false }
```

```jsonc
// Response (truncated)
{
  "data": {
    "categories": [
      {
        "id":         "a19fe930-3d0c-4f23-9cd4-12132fcc6b0a",
        "name":       "American Football",
        "category":   "AMERICAN_FOOTBALL",
        "icon":       "sports/american-football",
        "slug":       "american-football",
        "url":        "/sports/american-football",
        "hasRegions": false,
        "eventCount": 0
      },
      /* 25 more — see Sport category enum table above for full list */
    ]
  }
}
```

### `SportingCategoryScreen`

Per-category landing screen (e.g. `/sports/australian-rules`) — leagues, optional regions, optional futures grouped by league.

| | |
|---|---|
| **Hash** | `44a5f5b46e5c378682c3ebdc506cbc254ac76be05b72bd27b8d51636c6205aa2` |
| **Variables** | `category: SportingCategory!, statuses: [SportingMarketStatus!], excludeCategoryIds: [UUID!], includeRegions: Boolean, includeLeagues: Boolean, includeUpcomingEvents: Boolean, upcomingEventsCount: Int, upcomingEventsGroupBy: SportingEventsGroup, upcomingEventsStatuses: [SportingMarketStatus!], includeFutures: Boolean, futuresCountOnly: Boolean, futuresGroupBy: SportingEventsGroup` |

```jsonc
// Variables — AFL futures by league
{
  "category":               "AUSTRALIAN_RULES",
  "statuses":               ["OPEN", "LIVE"],
  "excludeCategoryIds":     [],
  "includeRegions":         false,
  "includeLeagues":         true,
  "upcomingEventsCount":    18,
  "upcomingEventsGroupBy":  "UNSPECIFIED",
  "upcomingEventsStatuses": ["OPEN"],
  "includeFutures":         true,
  "futuresGroupBy":         "LEAGUE"
}
```

```jsonc
// Response (truncated)
{
  "data": {
    "category": {
      "id":         "23d497e6-...",
      "name":       "Australian Rules",
      "category":   "AUSTRALIAN_RULES",
      "icon":       "sports/australian-rules",
      "slug":       "australian-rules",
      "url":        "/sports/australian-rules",
      "hasRegions": false,
      "eventCount": 0
    },
    "leagues": {
      "nodes": [
        { "id": "SportingCompetition:ccff2e9a-...", "name": "AFL", "url": "/sports/australian-rules/afl", "hasInPlayEvents": false, "region": null }
      ]
    },
    "futures": {
      "count": 7,
      "events": { "nodes": null },                  // null because futuresGroupBy is LEAGUE, not flat
      "leagues": {
        "nodes": [
          {
            "id":              "SportingCompetition:ccff2e9a-...",
            "name":            "AFL",
            "url":             "/sports/australian-rules/afl",
            "hasInPlayEvents": false,
            "region":          null,
            "events": {
              "nodes": [
                { "id": "SportingEvent:0c2e3ecc-...", "name": "AFL Premiership 2026",   "url": "/sports/australian-rules/afl/afl-premiership-2026/0c2e3ecc-...",   "sportCategory": { "id": "23d497e6-...", "icon": "sports/australian-rules" } },
                { "id": "SportingEvent:6f3764b6-...", "name": "AFL Brownlow 2026",       "url": "/sports/australian-rules/afl/afl-brownlow-2026/6f3764b6-...",       "sportCategory": { "id": "23d497e6-...", "icon": "sports/australian-rules" } },
                { "id": "SportingEvent:ce124490-...", "name": "AFL Rising Star 2026",   "url": "/sports/australian-rules/afl/afl-rising-star-2026/ce124490-...",   "sportCategory": { "id": "23d497e6-...", "icon": "sports/australian-rules" } },
                { "id": "SportingEvent:ab57afc7-...", "name": "AFL Coleman Medal 2026", "url": "/sports/australian-rules/afl/afl-coleman-medal-2026/ab57afc7-...", "sportCategory": { "id": "23d497e6-...", "icon": "sports/australian-rules" } }
              ]
            }
          },
          {
            "id":     "SportingCompetition:ed50e7f4-...",
            "name":   "VFL",
            "events": { "nodes": [ { "id": "SportingEvent:acdc0e1b-...", "name": "VFL Premiership 2026", ... } ] }
          }
        ]
      }
    }
  }
}
```

### `SportingCompetitionScreen`

Competition (league) screen with optional embedded events, futures, and sibling leagues.

| | |
|---|---|
| **Hash** | `1a346cbef31e3261c5f3d6e64a29e5acbaa76bdc3f00adb05a2f16dadc81c93e` *(bundle's current — gateway also still accepts the earlier `13650ba94d833bce4738d23bc1e85e428c28cea2aaa34574da381147ededed8c` hash)* |
| **Variables** | `category: SportingCategory!, regionSlug: String, competitionSlug: String!, excludeCategoryIds: [UUID!], statuses: [SportingMarketStatus!], includeLeagues: Boolean, includeUpcomingEvents: Boolean, upcomingEventsCount: Int, upcomingEventsGroupBy: SportingEventsGroup, includeFutures: Boolean, futuresCountOnly: Boolean, futuresGroupBy: SportingEventsGroup` |

```jsonc
// Variables — AFL competition page, upcoming events + futures (flat)
{
  "category":              "AUSTRALIAN_RULES",
  "regionSlug":            "",
  "competitionSlug":       "afl",
  "statuses":              ["OPEN", "LIVE"],
  "excludeCategoryIds":    [],
  "includeLeagues":        false,
  "includeUpcomingEvents": true,
  "upcomingEventsGroupBy": "UNSPECIFIED",
  "includeFutures":        true,
  "futuresGroupBy":        "UNSPECIFIED"
}
```

```jsonc
// Response (truncated)
{
  "data": {
    "league": {
      "id":              "SportingCompetition:ccff2e9a-...",
      "name":            "AFL",
      "url":             "/sports/australian-rules/afl",
      "hasInPlayEvents": false,
      "region":          null
    },
    "upcomingEvents": {
      "events": {
        "nodes": [
          {
            "id":              "SportingEvent:7d569108-...",
            "name":            "St Kilda vs Hawthorn",
            "url":             "/sports/australian-rules/afl/st-kilda-vs-hawthorn/7d569108-...",
            "advertisedStart": "2026-05-28T09:30:00.000Z",
            "eventType":       "MATCH",
            "eventTypeId":     "6bfa0efc-...",
            "bettingStatus":   "OPEN",
            "status":          "OPEN",
            "phase":           null,
            "hasLiveVision":   false,
            "inPlay":          false,
            "sportCategory":   { "id": "23d497e6-...", "name": "Australian Rules", "category": "AUSTRALIAN_RULES", "icon": "sports/australian-rules", "slug": "australian-rules", "url": "/sports/australian-rules", "hasRegions": false, "eventCount": 0 },
            "competition":     { "id": "SportingCompetition:ccff2e9a-...", "name": "AFL", "url": "/sports/australian-rules/afl", "hasInPlayEvents": false, "region": null },
            "teams": [
              { "id": "SportingTeam:070c490b-...", "name": "St Kilda",  "colour": "#C8102E", "locale": "HOME", "scores": [], "icon": { "web": "/images/ladbrokes/sprites/svg-sports-afl-icon.svg#st-kilda-fc" } },
              { "id": "SportingTeam:7fd82a2e-...", "name": "Hawthorn",  "colour": "#4A2E0B", "locale": "AWAY", "scores": [], "icon": { "web": "/images/ladbrokes/sprites/svg-sports-afl-icon.svg#hawthorn-hawks" } }
            ],
            "matchClock":   { "countDown": false, "maxPeriodSeconds": 1200, "paused": false, "periodSeconds": 0 },
            "marketCount":  79,
            "markets": {
              "nodes": [
                {
                  "id":                      "SportingMarket:295023bc-...",
                  "name":                    "Match Betting",
                  "marketTypeId":            "be25c37a-...",
                  "handicap":                null,
                  "isPrimary":               true,
                  "isSuspended":             false,
                  "status":                  "OPEN",
                  "liveBettingAvailable":    true,
                  "allowsCashOut":           false,
                  "sameGameMultiAvailable":  true,
                  "allowOddsBoostExtra":     false,
                  "additionalProductTypeIds": null,
                  "entrantCount":            2,
                  "entrants": {
                    "nodes": [
                      { "id": "SportingEntrant:56c5a938-...", "name": "St Kilda", "handicap": null, /* prices etc. */ }
                    ]
                  }
                }
              ]
            }
          }
        ]
      }
    },
    "futures": { /* shape mirrors upcomingEvents — flat list when futuresGroupBy is UNSPECIFIED */ }
  }
}
```

The `matchClock` block is populated on in-play events: `periodSeconds` increments, `paused` reflects half-time/quarter breaks, `maxPeriodSeconds` is the period length used to render a progress bar.

### `SportingEventScreen`

The single sport event detail screen with optional info-hub widgets.

| | |
|---|---|
| **Hash** | `8ccf7d5f68e47e8c924609b84c1ade3be08a804b56d2847f6440be556c57889f` |
| **Variables** | `id: ID!, includeInfoHub: Boolean!, includeWidgets: Boolean!` |

```jsonc
// Variables
{
  "id":               "SportingEvent:339e26d0-72a8-49bc-a85f-a2d02c0a1a70",
  "includeInfoHub":   true,
  "includeWidgets":   true
}
```

The variable `id` must be the **prefixed** form (`SportingEvent:<uuid>`); the bare UUID returns `{"data":{"event":null}}` rather than an error.

### `SportingInPlayScreen`

The in-play page — filter chips plus events grouped by competition.

| | |
|---|---|
| **Hash** | `331aaac378ee679d982082e3f807a5bff39573f7d6c57ea545a7ffa8e99852df` |
| **Variables** | `excludeCategoryIds: [UUID!]` |

```jsonc
// Variables
{ "excludeCategoryIds": [] }
```

```jsonc
// Response (truncated; ~65 KB live)
{
  "data": {
    "sportingGroupedInPlayEvents": {
      "filters": [
        { "id": "all",                                    "name": "All" },
        { "id": "2d20a25b-6b96-4651-a523-442834136e2d",   "name": "NBA" },
        { "id": "7732fc3b-9dd0-46e8-95e9-f4011a4002df",   "name": "NHL" },
        { "id": "a5618779-2cb3-4c0a-b8cc-ce2517fbc8d4",   "name": "MLB" },
        { "id": "71955b54-62f6-4ac5-abaa-df88cad0aeef",   "name": "Soccer" },
        { "id": "a19fe930-3d0c-4f23-9cd4-12132fcc6b0a",   "name": "American Football" },
        { "id": "e89fbf3f-7ed4-47b4-923e-6febc6691ac9",   "name": "Esports" },
        { "id": "fff64442-44f4-40d2-b830-5fa9b1bdf9e4",   "name": "Motor Sport" },
        { "id": "b92b2d14-10f7-46c7-8655-16eeed36ec4b",   "name": "Table Tennis" }
      ],
      "groups": [
        {
          "id":            "2d20a25b-...",
          "name":          "NBA",
          "category":      "BASKETBALL",
          "icon":          "sports/basketball",
          "slug":          "basketball",
          "url":           "/sports/basketball/usa/nba",
          "hasRegions":    false,
          "eventCount":    1,
          "competitions":  [],
          "events": [
            { "id": "SportingEvent:3fde676d-...", "name": "San Antonio Spurs vs Oklahoma City Thunder", /* ... */ }
          ]
        }
      ]
    }
  }
}
```

Note `filters[0]` is the synthetic `"all"` ID — used by the front-end to clear filter state.

### `SportingIconSets`

SVG sprite definitions and per-team icon references for one or more categories. Large (~1.1 MB for Basketball) — cache aggressively.

| | |
|---|---|
| **Hash** | `13dbe345de9b5926bc80a99cbb1931f40c6a19fb7f889770523930e6ae3ab510` *(gateway also still accepts earlier `830e8f22341d44a46d03aa2a7072e6b89c3b04bc17246a4676f59f7267521b6e`)* |
| **Variables** | `categoryIds: [UUID!]` |

```jsonc
{ "categoryIds": ["3c34d075-dc14-436d-bfc4-9272a49c2b39"] }
```

### `HomeSportsScreen`

Composite sports homepage payload.

| | |
|---|---|
| **Hash** | `50fab92cd64e6c71f6c1f8048e9d95529369add40bc3af425949fa7e4d1bc8fb` |
| **Variables** | `includeMajorEvents: Boolean, includeQuicklinks: Boolean, quicklinksShortTitle: Boolean, platform: QuickLinkPlatform, excludeCategoryIds: [UUID!], includeFeaturedEvents: Boolean, featuredEventsEventCount: Int, featuredEventsPlatform: QuickLinkPlatform, includeUpcomingEvents: Boolean, upcomingEventsCount: Int, upcomingEventsGroupBy: SportingEventsGroup, includeFeaturedComps: Boolean, featuredCompCount: Int, featuredCompStatuses: [SportingMarketStatus!], featuredCompEventCount: Int, includeInPlayEvents: Boolean, inPlayEventCount: Int` |

```jsonc
// Variables
{
  "excludeCategoryIds":       [],
  "includeMajorEvents":       false,
  "includeFeaturedEvents":    true,
  "featuredEventsEventCount": 5,
  "featuredEventsPlatform":   "MOBILE",
  "includeUpcomingEvents":    true,
  "upcomingEventsCount":      15,
  "upcomingEventsGroupBy":    "UNSPECIFIED",
  "includeFeaturedComps":     true,
  "featuredCompCount":        10,
  "featuredCompEventCount":   15,
  "featuredCompStatuses":     ["OPEN", "LIVE"],
  "includeInPlayEvents":      true,
  "inPlayEventCount":         15
}
```

Response shape:

```jsonc
{
  "data": {
    "featuredEvents":       { "nodes": [ /* QuickLink-shaped, each nests an event */ ] },
    "upcomingEvents":       { "nodes": [ /* SportingEvent */ ] },
    "featuredCompetitions": { "nodes": [ /* SportingCompetition with embedded events */ ] },
    "inPlayEvents":         { "nodes": [ /* SportingEvent with phase / scores */ ] }
  }
}
```

### `RacingRaceCardScreenWeb`

Full racecard for one race — runners, tips, markets, video, in-meeting race selector.

| | |
|---|---|
| **Hash (gateway-registered)** | `7085b5bef9cd71304cbd8264c229ab347711e32e341d7eefd03920645eedff81` |
| **Hash (current bundle)** | `d59b563bacb7984ed87e6a843669aa7f02d03e93a0cc98f505f859c6190cbbc7` *(not yet propagated to gateway — returns `PersistedQueryNotFound` at time of writing)* |
| **Variables** | `id: ID!, isLoggedIn: Boolean!, includePlaceExtra: Boolean!` |

```jsonc
// Variables
{
  "id":                "RacingRaceCard:179247bf-da00-41f8-b9c8-7a9da3e45f86",
  "isLoggedIn":        false,
  "includePlaceExtra": true
}
```

```jsonc
// Response (truncated)
{
  "data": {
    "raceCard": {
      "id":              "RacingRaceCard:179247bf-...",
      "distance":        1200,
      "trackCondition":  "Good 4",
      "weatherIcon":     "OVERCAST",
      "name":            "Asset Painting Services Mdn Plate",
      "advertisedStart": "2026-05-25T03:30:00.000Z",
      "fullForm":        "https://ladbrokesform.com.au/form/179247bf-...",
      "number":          1,
      "status":          "OPEN",
      "protestReason":   null,
      "meeting":         { "id": "RacingMeeting:13a288c4-...", "category": "HORSE", "name": "Mornington", "regionId": "8e2a3927-...", "venue": { "name": "Mornington", "country": "AUS" } },
      "videoChannels":   [ { "channelId": "bd93ca0c-...", "type": "CHANNEL", "url": "https://www.ladbrokes.com.au/videos/nep/channel1.m3u8?verify=..." } ],
      "tips":            [
        {
          "id":          "179247bf-...",
          "author":      { "name": "racingandsports" },
          "entrants":    [ { "id": "RacingEntrant:736c3ce6-..." } /* tipped runners */ ],
          "productType": { "productGroupId": "...", "productTypeId": "940b8704-...", "showOdds": true, "noOddsPlaceholder": "TBD", "suspendedPlaceholder": "TBA" },
          "summary":     "VELOCITE BELLE (12) was well backed on debut..."
        }
      ],
      "raceSelector":    [
        { "id": "RacingRace:179247bf-...", "number": 1, "finalFieldMarket": { "id": "RacingMarket:ae198856-...", "status": "OPEN" } }
        /* sibling races for in-meeting nav */
      ]
      /* + nested runners, markets, prices, exotics */
    }
  }
}
```

### `RacingListPopularSameRaceMultis`

Trending SRM combinations across races.

| | |
|---|---|
| **Hash** | `5fcebb946ed6e3bf008bc0ba28527de51110a0f3591d8e0e1f245b25dcab1984` *(gateway also still accepts earlier `be2033d23c0cd26aa2104e29f4d434d025a789c9a4a0a410a35ebdfc2e3246c7`)* |
| **Variables** | `eventIds: [ID!], countryCodes: [RacingCountryCode!], after: String, first: Int, excludedCategories: [RacingExcludedCategoriesInput!]` |

```jsonc
// Variables
{ "first": 9, "excludedCategories": [] }
```

```jsonc
// Response (truncated)
{
  "data": {
    "popularSameRaceMultis": {
      "nodes": [
        {
          "id":           "f148069c19644bd1823b9c652a9d2e27",
          "puntersCount": 5,
          "srmOdds": {
            "odds":             { "formatted": "4.40", "decimal": 4.4, "denominator": 5, "numerator": 17 },
            "minimumOdds":      { "formatted": "4.40", "decimal": 4.4, "denominator": 5, "numerator": 17 },
            "averageOdds":      { "formatted": "4.40", "decimal": 4.4, "denominator": 5, "numerator": 17 },
            "maximumOdds":      { "formatted": "4.40", "decimal": 4.4, "denominator": 5, "numerator": 17 },
            "combinationCount": 1,
            "combinations": [
              {
                "priceKey":   "<entrantId>-<position>:<entrantId>-<position>:...",
                "selections": [
                  { "entrantId": "4fee947c-...", "raceId": "b740aecb-...", "marketId": "dc96e544-...", "position": 1, "entrantNumber": 0 }
                ],
                "odds":       { "numerator": 17, "denominator": 5 }
              }
            ]
          },
          "race": {
            "id":              "RacingRace:b740aecb-...",
            "advertisedStart": "2026-05-25T01:23:00.000Z",
            "name":            "Ckh Painting"
          }
        }
      ]
    }
  }
}
```

### `RacingVideoChannels`

GraphQL wrapper for `/v2/video/video-v2/ListChannels`. Same data, same signed HLS URLs.

| | |
|---|---|
| **Hash** | `160653ed87b09847c05d10f480b18a608a895a4fc958178e007c13cd61c20fcf` |
| **Variables** | none |

```jsonc
{
  "data": {
    "racingListVideoChannels": [
      { "channelId": "bd93ca0c-...", "type": "CHANNEL", "url": "https://www.ladbrokes.com.au/videos/nep/channel1.m3u8?verify=..." },
      { "channelId": "2c184b7b-...", "type": "CHANNEL", "url": "https://www.ladbrokes.com.au/videos/nep/channel2.m3u8?verify=..." }
    ]
  }
}
```

---

## GraphQL operations — full catalogue (127 entries)

Every persisted operation registered in `vendor-graphql-ops-web-D59Og4AP.js`, with its current sha256 hash and full variable signature. **The Verified column** indicates which operations have been confirmed live end-to-end on 2026-05-25 — the rest have valid hashes in the bundle but were not individually exercised. Unverified ones may return `PersistedQueryNotFound` if the gateway hasn't picked up the latest bundle; verified ones definitely work today.

| Operation | Type | sha256 | Variables | Verified |
|---|---|---|---|---|
| `AccountBetTransaction` | `query` | `4bd3172f7b18fe30d03b500233c5492a2826526e20a4eaeed9037e77f90ce8b6` | `transactionId: ID!` |  |
| `AccountGetBetCombinations` | `query` | `88bc8db19cc5b60eefb6bfe5c7c46d101f6abb4e2548dd7bb6834b2302d45ac2` | `id: ID!, groupId: String, first: Int, after: String` |  |
| `AccountGetBetTransaction` | `query` | `6ad301a365bc4c39254bbe0710961f1b32ecb7d93e280bef91405f67a87fc8c1` | `id: ID!, groupId: String, includeCashOutCheck: Boolean, includeEntrantTrackers: Boolean, includeMultisPreview: Boolean, eventId: UUID` |  |
| `AccountListPendingBetTransactions` | `query` | `8758e97324af15f763965338e14c5a6568c1ad6a2fce65290b2282ef865da424` | `groupId: String, first: Int, after: String, orderBy: PendingBetsSortOrder, includeCashOutChecks: Boolean, includeMultisPreview: Boolean, eventId: UUID` |  |
| `AccountListResultedBetTransactions` | `query` | `4d1b0bac0c519919c4a253251deafe6e98b712f8fb4820aef70a77638c3f8a3c` | `first: Int, after: String, betStatuses: [BetStatus!], groupId: String, includeMultisPreview: Boolean` |  |
| `BetStakeLimit` | `query` | `ae61efdedef97b5ea457a61b92a5faee45c8aefe29909dd3fbce214d00866761` | _(none)_ |  |
| `BlackbookEntries` | `query` | `3d37275521ba43f70f5db7d9e4dedf0cb3207b49e82f109c9c0686683e224499` | `categories: [RacingCategory!], orderBy: BlackbookListEntriesOrderBy, view: BlackbookListEntriesView, pageSize: Int, after: String` |  |
| `BlackbookEntriesWithRaces` | `query` | `5f963e3301ca24ff96518d4522f34078489b92ad51db6f8db6b7bd65c2a22c15` | `categories: [RacingCategory!], orderBy: BlackbookListEntriesOrderBy, view: BlackbookListEntriesView, pageSize: Int, after: String` |  |
| `BlackbookRaceEntrantInfo` | `query` | `1de3f28631ad07111fe7944e94a60b18f47a3b79ba9451f0eb1593e2b51e2c39` | `raceId: ID!` |  |
| `CheckPinComplexity` | `query` | `448ca33cebdb6b2de7257a2ea82b2b56d61a95a6da5aea6324f2ad9b442edff9` | `pin: String!, dateOfBirth: String!` |  |
| `ClientAccountCasinoTransactions` | `query` | `b26c66e9d32816201e6958d441baf7c70b3a8ca25b370fb97c96d72328f249fd` | `after: String, first: Int, groupId: String, transactionStartDate: DateTime!, transactionEndDate: DateTime!` |  |
| `ClientAccountSportsbookTransactions` | `query` | `833152158954a4baef18235631ac15ea8b29063611cf37de7f1c953bdee2dfb0` | `after: String, first: Int, groupId: String, transactionStartDate: DateTime!, transactionEndDate: DateTime!` |  |
| `ClientAddressLookup` | `query` | `b5a626d0ac38157fc54fbfecb52340f569b0b6602fd9351c650c5ddb5b12e958` | `partialAddress: String!, pageSize: Int` |  |
| `ClientContactUs` | `query` | `11a20522ae1d307f9ccc49cb7610f5eacd2a389c7078acb63329c27a56a3d17d` | _(none)_ |  |
| `ClientCouponsOffers` | `query` | `ca79a297c49da7b5e787889ecb195f331c939cc502cbf4014dfd9565ced4f4ac` | _(none)_ |  |
| `ClientDetailsStartUp` | `query` | `a3e52fa7c5b82bd493922743c26749ed993773a1ea98e7362bd29b881cfbdeaa` | _(none)_ |  |
| `ClientFindAddress` | `query` | `6aaf0635008db4c2b8937f192f2f9cd53dd6c54bc4f276db28760f5892089afd` | `placeId: String!` |  |
| `ClientGetExternalClientVerification` | `query` | `848dbb586932c86ecf58b71c6260a3944e59654a2b3287903e41f7c810d9d3e8` | _(none)_ |  |
| `ClientNatureAndPurposeQuestions` | `query` | `591713ade4b6b15d817460c43a6c7c8d82163061dd64ba285633b49f0668c937` | _(none)_ |  |
| `ClientPromotions` | `query` | `db06b042446ea3630d2402baacedbe7e96f87520c5773fd60b08b7b58a6e9ca3` | `exclusiveOddsEntrants: Int, exclusiveOddsExpireDateTime: DateTime, includeExpired: Boolean` |  |
| `CreateBetStakeLimit` | `mutation` | `262ade6f0dc4dc8a90329def331b813eabf6c5d418a3644be112275fba74513a` | `input: CreateBetStakeLimitInput!` |  |
| `CreateBlackbookEntry` | `mutation` | `6743272e6a204e1a99f6aef09c20a4be73b407f9169c1abb5cf688b2d18d5d62` | `input: CreateBlackbookEntryInput!` |  |
| `CreateExperienceBooking` | `mutation` | `7315857d66ebfe5edc0ebaf387ce479a6900e53da2280ccc617380b87a008a6b` | `input: CreateExperienceBookingInput!` |  |
| `DeclineExpressionOfInterest` | `mutation` | `6f9d3985297e719e001e6c287a22fc104eb25e21d6ee1b3625203454843cb575` | `input: DeclineExpressionOfInterestInput!` |  |
| `DeleteBetStakeLimit` | `mutation` | `b2b8702df97350ac288c047687eb42b4f3d3f529532ac2537cb36f9b3a7c222d` | _(none)_ |  |
| `DeleteBlackbookEntry` | `mutation` | `40791da65de51762c89974b003803aa6d6fa8db94c6dc5fb104cb473be56cb4c` | `input: DeleteBlackbookEntryInput!` |  |
| `Experience` | `query` | `faabd8ea76a2d1c7a54fc4e2a5fc040fb97542547fe099500f0aeaf5a4eeb640` | `id: ID!` |  |
| `ExperienceEventCards` | `query` | `4c028045cb4781d8ae9e36703bb3254088ec896b3ffe81f8b0d05c7e8d8892ae` | `firstInviteOnlyEvents: Int, afterInviteOnlyEvents: String, firstLimitedAvailabilityEvents: Int, afterLimitedAvailabilityEvents: String, firstEOIEvents: Int, afterEOIEvents: String, firstUpcomingEvents: Int, afterUpcomingEvents: String, firstExclusivePromotions: Int, subdivision: Subdivision` |  |
| `ExternalActivityStatement` | `query` | `7b1a9c35bd0adf3f1838e580972a044552c13d084f4f17f4444c819faca06ec2` | `id: ID!, createTime: Int!, hash: String!` |  |
| `GamingActivities` | `query` | `6546292de306e324082d09a189f5a7539f7be31a24f1fdec4c45914ed28ac8de` | `after: String, createTimeInterval: DateRange, first: Int, gameTypeIds: [String!], result: GamingActivityResultType, supplierIds: [String!]` |  |
| `GamingBonuses` | `query` | `12d2e911492bf7f4732870d1dd6de102244d8236f1b3839dd91795f115c0fba0` | `after: String, first: Int, gameTileVariant: GamingGameTileVariant, types: [GamingBonusType!]` |  |
| `GamingCategories` | `query` | `185997d36540c3eec49079cb20e61aff347c73ff826dd72272542f46523812de` | `after: String, categoryView: GamingCategoryView!, first: Int` |  |
| `GamingChallenge` | `query` | `b767c8274f7b44a2bf9bde79d7d6cdf158a575670cd2433b706c9e64e131669d` | `id: ID!` |  |
| `GamingCollections` | `query` | `c0a643d0f43129b3383501a19fcd11f45aa855bd77aa70e4cc1e7050d04bcde4` | `lobbyId: ID!` |  |
| `GamingFavouriteGames` | `query` | `0899b32d7b24f9bace1cacbdedd3d8270e9d2f2820457b02ee624beec176989f` | `after: String, first: Int, gameTileVariant: GamingGameTileVariant` |  |
| `GamingFeed` | `query` | `ff6e8264cd549390471fdda4cc8dc17e445f385defa26efd07acfffe9af704b3` | `after: String, first: Int, type: GamingFeedPostType` |  |
| `GamingGame` | `query` | `19be1dd8b510a78ec5219a9c95424c124f6fded70b24bd3c87486b2be1000567` | `id: ID!, gameTileVariant: GamingGameTileVariant` |  |
| `GamingGameBySlug` | `query` | `3e0a72dd0b4c76209ee2cb5996c328f20f547d4a0bea5444c67478e0d9b1a15d` | `slug: String!, gameTileVariant: GamingGameTileVariant` |  |
| `GamingGamePromo` | `query` | `e4a694c6823fefeafb6dedd042e21d6c2047b7205813d571565b5be853103444` | `id: ID!` |  |
| `GamingGames` | `query` | `b542069df88eb8d6262b79a5c24ae40c9f26aea45ee29df37c2495ace4f64910` | `after: String, badgeIds: [String!], first: Int, collectionId: ID, categoryId: UUID, gameTileVariant: GamingGameTileVariant, orderBy: GamingGameOrder, searchQuery: String, supplierIds: [ID!]` |  |
| `GamingLobbies` | `query` | `6a265d68372c4c921e1ed780c3d7d59df66858308d6688c6e99426fcfba4cfeb` | _(none)_ |  |
| `GamingNews` | `query` | `00eb224cd104611f2bd0ff2249b40e03114c0f6a88ee0ff1b4b3cb7efed4cba6` | `id: ID!` |  |
| `GamingPageMetadata` | `query` | `8fea4316f22cd4825448145b0d6f446a6d42191f37812bedebd14ec66187a95b` | `urlSegment: String!` |  |
| `GamingPromoBanners` | `query` | `2f7764deb5d3748e21204965406488437387362217bc5fab39b7605993455dc7` | `after: String, first: Int` |  |
| `GamingPromotion` | `query` | `5d27249a4eb692cdf9b8b885443cecc80a98b38132fc7dca5ac7e4b139af0a06` | `id: ID!` |  |
| `GamingQuicklinks` | `query` | `52c44db57e74e47ad6fca29c164bdb1e5adccd3b98c59a377210dfe070d871b8` | `lobbyId: ID!` |  |
| `GamingQuicklinksPublic` | `query` | `21cf4fa578394dfefec15056056a304f555ae7b84397945e3afa283e1a235397` | `lobbyId: ID!` |  |
| `GamingRaffle` | `query` | `4aad6823adefe4483a4c9705f5732efc393c831204ff71f3891d05ef579d88b4` | `id: ID!` |  |
| `GamingRewardsSummary` | `query` | `f13d03cea1bb925b5c9a703b97757da97a223632f2c20f9d77f171159684c260` | _(none)_ |  |
| `GamingSuppliers` | `query` | `dd0e0beef8130c056443613059dadd63d5aecb07a8221c33c74b0435557ff267` | `after: String, first: Int` |  |
| `GenerateBetslip` | `query` | `3d1ce2cfdac519895ce80d4e05ec36496bb84adea98f9a086a685b4343145a92` | `input: BetslipInput!` |  |
| `GroupBetMembershipHistory` | `query` | `47d0cf32b5a16fc8a6561c02669ab72b80338aaae4853c3cd1460429647082ed` | `month: Int!, year: Int!, first: Int, after: String` |  |
| `HomeScreen` | `query` | `77255ac6685a81a7cb0a459db9ad1a16ed2b7db3112cae06910a35883ed97a2e` | `includeQuickLinks: Boolean, excludeCategoryIds: [UUID!], excludeLoggedInOnly: Boolean, quicklinksShortTitle: Boolean` |  |
| `HomeSportsScreen` | `query` | `50fab92cd64e6c71f6c1f8048e9d95529369add40bc3af425949fa7e4d1bc8fb` | `includeMajorEvents: Boolean, includeQuicklinks: Boolean, quicklinksShortTitle: Boolean, platform: QuickLinkPlatform, excludeCategoryIds: [UUID!], includeFeaturedEvents: Boolean, featuredEventsEventCount: Int, featuredEventsPlatform: QuickLinkPlatform, includeUpcomingEvents: Boolean, upcomingEventsCount: Int, upcomingEventsGroupBy: SportingEventsGroup, includeFeaturedComps: Boolean, featuredCompCount: Int, featuredCompStatuses: [SportingMarketStatus!], featuredCompEventCount: Int, includeInPlayEvents: Boolean, inPlayEventCount: Int` | ✅ |
| `HomepageNextToJumpRaces` | `query` | `a5d85b43c98d2f3c6eea60fe4a5791b0e098c02b73e7a4028eaffb84e763375d` | `first: Int, categories: [RacingCategory!]` |  |
| `InitiateOtherVerificationProcess` | `mutation` | `ebef9b29ceedf3deac02edb97a80794ea021538dcd38a35c1a6685af4a0074de` | _(none)_ |  |
| `ListEntrantRunners` | `query` | `bad12ca4a5bd6063687f3c0733f9239f718c6aafaf9348eb49c5db8f6d169a00` | `entrantIds: [ID!]!` |  |
| `ListPendingBets` | `query` | `d353f13d63eb1cb157c9d6ea68eeb521f4bb458611b11041184cb1772c228d8a` | `after: String, first: Int, groupId: String, orderBy: PendingBetsSortOrder!` |  |
| `ListResultedBets` | `query` | `f92528a9de834a974c7da2f09645ae0ba66b100dd8e56889dff23bee8d74d27c` | `after: String, filterBy: [BetStatus!], first: Int, groupId: String` |  |
| `PersonalisedPromotionsList` | `query` | `c1dc53ae4dbe3bb289a10054259780a00e6b8a73de4e2d152a8b4d6fbd5d677b` | `promotionType: PromotionsPromotionType` |  |
| `PromotionsList` | `query` | `f9755c77e60ae8e4f4a094fa650db0b675f2f9988c5dcb6c8ad27cc75ad0792e` | `after: String, first: Int, subdivision: Subdivision, eligibility: [PromotionEligibility!], walletType: WalletType` |  |
| `RaceEntrantInfo` | `query` | `b6c2204fe2d582707603edefad76c17a44304b913003330040c03e6c00855260` | `raceId: ID!` |  |
| `RacingBackupRunners` | `query` | `a482eb4cc70fccf387be6090272864be21ab4901d892fb608a1754b1ab75af24` | `raceId: ID!` |  |
| `RacingBetBuilderMeeting` | `query` | `13529d9e69865cae13881feb2b9372812fc0bcb86f80f271010ce0b2cede6d58` | `meetingId: ID!, shouldFetchProductGroups: Boolean` |  |
| `RacingBetBuilderMeetingList` | `query` | `1e7b7104aac566724271598042dbd41ec0027da01dba98955c17dcd05e31f78c` | `date: Date!, regions: [Region!], categories: [RacingCategory!], includeDayAfter: Boolean` |  |
| `RacingClubActivityFeed` | `query` | `4d8906fe128c2ebdd54a306238ad5220b3dc8a5eaba90e5636cfd2ab3c262326` | `referenceIds: [ID!], authorTypes: [RacingClubAuthorType!], first: Int, after: String, types: [RacingClubPostType!]` |  |
| `RacingClubBallotDetails` | `query` | `d19c73fd076bd962b8ac7f0563e6e30b947965301de04179f38fb93de20806ee` | `ballotId: ID!, isLoggedIn: Boolean!` |  |
| `RacingClubEnterBallot` | `mutation` | `6af4f8124c3173d21440697fc96353961d6106717f449fd4f1185f5af925073c` | `ballot: EnterRacingClubBallotInput!` |  |
| `RacingClubFollow` | `mutation` | `682a474e764ad8e8c4a93dda8dd958c34683b87ad92e879bbe6270533795f3a8` | `follow: RacingClubFollowInput!` |  |
| `RacingClubGetBallotEntry` | `query` | `b8fadeb780b0ebed70fc829968ea5e7eb69b148b74f4bde088da1880f03a8737` | `ballotId: ID!` |  |
| `RacingClubGetFollow` | `query` | `625736ec655d268fb745fcbf52b949ef2f45554dc894f1495dd6226f3c8e0681` | `id: ID!` |  |
| `RacingClubListActiveBallots` | `query` | `85c892ab4596524ad08fcbbfaa0d0ee561af53aa34f6bc42be321e30ef1f0567` | `runnerIds: [ID!], categories: [RacingCategory!], runnerCategoryIds: [ID!], visible: Boolean, timeInterval: DateRange, first: Int, after: String, isLoggedIn: Boolean!` |  |
| `RacingClubListBallots` | `query` | `351bcb859cbe3dd6c0146e954edfbc271f0280847085d6fb4c044b892a500455` | `runnerIds: [ID!], timeInterval: DateRange, types: [RacingClubBallotType!], first: Int, after: String, orderBy: RacingClubBallotOrder, isLoggedIn: Boolean!, status: RacingClubBallotFilterStatus, enteredOnly: Boolean!` |  |
| `RacingClubListFollow` | `query` | `4fcd5b43d5f1b96fcc63ba3cf43a87639d5f4202f7fdb3f4d3ff7430014a4370` | `first: Int, after: String, isLoggedIn: Boolean!` |  |
| `RacingClubListRaces` | `query` | `e8d89d668670c2530a0075a2afc267e1bafc3bf914ad9a672a290fb716d41c34` | `runnerIds: [ID!], first: Int, after: String` |  |
| `RacingClubListRunners` | `query` | `20a43c5362b6e1f12c34a1769fa0ed6a26d423dce9443dd14ee614536b4844bd` | `runnerIds: [ID!], categories: [RacingCategory!], statuses: [String!], first: Int, after: String, isLoggedIn: Boolean!, orderBy: RacingClubListRunnerOrder` |  |
| `RacingClubListSuggestedFollow` | `query` | `e34a9c1a45adb9f1dcbc481a4cfea8d8bea652bb9a0a0d5546a1e631034fb06b` | `first: Int, after: String, isLoggedIn: Boolean!` |  |
| `RacingClubListWinningBallotEntry` | `query` | `33e39801ac024affdd1f02a32f3b9e2385065af9f9ae13af1a19931ccaf3caa8` | `ballotIds: [ID!], runnerIds: [ID!], outcomes: [RacingClubBallotEntryOutcome!], visible: Boolean, endTimeInterval: DateRange, eventTimeInterval: DateRange, orderBy: RacingClubBallotEntryOrder, first: Int, after: String, ballotTypes: [RacingClubBallotType!]` |  |
| `RacingClubRunnerDetails` | `query` | `6c70aac4c9f392836c6f9dbf46c224ec78b9b6ff2d9ddd8b352eaec6d41e883a` | `ballotId: ID, runnerId: ID!, includePosts: Boolean, isLoggedIn: Boolean!` |  |
| `RacingClubRunnerGallery` | `query` | `006d11e7b2e4de22681775e34486bc481ef10bfbbb653de074f9e524b34784ec` | `runnerId: ID!, first: Int, after: String` |  |
| `RacingClubUnfollow` | `mutation` | `775a1e48fe30f93f0587f4c5020673fffccf897a1139be1287cff287ad61d0c4` | `unfollow: RacingClubUnfollowInput!` |  |
| `RacingEntrantInfo` | `query` | `cc13604c5518ed1b779279b6759f39e0ef187a8e83f20a1a65d913c61cb7e9bc` | `raceIds: [ID!]!` |  |
| `RacingExtraMarketsList` | `query` | `9a71cde40898f37b397090e7c73b97eafa225814ec73d864dc1fab748cc1028d` | `after: String, first: Int` |  |
| `RacingExtrasMarket` | `query` | `a49e52022fd8d59145d8be02887746e9161b643120c84698c34ea99520e1f13a` | `id: ID!, orderBy: RacingEntrantOrder` |  |
| `RacingExtrasScreenWeb` | `query` | `dec7453c51253bb2bdc732383fa1995b2d78b9e0cb48335df00c8b4aaeb38d11` | `horse: Boolean!, greyhound: Boolean!, harness: Boolean!, regions: [Region!]` |  |
| `RacingFutureRaceScreenWeb` | `query` | `1a8fa05a3e6887f97d13e40872bb4b9c4e457cb7762ebfe3cd67ffbb847c1ef6` | `raceId: ID!` |  |
| `RacingFuturesScreen` | `query` | `703e804af334feff8b9cf28ca088ba3187b387251b6ae6d3a717bb2141027622` | `categories: [RacingCategory!], regions: [Region!], groupBy: RacingFuturesGroup` |  |
| `RacingGenerateEasyBet` | `query` | `2aa80827756ae90c9c3d859db45e49fd8791c6da545d97197efff29b4e91eb92` | `compoundId: ID, productTypeId: ID!, raceId: ID, stake: Float!, isPercentageBetting: Boolean` |  |
| `RacingHomeMeetingsDesktopScreen` | `query` | `aad6371ccd6b1eff7a44f4e41889bb491f749bda044d51832ee33c1af08dd085` | `date: Date!, categories: [RacingCategory!], regions: [Region!], shouldFetchPools: Boolean` |  |
| `RacingHomeScreenWeb` | `query` | `d2a9a090530bc43c11e6377245757d3c1003d3af852ab412904fed382dfd94df` | `horse: Boolean!, greyhound: Boolean!, harness: Boolean!, date: Date!, regions: [Region!]` |  |
| `RacingHomeScreenWebAuthed` | `query` | `0eb15dd2262f3e2601778711644ffebf87751fcaa41e314edfc26da375ff1018` | `horse: Boolean!, greyhound: Boolean!, harness: Boolean!, date: Date!, regions: [Region!], promotionSubdivision: Subdivision, promotionEligibility: [PromotionEligibility!]` |  |
| `RacingListPools` | `query` | `0b0b2a494b5df0a8f6424d0012227e08e44f6549fe4f497df456d3d751d0527a` | `after: String, first: Int, raceIds: [ID!], compoundIds: [ID!]` |  |
| `RacingListPopularSameRaceMultis` | `query` | `5fcebb946ed6e3bf008bc0ba28527de51110a0f3591d8e0e1f245b25dcab1984` | `eventIds: [ID!], countryCodes: [RacingCountryCode!], after: String, first: Int, excludedCategories: [RacingExcludedCategoriesInput!]` | ✅ |
| `RacingNextToGoFavourites` | `query` | `256c36119c46b3e6ed31dfa0190077c189df37364c8203604e672fb216e2d7d9` | `first: Int, after: String, categories: [RacingCategory!]` |  |
| `RacingProBetEntrants` | `query` | `fe07e3ecb8a8503095a8758a227e47d301cbda3890e40d0579b450d30031d4b4` | `marketId: ID!` |  |
| `RacingQuickBet` | `query` | `a0d0d36a1cb446aa49bf1ed34a6aa59339b978ce2418312a6d49c2c182ae5ab2` | `entrantId: ID!, raceId: ID!, marketId: ID!, meetingId: ID!` |  |
| `RacingRace` | `query` | `75b11f6779b77eedfb0b7a2207c30d6e09613f3726f2014559ed30e25d7fd4e2` | `raceId: ID!, shouldFetchPools: Boolean` |  |
| `RacingRaceAskFormAssistant` | `query` | `068155c3f4524792b09b61baa9a524617a22e95b5db2dd86b542b9cb15116b6e` | `raceId: UUID!, question: String!, promptId: UUID` |  |
| `RacingRaceCardScreenWeb` | `query` | `d59b563bacb7984ed87e6a843669aa7f02d03e93a0cc98f505f859c6190cbbc7` | `id: ID!, isLoggedIn: Boolean!, includePlaceExtra: Boolean!` | ✅ |
| `RacingRaceCardScreenWebAuthed` | `query` | `ce6d185e003924e688171275e8eadd7aec7dfa5111b184c4c29819ba9092661b` | `id: ID!, promotionSubdivision: Subdivision, promotionEligibility: [PromotionEligibility!], excludeClientPromotions: Boolean!, includePlaceExtra: Boolean!` |  |
| `RacingRaceGetFormAssistantMessages` | `query` | `98cec36f712228a00b894a890b17f145999fca53db0e622bfab864042c8ae652` | `raceId: UUID!, isLoggedIn: Boolean!` |  |
| `RacingSideMenuNextToJumpRaces` | `query` | `92ce964ddc5115b7f0c5a076f09183684c2da7aa93d87346d85108f36a451844` | `first: Int, regions: [Region!], categories: [RacingCategory!]` |  |
| `RacingVideoChannels` | `query` | `160653ed87b09847c05d10f480b18a608a895a4fc958178e007c13cd61c20fcf` | _(none)_ | ✅ |
| `RegisterExpressionOfInterest` | `mutation` | `872abd3e514b7c10cc8ba125cbad7c0f833f30c16cbc5948086d3e11298a5357` | `input: RegisterExpressionOfInterestInput!` |  |
| `SkipExternalClientVerification` | `mutation` | `2d530d0b4bee041a11a3e37dc5747b00567add81fb259def0320fb338ed39057` | _(none)_ |  |
| `SportingCategories` | `query` | `e32cd40f8962491f27966f35327ea1f32de8603c2c39f50269232713e18ebd62` | `marketControlExclude: Boolean` | ✅ |
| `SportingCategoryScreen` | `query` | `44a5f5b46e5c378682c3ebdc506cbc254ac76be05b72bd27b8d51636c6205aa2` | `category: SportingCategory!, statuses: [SportingMarketStatus!], excludeCategoryIds: [UUID!], includeRegions: Boolean, includeLeagues: Boolean, includeUpcomingEvents: Boolean, upcomingEventsCount: Int, upcomingEventsGroupBy: SportingEventsGroup, upcomingEventsStatuses: [SportingMarketStatus!], includeFutures: Boolean, futuresCountOnly: Boolean, futuresGroupBy: SportingEventsGroup` | ✅ |
| `SportingCompetitionPopularSameGameMultis` | `query` | `d8355b093b5488a1ede8a1506f2bd43240ba0c07ff597d2b0b1f89c0e983db3f` | `competitionIds: [ID!]!, first: Int, countPerEventCount: [Int!], promotions: Boolean!, promotionSubdivision: Subdivision, promotionEligibility: [PromotionEligibility!]` |  |
| `SportingCompetitionScreen` | `query` | `1a346cbef31e3261c5f3d6e64a29e5acbaa76bdc3f00adb05a2f16dadc81c93e` | `category: SportingCategory!, regionSlug: String, competitionSlug: String!, excludeCategoryIds: [UUID!], statuses: [SportingMarketStatus!], includeLeagues: Boolean, includeUpcomingEvents: Boolean, upcomingEventsCount: Int, upcomingEventsGroupBy: SportingEventsGroup, includeFutures: Boolean, futuresCountOnly: Boolean, futuresGroupBy: SportingEventsGroup` | ✅ |
| `SportingEntrantFormData` | `query` | `1e67cba526e898cd422f970a19b4843618f5ee8b6cd3206c8c07453a94f7488d` | `eventId: ID!` |  |
| `SportingEventEntrantFormData` | `query` | `5edfd23ba0233fcead285ea56cf39e803aa36fc12baa00811d4b93b448c35cac` | `id: ID!` |  |
| `SportingEventPopularSameGameMultis` | `query` | `396a33e940eb678e6648ddf6b67230a121eeea6aad1866e1d633de16b5edba1a` | `eventId: ID!, first: Int, promotions: Boolean!, promotionSubdivision: Subdivision, promotionEligibility: [PromotionEligibility!]` |  |
| `SportingEventScreen` | `query` | `8ccf7d5f68e47e8c924609b84c1ade3be08a804b56d2847f6440be556c57889f` | `id: ID!, includeInfoHub: Boolean!, includeWidgets: Boolean!` | ✅ |
| `SportingEvents` | `query` | `dd633e5290e3d24b6969565c8789f5358a3e08f6d7c7adce91f9b3c721c3973d` | `first: Int, after: String, category: SportingCategory, regionSlug: String, competitionSlug: String, statuses: [SportingMarketStatus!], eventTypes: [SportingEventType!], groupByLeague: Boolean, detailedView: Boolean` |  |
| `SportingIconSets` | `query` | `13dbe345de9b5926bc80a99cbb1931f40c6a19fb7f889770523930e6ae3ab510` | `categoryIds: [UUID!]` | ✅ |
| `SportingInPlayEvents` | `query` | `f9f5f7f9e2d02358953f693998f857a808b692b2a1b65346f996c7af6cb8e4a0` | `includeInPlayFilters: Boolean, includeGroupedInPlayEvents: Boolean, includeInPlayEvents: Boolean, category: SportingCategory, regionSlug: String, competitionSlug: String, excludeCategoryIds: [UUID!]` |  |
| `SportingInPlayScreen` | `query` | `331aaac378ee679d982082e3f807a5bff39573f7d6c57ea545a7ffa8e99852df` | `excludeCategoryIds: [UUID!]` | ✅ |
| `SportingInPlaySideMenu` | `query` | `ee697c440b81e8947374ecad321fa7487f0b9242aba41b794017dedebc45c2b6` | `inPlayEventCount: Int` |  |
| `SportingLandingScreen` | `query` | `e6b3a3c40e1a00a8ca7cf8172d72e7698119b566df8353e41038b080b7966e13` | `includeCategories: Boolean, statuses: [SportingMarketStatus!], includeQuicklinks: Boolean, quicklinksShortTitle: Boolean, platform: QuickLinkPlatform, excludeCategoryIds: [UUID!], includeFeaturedEvents: Boolean, featuredEventsEventCount: Int, featuredEventsType: QuickLinkType, includeUpcomingEvents: Boolean, upcomingEventsCount: Int, upcomingEventsGroupBy: SportingEventsGroup, includeFeaturedComps: Boolean, featuredCompCount: Int, featuredCompStatuses: [SportingMarketStatus!], featuredCompEventCount: Int, includeInPlayEvents: Boolean, inPlayEventCount: Int` |  |
| `SportingLiveBettingFastCode` | `query` | `7b93fbd69dee64bbbe1648013743c243c53797f46465b627ee640b7cec9541a8` | `entrantId: UUID!` |  |
| `SportingPromotedMarkets` | `query` | `4417bc5c40adae77de7244f7ba8f5fb64043c287c8acd3f0cb6396f76bd28cdb` | `excludeCategoryIds: [UUID!]` |  |
| `SportingRegionScreen` | `query` | `e74d008835be9c4c041435297c6515efdf65e836c036b532e5f52edb8af9eb3b` | `category: SportingCategory!, regionSlug: String!, statuses: [SportingMarketStatus!], excludeCategoryIds: [UUID!], includeRegions: Boolean, includeLeagues: Boolean, includeUpcomingEvents: Boolean, upcomingEventsCount: Int, upcomingEventsGroupBy: SportingEventsGroup, includeFutures: Boolean, futuresCountOnly: Boolean, futuresGroupBy: SportingEventsGroup` |  |
| `SportingVideoStreams` | `query` | `788dee337af133bc6c4977a6582428df6dfcfe6c59eb8a57a5d6a72e98192fb9` | `eventIds: [String!]!` |  |
| `TerminalNextToJumpRaces` | `query` | `0ffd4ea1eb38a7e4e13cb7765c8cac9a1b65e170dc2f3d8b0f657e91d459c728` | `first: Int, categories: [RacingCategory!], shouldFetchProductGroups: Boolean` |  |
| `ToolBoxExclusiveOddsRacingEntrants` | `query` | `7c4049932c02e972250e017078428c63938b66eb404cf806874f21b95d4eae85` | `first: Int, after: String, expireDateTime: DateTime, filter: ToolboxExclusiveOddsRacingEntrantFilter` |  |
| `UpdateBetStakeLimit` | `mutation` | `ad9171ebd6a25981f5d3990ab3a1bde3a0fb6f2492acb077272afaec1a18de9b` | `input: UpdateBetStakeLimitInput!` |  |
| `UpdateBlackbookEntry` | `mutation` | `8bf00fe5483f867dc3b5d4f4ae010635e0fc40dc9ac8f33b02e567f9bf24510a` | `input: UpdateBlackbookEntryInput!` |  |

**Counts:** 127 operations total — 113 queries, 14 mutations.

**Grouping (by name prefix):**

| Prefix | Count | Purpose |
|---|---|---|
| `Racing*` | 41 | Race cards, meetings, futures, extras, video, club/loyalty, form-assistant, terminal, pro-tools |
| `Gaming*` | 21 | Casino lobbies / games / promos / activity (out of scope for sportsbook integrators) |
| `Sporting*` | 18 | Categories, regions, competitions, events, markets, in-play, video, SGM trending |
| `Client*` | 10 | KYC / address / promotions / verification |
| `Account*` | 5 | Authenticated bet history / pending / resulted / combinations |
| `Blackbook*` | 3 | Punter blackbook (followed runners/jockeys/trainers) |
| `Create*` | 3 | Mutations (stake limits, blackbook entries, experience bookings) |
| `List*` | 3 | Generic pagination wrappers |
| `Update*` / `Delete*` | 4 | Mutations |
| `Home*` / `Homepage*` | 3 | Homepage payloads (logged in / not, sports tab, racing tab) |
| `Experience*` | 2 | "Ladbrokes Experiences" booking system |
| Misc | 14 | One-offs: `Check*`, `Generate*`, `Group*`, `Initiate*`, `Personalised*`, `Promotions*`, `Race*`, `Register*`, `Skip*`, `Terminal*`, `ToolBox*`, `External*`, `Decline*`, `BetStakeLimit` |

---

## Your own account (group `entain.write`)

**`entain_place_bet`** — one tool, and the only one here needing a personal credential. Captured live 2026-08-27
from real bets on Ladbrokes — a single and a three-leg same game multi, both HTTP 200,
`status: "accepted"`.

```
POST https://api.ladbrokes.com.au/v2/betting/place-bet
{ "stake": 1,
  "bets": [{ "legs": [{ "bet_id", "entrant_name",
                        "odds": { "numerator", "denominator", "decimal" },
                        "product_type_id", "root_category_id",
                        "selections": [{ "position", "market_id", "event_id", "entrant_id" }] }],
             // SGM ONLY — a single carries no `prices` block:
             "prices": { "<event_id>": { "valid": true,
                                         "odds": { "numerator", "denominator" } } } }] }

→ 200
{ "transaction_id", "status": "accepted", "accepted_stake", "message",
  "placed_odds": [{ "product_type_id", "odds": { "decimal", "numerator", "denominator" } }] }
```

`market_id` and `entrant_id` are the **same identifiers** `entain_sport_event_card` and
`entain_sgm_price` use, so the resolver written for pricing serves placing too.

### Where Entain sits against the other two books

It reports **more** about what happened than either, and offers **less** to recover with.

| | Sportsbet | TAB | **Entain** |
|---|---|---|---|
| Success signal | `202` — async | `201` — synchronous | **`200` + `status` in the body** |
| Price binding | none — client asserts | `decoToken` per leg | none — client asserts |
| Idempotency | none | `transactionId` you send | **none — `transaction_id` is returned** |
| Stake actually taken | not stated | `stake` echoed | **`accepted_stake`** |
| Price actually struck | `betPotentialWin` | `expectedReturn` | **`placed_odds`** |

1. **HTTP 200 is not the verdict — `status` is.** Anything other than `"accepted"` is a bet
   that did not go on, whatever the code said.
2. **Check `accepted_stake` against what you sent.** Entain states the stake it actually
   took, and a book may take less than asked; on a limited account that is normal, not an
   error. Both verified bets matched, but assuming they always will means eventually
   reporting a bet larger than the one that exists.
3. **Never retry.** `transaction_id` is *returned*, not sent — a receipt, not an
   idempotency key. Unlike TAB there is no way to ask whether a timed-out placement
   landed, so treat it like Sportsbet's and read the account instead.

### Authentication

Entain issues an OIDC token set at login into **plain, non-HttpOnly cookies**:
`web-frontend:token:accessToken`, `…:refreshToken`, `…:expiresAt`, `…:scope`. Verified
live: scope is `["openid","offline_access"]` — which is why a refresh token exists — and
the access token is a JWT with a **one-hour** life whose expiry is published in
`expiresAt` as plain milliseconds.

Because the refresh token sits in an ordinary readable cookie, Entain is the **easiest of
the three books to connect**: the existing cookie-reading `connect` machinery takes it
as-is. Sportsbet's location was never established; TAB's lives in localStorage.

> **The token endpoint is on a separate auth host — config-derived, not yet round-tripped.**
> Every guess against the `api.ladbrokes.com.au` data host returned go-micro's
> "none available", because the auth server is elsewhere. Derived 2026-08-27 from the live
> site's `window.__config`: `auth.url = https://authentication.neds.com/auth`, a **public
> client** `web-frontend`, `defaultClient: hydra`, and `activeTokenRefreshThreshold: 0.75`
> (a refresh-token flow). The app bundle joins that base with a `/token` suffix and posts
> `grant_type`/`refresh_token`/`client_id`, so the endpoint is
> `https://authentication.neds.com/auth/token`, now set in the spec.
>
> What is **still unproven**: the auth host is behind **Kasada** (`auth.kasada: true`),
> which drops both server-side curl (empty body) and scripted browser fetch
> (`Failed to fetch`, no CORS + no `x-kpsdk` header), so a bogus-token probe could not be
> executed to confirm the exact status/shape. An unattended refresh will likely need a
> Kasada token attached, exactly as the web client does. Host + base + suffix + public
> client + refresh grant are config-confirmed; the precise path and the Kasada requirement
> are the residual unknowns — confirm with one real refresh before relying on the tier.

## Endpoint quick reference

| # | Group | Method | Path | Verified |
|---|---|---|---|---|
| 1 | Domain | GET | `/v2/domain-featured/domain-featured-v2/ListQuickLinks?filter=<json>` | ✅ |
| 2 | Domain | GET | `/v2/domain-featured/DomainFeatured/featured-slider-events` | ✅ |
| 3 | Racing | GET | `/v2/racing/meeting?date=&timezone=` | ✅ |
| 4 | Racing | GET | `/v2/racing/next-races-category-group?count=&categories=<json[]>` | ✅ |
| 5 | Racing | GET | `/v2/racing/search` | ✅ |
| 6 | Racing | GET | `/rest/v1/racing/?method=future-markets&exclude=<json>` | ✅ |
| 7 | Sport | GET | `/v2/sport/event-card?id=<uuid>` | ✅ |
| 8 | Sport | GET | `/v2/sport/event-request?category_ids=<json[]>` | ✅ |
| 9 | Event | GET | `/v2/event/MarketRules` | ✅ |
| 10 | Event | GET | `/v2/event/MarketTypeGroupsByCategoryID?category_id=<uuid>` | ✅ |
| 11 | Event | GET | `/v2/event/MarketTypeGroupMapsByCategoryID?category_id=<uuid>` | ✅ |
| 12 | SEO | GET | `/v2/metadata/GetByURL?url=<path>` | ✅ |
| 13 | Video | GET | `/v2/video/video-v2/ListChannels` | ✅ |
| 14 | Insights | POST | `/insights/event` | ⚠️ POST-only, 400 on empty body |
| 15 | Insights | POST | `/insights/error` | ❓ POST inferred |
| 16 | Insights | POST | `/insights/sync` | ❓ POST inferred |
| 17 | CMS | GET | `https://www.ladbrokes.com.au/cdn/contentful/api/spaces/5pu2kqpl2a5n/environments/master/entries?content_type=...` | ✅ |
| 18 | Form | GET | `https://www.ladbrokes.com.au/cdn/ladbrokes/form/<race_id>` | ✅ (HTML, not JSON) |
| 19 | Video | GET | `https://www.ladbrokes.com.au/videos/nep/channel{N}.m3u8?verify=...` | ✅ (HLS) |
| 20 | GraphQL | GET/POST | `/gql/router?operationName=&variables=&extensions=` | ✅ (10 of 127 ops live-verified end-to-end; remaining 117 hashes pulled from JS bundle) |

---

## Internal RPC names (not directly callable)

These names appear in the JS bundle but resolve to internal RPC methods that are not routed through the public gateway today — calling them directly returns 500 (`rpc: can't find method ...`). They are reachable only via the GraphQL gateway:

```
v2/BatchGetCompetitionCategoryMappings
v2/BatchGetCompetitions
v2/BatchGetEntrants
v2/BatchGetMarkets
v2/BatchGetMeetings
v2/BatchGetRaces
v2/BatchGetSGMPrices
v2/BatchGetVenues
v2/GetMarket
v2/ListPriceKineticsStreams
v2/list-blocked-markets
v2/list-conditions
v2/list-entrant-yard-comments
v2/list-entrants
v2/list-markets
v2/list-prices
v2/list-races
```

Authenticated / wallet / KYC RPCs (require session cookie):

```
v2/AddressLookup, v2/GetAddress, v2/UpdateAddress
v2/CreateEmailVerification, v2/CreateSMSVerification, v2/SendIDVerificationSMS
v2/ApplyIDVLeverageMatch, v2/CheckIDVLeverageEligibility, v2/ConfirmKYCRefresh, v2/UpdateKYCRefresh
v2/CreateAMFSubmission
v2/CheckCreditCard3DSecureRequired
v2/ListCreditCards, v2/ActivateMerchantCard, v2/GetMerchantCardAccount, v2/RequestMerchantCard,
  v2/ListMerchantCardAccountTransactions, v2/CreateMerchantCardDeposit, v2/CreateMerchantCardWithdrawal
v2/CreatePayID, v2/GetPayID
v2/ListWithdrawalMethods
v2/GetClientReferrerUnlockState, v2/GetCurrentClientReferralCode,
  v2/LookupClientReferralCode, v2/UpsertClientReferralCode
v2/GetContactDetailsAvailability, v2/GetExternalClientVerification
v2/GetPreferences, v2/UpdatePreferences
v2/UpdateClientPin, v2/UpdateEmail, v2/UpdatePhone
```

Trading / admin (internal-only):

```
v2/batch-upsert-blocked-markets
v2/create-blocked-market, v2/update-blocked-market
v2/create-condition, v2/update-condition
v2/create-elite-portal-token
v2/create-everest-promo-token
v2/create-owners-incentive-scheme-entry
```

---

*Verified 2026-05-25 from an anonymous client against `api.ladbrokes.com.au` (Cloudflare-fronted Entain Neds Platform). Operation hashes and variable signatures are extracted from `vendor-graphql-ops-web-D59Og4AP.js`; the gateway-registered hash set may differ from the bundle on any given day (see [hash drift](#hash-drift--critical-caveat)).*

## Tool reference

Every tool this provider registers. Entain is mostly a GraphQL surface, so several
of these are dispatchers that take an operation name — see the sections above for
how the catalogue resources work.


### `entain.cdn`

| Tool | What it does |
|---|---|
| `entain_cms_entries` | Contentful CMS entries (promotions, major-event nav) via the www CDN proxy. |

### `entain.graphql`

| Tool | What it does |
|---|---|
| `entain_graphql_call` | Call any of Entain's 127 persisted GraphQL operations against
api.ladbrokes.com.au/gql/router by name + variables. Hashes are managed
server-side;… |

### `entain.rest`

| Tool | What it does |
|---|---|
| `entain_event_market_rules` | Settlement rules for every named market, indexed by rule id. |
| `entain_event_market_type_group_maps` | Join table between market types and market-type groups (dedup by pair). |
| `entain_event_market_type_groups` | Market-tab group definitions for a sport category (lower priority renders first). |
| `entain_featured_slider` | Featured slider events (homepage hero carousel). |
| `entain_metadata_by_url` | SEO metadata (page title) for a given URL path. |
| `entain_quicklinks_list` | Navigation quick-links (racing/sports nav tiles). |
| `entain_racing_future_markets` | Legacy v1 racing RPC selector (future-markets races feed). |
| `entain_racing_meeting` | All race meetings + races for one date (normalised UUID-keyed tables). |
| `entain_racing_next_races` | Next races about to jump, grouped per racing category. |
| `entain_racing_racecard` | Full priced racecard for one race — entrants, fixed-odds fluctuations, form. |
| `entain_racing_search` | Racing search facets (barrier/country/jockey/trainer buckets); optional full-text. |
| `entain_sgm_price` | **Prices a same game multi you choose** — correlation-adjusted, several events per call. |
| `entain_place_bet` | **Places a real bet** on your own Ladbrokes/Neds account. Irreversible; needs `ENTAIN_REFRESH_TOKEN`. |
| `entain_sport_event_card` | Complete event card — every market, selection and price for one sport event. |
| `entain_sport_event_request` | Bulk events + markets + prices for one or more sport categories. |
| `entain_video_channels` | Racing live-video channels (HLS .m3u8 URLs; verify token expires within minutes). |
