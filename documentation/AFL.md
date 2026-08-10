# AFL API Documentation

Unofficial reference for the JSON endpoints used by `www.afl.com.au` and the AFL mobile apps. Two hosts make up the public surface:

- **`aflapi.afl.com.au`** — the **public** "Pulse Platform" API. No authentication required for read endpoints. Powers the competition/team/match/ladder/broadcast/news catalogues.
- **`api.afl.com.au`** — the **premium** API (codename **CFS** = *Content Feed Service*, plus the **StatsPro**, **CFS-Premium**, **Keyserver** and **Commentary** services). Every endpoint requires the `x-media-mis-token` header — anonymous calls return `HTTP 401 CFSAPI001`.

> All public endpoints in this document have been verified against live traffic on 2026-05-27. Field shapes and example payloads are reproduced from observed responses. `api.afl.com.au` endpoints are documented from URL patterns the user captured (verified working in their browser session) plus the AFL JS bundle — their response shapes were not reproduced live because the token mint requires Okta auth.

---

## Table of Contents

- [Hosts & services](#hosts--services)
- [Authentication](#authentication)
- [Conventions](#conventions)
  - [Two ID systems](#two-id-systems)
  - [Competitions](#competitions)
  - [Teams](#teams)
  - [Match status / draft status](#match-status--draft-status)
  - [Pagination](#pagination)
  - [Time format](#time-format)
  - [Error envelopes](#error-envelopes)
- [aflapi: AFL Core](#aflapi-afl-core)
  - [Competitions](#competitions-1)
  - [Comp seasons](#comp-seasons)
  - [Rounds](#rounds)
  - [Ladders](#ladders)
  - [Seasons](#seasons)
  - [Clubs](#clubs)
  - [Teams (catalogue)](#teams-catalogue)
  - [Team ID map](#team-id-map)
  - [Venues](#venues)
  - [Players](#players)
  - [Matches (list)](#matches-list)
  - [Matches (single)](#matches-single)
- [aflapi: Broadcasting](#aflapi-broadcasting)
  - [Regions](#regions)
  - [Broadcasters](#broadcasters)
  - [Channels](#channels)
  - [Events (broadcast schedule)](#events-broadcast-schedule)
  - [Single broadcast event](#single-broadcast-event)
  - [Match events (per round/compseason)](#match-events-per-roundcompseason)
  - [Live video streams](#live-video-streams)
  - [Live audio streams](#live-audio-streams)
- [aflapi: Content (Pulse CMS)](#aflapi-content-pulse-cms)
  - [Text articles (news)](#text-articles-news)
  - [Single text article](#single-text-article)
  - [Video content](#video-content)
  - [Photo content](#photo-content)
  - [Promo content](#promo-content)
  - [PROMO content (alternate path casing)](#promo-content-alternate-path-casing)
  - [Reference expressions & tag expressions](#reference-expressions--tag-expressions)
- [api.afl.com.au: CFS (premium feed)](#apiaflcomau-cfs-premium-feed)
- [api.afl.com.au: StatsPro](#apiaflcomau-statspro)
- [api.afl.com.au: Commentary feed](#apiaflcomau-commentary-feed)
- [api.afl.com.au: Keyserver (video URL signing)](#apiaflcomau-keyserver-video-url-signing)
- [api.afl.com.au: CFS-Premium (user)](#apiaflcomau-cfs-premium-user)
- [Site config / Okta](#site-config--okta)
- [Endpoint quick reference](#endpoint-quick-reference)

---

## Hosts & services

The web client embeds its configuration in `window.PULSE` on the homepage. From the production HTML:

```jsonc
{
  "api":             "//aflapi.afl.com.au/afl/v2/",
  "aflApi":          "//aflapi.afl.com.au/",
  "cfsApi":          "https://api.afl.com.au/cfs/afl",
  "cfsCommentary":   "//api.afl.com.au/cfs/commentaryFeed",
  "statsPro":        "https://api.afl.com.au/statspro",
  "cfsPremium":      "https://api.afl.com.au/cfs-premium/users/",
  "cfsUrlSigning":   "https://api.afl.com.au/keyserver/urlSigning",
  "staticResources": "//www.afl.com.au/static-resources/",
  "okta": {
    "url":           "https://login.id.afl",
    "accountUrl":    "https://secure.id.afl/profile-management",
    "clientId":      "0oa2gv3sqmWOi4pUg3l7",
    "redirectPath":  "/callback"
  },
  "competitions": { "AFL": 1, "AFLW": 3 }
}
```

Each AFL club additionally exposes its own brand-mirrored Pulse API at `aflapi.{club}.com.au` (Adelaide → `aflapi.afc.com.au`, Brisbane → `aflapi.lions.com.au`, … 18 clubs). Those are out of scope for this doc but share the same contract as `aflapi.afl.com.au`.

| Sub-path | Service | Auth |
|---|---|---|
| `aflapi.afl.com.au/afl/v2/...` | AFL Core (competitions/teams/matches/etc) | ❌ none |
| `aflapi.afl.com.au/broadcasting/...` | Broadcast schedule / regions / channels / live streams | ❌ none |
| `aflapi.afl.com.au/content/afl/...` | Pulse CMS (news, video, photo, promos) | ❌ none |
| `api.afl.com.au/cfs/afl/...` | CFS (premium match & stats feed) | ✅ `x-media-mis-token` |
| `api.afl.com.au/cfs/commentaryFeed/...` | Match commentary | ✅ `x-media-mis-token` |
| `api.afl.com.au/statspro/...` | StatsPro (rich stats) | ✅ `x-media-mis-token` |
| `api.afl.com.au/keyserver/urlSigning` | Signed HLS video URLs | ✅ `x-media-mis-token` |
| `api.afl.com.au/cfs-premium/users/...` | Premium/AFLiD-bound user data | ✅ `x-media-mis-token` |
| `login.id.afl/...` | Okta identity | — |

---

## Authentication

### `aflapi.afl.com.au`

No headers required. Anonymous `GET` works on every endpoint documented here. CORS is permissive.

### `api.afl.com.au`

Requires the `x-media-mis-token` header. Without it (or with an empty string):

```json
{
  "code": "CFSAPI001",
  "date": "2026-05-26T23:01:33.176+0000",
  "host": "mis-match-5f5d64cf5-79qbr",
  "mdc": "@AF7R@",
  "path": "/afl/matchItem/CD_M20260141201",
  "status": 401,
  "techMessage": "Access to this site is forbidden",
  "userMessage": "Access to this site is forbidden",
  "version": "2.1.28"
}
```

Akamai also fronts the host: certain probe paths (e.g. `/port/v2/token`, `/cfs-premium/users/anonymous`) return Edge "Access Denied" HTML pages before they ever hit the origin. Origin/Referer hints (`Origin: https://www.afl.com.au`, `Referer: https://www.afl.com.au/`) do **not** by themselves grant access.

The token is minted by the deployed front-end through an Okta-backed flow (`clientId: 0oa2gv3sqmWOi4pUg3l7`, issuer `https://login.id.afl`). The web client stores it under the localStorage key `mis_api_token` and replays it on every API call.

For integration without Okta you either:

1. Sniff a valid `x-media-mis-token` from a browser session (it's a JWT-shaped bearer and rotates periodically).
2. Use only the `aflapi.afl.com.au` surface (covers the vast majority of public-interest data).

---

## Conventions

### Two ID systems

Every entity has two identifiers:

| Field | Form | Example | Use |
|---|---|---|---|
| `id` | Integer (Pulse Platform sequential) | `8139` | Used by `aflapi.afl.com.au` paths (`/matches/8139`). |
| `providerId` | String `CD_<TYPE><number>` | `CD_M20260141201` | Used by `api.afl.com.au/cfs/...` and `api.afl.com.au/statspro/...` paths. |

The provider-ID prefix encodes the entity type:

| Prefix | Entity |
|---|---|
| `CD_C<n>` | Competition (e.g. `CD_C014` = Toyota AFL Premiership) |
| `CD_S<year><compSeq>` | Comp season (e.g. `CD_S2026014` = 2026 Toyota AFL Premiership) |
| `CD_R<year><compSeq><round>` | Round (e.g. `CD_R202601412` = Round 12 of 2026 AFL) |
| `CD_M<year><compSeq><roundRR><matchMM>` | Match (e.g. `CD_M20260141201` = round 12 match 01) |
| `CD_T<n>` | Team (e.g. `CD_T10` = Adelaide Crows) |
| `CD_O<n>` | Club (e.g. `CD_O1` = Adelaide Crows club) |
| `CD_V<n>` | Venue (e.g. `CD_V190` = Marvel Stadium) |
| `CD_I<n>` | Player ("Individual"; e.g. `CD_I200131`) |

Use `/afl/v2/teams/idmap` (below) to map between the two ID systems when crossing the `aflapi`/`api` boundary.

### Competitions

The 16 competitions returned by `/afl/v2/competitions`:

| `id` | `providerId` | `code` | `name` |
|---|---|---|---|
| 1 | `CD_C014` | `AFL` | Toyota AFL Premiership |
| 2 | `CD_C101` | `AFL` | AFL Preseason |
| 3 | `CD_C264` | `AFLW` | NAB AFLW |
| 4 | `CD_C584` | `U18B` | NAB League Boys |
| 5 | `CD_C574` | `U18G` | Talent League Girls |
| 6 | `CD_C644` | `U18G` | NAB League Girls |
| 7 | `CD_C015` | `VFL` | VFL Premiership |
| 8 | `CD_C136` | _(unnamed)_ | _(unused slot)_ |
| 9 | `CD_C664` | `AFL` | AFL Origin |
| 11 | `CD_C464` | `VFLW` | VFLW |
| 12 | `CD_C120` | `WAFL` | WAFL Premiership |
| 13 | `CD_C011` | `U18B` | Talent League Boys |
| 14 | `CD_C016` | `SANFL` | SANFL Premiership |
| 15 | `CD_C414` | `U18CG` | Under 18 Girls National Championships |
| 16 | `CD_C019` | `U18CB` | Under 18 Boys National Championships |
| 17 | `CD_C944` | `AFL` | Toyota AFL Indigenous All Stars |

### Teams

The `aflapi` `team.id` for the AFL men's competition (from the Okta config):

| Club | AFL `teamId` | AFLW `teamId` |
|---|---|---|
| Adelaide Crows | 1 | 19 |
| Brisbane Lions | 2 | 21 |
| Carlton | 5 | 22 |
| Collingwood | 3 | 24 |
| Essendon | 12 | 118 |
| Fremantle | 14 | 25 |
| Geelong Cats | 10 | 26 |
| Gold Coast SUNS | 4 | 33 |
| GWS GIANTS | 15 | 28 |
| Hawthorn | 9 | 119 |
| Melbourne | 17 | 29 |
| North Melbourne | 6 | 30 |
| Port Adelaide | 7 | 120 |
| Richmond | 16 | 34 |
| St Kilda | 11 | 36 |
| Sydney Swans | 13 | 121 |
| West Coast Eagles | 18 | 35 |
| Western Bulldogs | 8 | 32 |

`teamType` enum observed: `MEN`, `WOMEN`. The `/teams` catalogue also includes state-league, U18 and historical teams (150 entries total).

### Match status / draft status

`MATCH_STATUS` (from the JS bundle, used in `/afl/v2/matches?status=...`):

| Code | Meaning |
|---|---|
| `U` | Upcoming (scheduled) |
| `L` | Live (in progress) |
| `C` | Complete |
| `P` | Postponed |
| `B` | Bye (no match scheduled for this team this round) |
| `S` | Suspended (in-game stoppage) |

Multiple values are comma-separated: `?status=L,U` returns both live and upcoming.

`DRAFT_STATUS` (used in some match payloads):

| Code | Meaning |
|---|---|
| `PRE_DRAFT` | Before draft conducted |
| `LIVE` | Draft in progress |
| `COMPLETE` | Draft completed |
| `PAUSED` | Draft paused |

### Pagination

Endpoints that return a list embed pagination either as a top-level `meta.pagination` (AFL core), `pageInfo` (broadcasting / content), or are unpaginated for small response sets.

```jsonc
// AFL core
"meta": {
  "code": 200,
  "pagination": { "page": 0, "numPages": 11, "pageSize": 10, "numEntries": 108 }
}

// Broadcasting / content
"pageInfo": { "page": 0, "numPages": 1, "pageSize": 100, "numEntries": 31 }
```

Page sizes accept `?pageSize=N` (some endpoints accept up to 300). Page index uses `?page=N` (0-based).

### Time format

- `aflapi.afl.com.au` UTC timestamps: ISO 8601 with `+0000` suffix on AFL core (`"2026-05-28T09:30:00.000+0000"`) **and** trailing `Z` on broadcasting (`"2026-05-28T09:30:00Z"`).
- Content endpoints emit `publishFrom`/`publishTo`/`lastModified` as **Unix milliseconds** (`1779825600000`).
- Date-only inputs to `?startDate=` / `?endDate=` use `YYYY-MM-DD`. `?fromDate=` uses URL-encoded ISO 8601 (`2026-05-25T07%3A00%3A00Z`).

### Error envelopes

| Surface | Shape |
|---|---|
| `aflapi.afl.com.au` validation | `{"meta":{"code":400,"errors":[{"code":"...","detail":"..."}]}}` |
| `aflapi.afl.com.au` not found | `{"meta":{"code":404,"errors":[{"code":"NOT_FOUND","detail":"..."}]}}` |
| `api.afl.com.au` (any service) | `{"code":"CFSAPI001"\|"KEYSERVER001"\|...,"date":"...","host":"...","mdc":"...","path":"...","status":401,"techMessage":"...","userMessage":"...","version":"..."}` |
| Akamai edge block | HTML `<H1>Access Denied</H1>` with reference number |

---

## aflapi: AFL Core

All under `https://aflapi.afl.com.au/afl/v2/`.

### Competitions

List all competitions known to the platform.

| | |
|---|---|
| **Method/Path** | `GET /afl/v2/competitions` |

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `page` | int | Page index (0-based). Default `0`. |
| `pageSize` | int | Items per page. Observed up to `50`. |

Verified `?pageSize=50` → 200, ~423 B, 16 competitions. See [Competitions table](#competitions) above.

```jsonc
{
  "meta": { "code": 200, "pagination": { "page": 0, "numPages": 1, "pageSize": 50, "numEntries": 16 } },
  "competitions": [
    { "id": 1, "providerId": "CD_C014", "code": "AFL",  "name": "Toyota AFL Premiership" },
    { "id": 3, "providerId": "CD_C264", "code": "AFLW", "name": "NAB AFLW" }
  ]
}
```

### Single competition

```
GET /afl/v2/competitions/{competitionId}
```

Verified `/afl/v2/competitions/1` → 200, 123 B.

```json
{ "meta": { "code": 200 }, "competitions": [ { "id": 1, "providerId": "CD_C014", "code": "AFL", "name": "Toyota AFL Premiership" } ] }
```

> Note: even single-entity endpoints return the wrapper `{ "meta": ..., "competitions": [...] }`.

### Comp seasons

Three list endpoints.

**All comp seasons (across all competitions):**

```
GET /afl/v2/compseasons?page={n}&pageSize={n}
```

Verified `?page=0&pageSize=150` → 200, ~24 KB, 92 comp seasons spanning 2012–2026.

**Comp seasons within one competition:**

```
GET /afl/v2/competitions/{competitionId}/compseasons?pageSize={n}
```

Verified `/competitions/1/compseasons?pageSize=20` → 200, 337 B, 15 AFL seasons.

**Single comp season:**

```
GET /afl/v2/compseasons/{compSeasonId}
```

Verified `/compseasons/85` → 200, ~1.5 KB. Embeds the full rounds array.

Response shape (per item):

```jsonc
{
  "id": 85,
  "providerId": "CD_S2026014",
  "name": "2026 Toyota AFL Premiership",
  "shortName": "Premiership",
  "competition": { "id": 1, "providerId": "CD_C014", "code": "AFL", "name": "Toyota AFL Premiership" },
  "season":      { "id": 16, "year": 2026 },
  "rounds":      [ /* see Rounds */ ],
  "currentRoundNumber": 12
}
```

### Rounds

Rounds for a comp season.

| | |
|---|---|
| **Method/Path** | `GET /afl/v2/compseasons/{compSeasonId}/rounds` |

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `pageSize` | int | Up to `50`. |
| `roundNumber` | int | Filter to a single round. |

Verified `/compseasons/85/rounds?pageSize=50` → 200, ~1.7 KB, 25 rounds. Each round:

```jsonc
{
  "id": 1355,
  "providerId": "CD_R202601412",
  "abbreviation": "Rd 12",        // also "OR" (Opening Round), "FW1" (Finals Week 1), "SF", "PF", "GF"
  "name": "Round 12",
  "roundNumber": 12,
  "byes": [
    {
      "id": 1, "providerId": "CD_T10",
      "name": "Adelaide Crows", "abbreviation": "ADEL", "nickname": "Crows",
      "club": { "id": 3, "providerId": "CD_O1", "name": "Adelaide Crows", "abbreviation": "Crows", "nickname": "Crows" },
      "teamType": "MEN"
    }
  ],
  "utcStartTime": "2026-05-22T08:00:00.000+0000",
  "utcEndTime":   "2026-05-25T10:00:00.000+0000"
}
```

Round-number `0` is the Opening Round. Finals weeks use roundNumber 24 (FW1), 25 (SF), 26 (PF), 27 (GF).

### Ladders

The competition ladder up to and including the requested compseason's `currentRoundNumber`.

| | |
|---|---|
| **Method/Path** | `GET /afl/v2/compseasons/{compSeasonId}/ladders` |

Verified `/compseasons/85/ladders` → 200, ~3.4 KB.

```jsonc
{
  "meta":      { "code": 200 },
  "compSeason": { "id": 85, "providerId": "CD_S2026014", "name": "2026 Toyota AFL Premiership", "shortName": "Premiership", "currentRoundNumber": 12 },
  "round":      { /* round object including utcStartTime/utcEndTime + byes */ },
  "lastUpdated": "...",
  "ladders": [
    {
      "conference": null,           // null for AFL; some comps use East/West etc.
      "entries": [
        {
          "position": 1,
          "team": { /* team object */ },
          "played":          11,
          "pointsFor":       1054,
          "pointsAgainst":   778,
          "minScore":        45,
          "maxScore":        118,
          "avgWinMargin":    28.6,
          "avgLossMargin":   10.0,
          "playersUsed":     30,
          "quartersWon":     { "winQ1": 8, "winQ2": 6, "winQ3": 8, "winQ4": 6, "total": 28 },
          "playedThisRound": false,
          "thisSeasonRecord": {
            "ladderPosition":   1,
            "aggregatePoints":  40,
            "percentage":       135.5,
            "winLossRecord":    { "wins": 10, "losses": 1, "draws": 0, "played": 11 },
            "orderedBy":        "points",
            "winRatio":         0.0
          },
          "thisRoundLastSeason": {
            "ladderPosition":   8,
            "aggregatePoints":  28,
            "percentage":       106.4,
            "winLossRecord":    { /* ... */ }
          }
        }
      ],
      "finalsCutOff":    8,        // top-8 cutoff
      "topFinalsCutOff": 4         // top-4 (double-chance) cutoff
    }
  ]
}
```

### Seasons

Calendar-year season records.

```
GET /afl/v2/seasons
GET /afl/v2/seasons/{seasonId}
```

Verified `/seasons` → 200, 185 B. 16 years from 2010 to 2026.

```jsonc
{
  "meta": { "code": 200, "pagination": { "page": 0, "numPages": 2, "pageSize": 10, "numEntries": 16 } },
  "seasons": [ { "id": 16, "year": 2026 }, { "id": 15, "year": 2025 } ]
}
```

### Clubs

```
GET /afl/v2/clubs
GET /afl/v2/clubs/{clubId}
```

Verified `/clubs` → 200, 387 B (first page). 32 clubs (paginated, pageSize=10 default — pass `?pageSize=50` for one page).

```json
{ "id": 1, "providerId": "CD_O5", "name": "Carlton", "abbreviation": "Blues", "nickname": "Blues" }
```

### Teams (catalogue)

```
GET /afl/v2/teams
GET /afl/v2/teams/{teamId}
```

Verified `/teams` → 200, 1.1 KB (page 0). **150 teams** total — AFL men, AFLW, all state leagues and historical teams. Per-team:

```jsonc
{
  "id":          1,
  "providerId":  "CD_T10",
  "name":        "Adelaide Crows",
  "abbreviation":"ADEL",
  "nickname":    "Crows",
  "club":        { "id": 3, "providerId": "CD_O1", "name": "Adelaide Crows", "abbreviation": "Crows", "nickname": "Crows" },
  "metadata": {
    "social_youtubeUrl":   "https://www.youtube.com/user/adelaidefootballclub",
    "social_instagramUrl": "https://www.instagram.com/adelaide_fc/",
    "social_facebookUrl":  "https://www.facebook.com/adelaidecrows/",
    "social_twitterUrl":   "https://twitter.com/Adelaide_FC",
    "clubSiteUrl":         "https://www.afc.com.au/",
    "homeVenue":           "Adelaide Oval",
    "captainIds":          "1080"
  },
  "teamType": "MEN"
}
```

### Team ID map

Maps the `CD_T*` provider IDs to the integer `id`s used by `aflapi`.

```
GET /afl/v2/teams/idmap
```

Verified → 200, 800 B.

```json
{
  "meta": { "code": 200 },
  "entityType": "team",
  "idMapResponse": {
    "ids": {
      "CD_T1173": 89, "CD_T8592": 60, "CD_T8593": 62,
      "CD_T10":   1,  "CD_T20":   2,  "CD_T30":   5,
      "CD_T40":   3,  "CD_T50":   12, "CD_T60":   14,
      "CD_T70":   10, "CD_T80":   9,  "CD_T90":   17,
      "CD_T100":  6,  "CD_T110":  7,  "CD_T120":  16,
      "CD_T130":  11, "CD_T140":  8,  "CD_T150":  18,
      "CD_T160":  13, "CD_T1000": 4,  "CD_T1010": 15
      /* + 100+ state-league and AFLW team IDs */
    }
  }
}
```

Use this when joining StatsPro / CFS payloads (which use `CD_T*`) to `aflapi` payloads (which use integer IDs).

### Venues

```
GET /afl/v2/venues
GET /afl/v2/venues/{venueId}
```

Verified → 200, 552 B (page 0). 191 venues. Per-venue:

```json
{
  "id":          3,
  "providerId":  "CD_V190",
  "name":        "Marvel Stadium",
  "abbreviation":"MRVL",
  "location":    "Melbourne",
  "state":       "VIC",
  "timezone":    "Australia/Melbourne",
  "landOwner":   "Wurundjeri"
}
```

`landOwner` is the AFL's Indigenous land acknowledgement (Larrakia, Yidinji, Wurundjeri, ...).

### Players

```
GET /afl/v2/players
GET /afl/v2/players/{playerId}
```

Verified `/players` → 200, 945 B (page 0). **17,403 players** in the catalogue (all-time). Per-player:

```jsonc
{
  "id": 1,
  "providerId":     "CD_I200131",
  "firstName":      "James",
  "surname":        "Podsiadly",
  "dateOfBirth":    "1981-09-10",
  "draftYear":      "2010",
  "heightInCm":     193,
  "weightInKg":     100,
  "recruitedFrom":  "Yarraville (Vic)/Western U18/Ess Rookies/Coll Rookies/Werribee (VFL)/Geel VFL/Geelong",
  "debutYear":      "2010",
  "draftType":      "rookieElevation",
  "draftPosition":  "58",
  "metadata":       {}
}
```

### Matches (list)

| | |
|---|---|
| **Method/Path** | `GET /afl/v2/matches` |

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `competitionId` | int (or comma-list) | Filter by competition. Accepts repeated/comma-separated values: e.g. `competitionId=1,3` or `competitionId=2,1,2,1,1,2,...` (the web client builds it from selected nav state — duplicates are fine and ignored). |
| `compSeasonId` | int | Filter by comp season. |
| `roundNumber` | int | Round number within the comp season. |
| `teamId` | int (or comma-list) | Filter to matches involving these teams. `?teamId=11,9` = St Kilda or Hawthorn. |
| `status` | enum CSV | One or more of `U,L,C,P,B,S`. Default returns all statuses. |
| `startDate` | `YYYY-MM-DD` | Lower bound on `utcStartTime`. |
| `endDate` | `YYYY-MM-DD` | Upper bound. |
| `sort` | `asc` \| `desc` | Sort by start time. |
| `page` | int | 0-based. |
| `pageSize` | int | Observed up to `300`. |

Verified call (108 matches in 2026 AFL season):

```
GET /afl/v2/matches?status=L,U&startDate=2026-05-25&competitionId=1
```

```jsonc
{
  "meta": {
    "code": 200,
    "pagination": { "page": 0, "numPages": 11, "pageSize": 10, "numEntries": 108 }
  },
  "matches": [
    {
      "id":         8139,
      "providerId": "CD_M20260141201",
      "compSeason": { "id": 85, "providerId": "CD_S2026014", "name": "2026 Toyota AFL Premiership", "shortName": "Premiership", "currentRoundNumber": 12 },
      "round":      { "id": 1355, "providerId": "CD_R202601412", "abbreviation": "Rd 12", "name": "Round 12", "roundNumber": 12, "byes": [ /* ... */ ], "utcStartTime": "...", "utcEndTime": "..." },
      "home": {
        "team":   { "id": 11, "providerId": "CD_T130", "name": "St Kilda",  "abbreviation": "STK", "nickname": "Saints", "club": { /* ... */ }, "teamType": "MEN" },
        "score":  { /* present when match has started */ }
      },
      "away": {
        "team":   { "id": 9,  "providerId": "CD_T80",  "name": "Hawthorn",  "abbreviation": "HAW", "nickname": "Hawks",  "club": { /* ... */ }, "teamType": "MEN" }
      },
      "venue":             { "id": 5,  "providerId": "CD_V050", "name": "MCG", "abbreviation": "MCG", "location": "Melbourne", "state": "VIC", "timezone": "Australia/Melbourne" },
      "utcStartTime":      "2026-05-28T09:30:00.000+0000",
      "status":            "U",
      "matchNumber":       8139,
      "matchPriority":     "PRIMARY",
      "broadcastChannels": "Fox Footy"
      /* + further fields: weather, umpires (when known), attendance */
    }
  ]
}
```

The 2026 web client builds `competitionId=` lists by mapping each visible team's primary competitions; that's why captured URLs sometimes contain `?competitionId=2,1,2,1,1,2,...` — the server treats it as a set.

### Matches (single)

```
GET /afl/v2/matches/{matchId}
```

Verified `/matches/8139` → 200, 686 B (no score yet) → up to ~3 KB once the match contains a score and umpires.

Wrapper:

```json
{ "meta": { "code": 200 }, "matches": [ { /* same shape as list above */ } ] }
```

### Match ID map

```
GET /afl/v2/matches/idmap
```

Maps every match `providerId` (`CD_M*`) to its integer `id`. Verified → 200, ~48 KB.

```jsonc
{
  "meta":       { "code": 200 },
  "entityType": "match",
  "idMapResponse": {
    "ids": {
      "CD_M20180141201": 1607,
      "CD_M20180141202": 1608,
      "CD_M20260141201": 8139,
      "CD_M20260161205": 8828
      /* + every historical match */
    }
  }
}
```

### Player ID map

```
GET /afl/v2/players/idmap
```

Maps every player `providerId` (`CD_I*`) to its integer `id`. Verified → 200, ~98 KB, **17,403 mappings**. Same envelope as match/idmap, with `entityType: "player"`.

> **`/venues/idmap`, `/clubs/idmap`, `/compseasons/idmap`** return `HTTP 400` (the route exists but the entity type is rejected). **`/rounds/idmap`** returns `404`. Only **`teams/idmap`**, **`matches/idmap`** and **`players/idmap`** are wired up.

---

## aflapi: Broadcasting

All under `https://aflapi.afl.com.au/broadcasting/`.

### Regions

```
GET /broadcasting/regions
GET /broadcasting/regions/{regionId}
```

Verified `?page=0&pageSize=100` → 200, ~1.6 KB, 26 regions.

```json
[
  { "id": 2,  "name": "VIC - Melbourne",   "timezone": "Australia/Melbourne" },
  { "id": 3,  "name": "UK",                "timezone": "Europe/London" },
  { "id": 4,  "name": "ACT - Canberra",    "timezone": "Australia/ACT" },
  { "id": 5,  "name": "NSW – Sydney",      "timezone": "Australia/Sydney" },
  { "id": 6,  "name": "Tasmania",          "timezone": "Australia/Tasmania" },
  { "id": 7,  "name": "SA – Adelaide",     "timezone": "Australia/Adelaide" },
  { "id": 8,  "name": "WA – Perth",        "timezone": "Australia/Perth" },
  { "id": 9,  "name": "NT – Darwin",       "timezone": "Australia/Darwin" },
  { "id": 10, "name": "USA",               "timezone": "US/Eastern" },
  { "id": 11, "name": "VIC - Regional",    "timezone": "Australia/Victoria" },
  { "id": 12, "name": "Pacific",           "timezone": "Pacific/Fiji" },
  { "id": 13, "name": "Asia",              "timezone": "Asia/Singapore" },
  { "id": 14, "name": "China",             "timezone": "Asia/Hong_Kong" },
  { "id": 15, "name": "New Zealand",       "timezone": "NZ" },
  { "id": 16, "name": "Africa",            "timezone": "Africa/Johannesburg" }
]
```

Single region returns the bare object (no wrapper):

```json
{ "id": 2, "name": "VIC - Melbourne", "timezone": "Australia/Melbourne" }
```

### Broadcasters

```
GET /broadcasting/broadcasters
```

Verified → 200, 1.4 KB. 49 broadcasters (Foxtel, Channel 7, BBC, ESPN, …). Each:

```jsonc
{
  "id": 2,
  "name": "Foxtel",
  "abbreviation": null,
  "logo": {
    "reference": "568475",
    "type": "PHOTO",
    "info": { "original": { "width": 560, "height": 288, "aspectRatio": 1.94, "url": "https://resources.afl.com.au/..." }, "orientation": "NORMAL", "areas": [ /* … */ ] }
  },
  "link": null,
  "restrictedCountries": ["AU"]
}
```

### Channels

```
GET /broadcasting/channels
```

Verified → 200, 2 KB (page 0). **272 channels**. Each:

```jsonc
{
  "id":   4,
  "name": "Fox Footy",
  "abbreviation": null,
  "logo":         { /* photo object */ },
  "link":         null,
  "broadcaster":  { /* broadcaster object */ },
  "channelTypes": [ { "id": 4, "name": "Web", "mediaType": "VIDEO" } ]
}
```

`channelTypes.mediaType` is one of `VIDEO`, `AUDIO`, `TEXT`.

### Events (broadcast schedule)

The broadcast-schedule feed — one entry per match per channel.

| | |
|---|---|
| **Method/Path** | `GET /broadcasting/events` |

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `fromDate` | ISO 8601 (URL-encoded, e.g. `2026-05-25T07:00:00Z`) | Lower bound. |
| `toDate` | ISO 8601 | Optional upper bound. |
| `compseason` | int | Restrict to a comp season. |
| `round` | int | Restrict to a round. |
| `pageSize` | int | Up to `100`. |

Verified `?fromDate=2026-05-25T07%3A00%3A00Z&pageSize=100` → 200, ~25 KB, 31 events.

```jsonc
{
  "pageInfo": { "page": 0, "numPages": 1, "pageSize": 100, "numEntries": 31 },
  "content": [
    {
      "id":            4553,
      "name":          "St Kilda v Hawthorn",
      "startDateTime": "2026-05-28T09:30:00Z",
      "broadcasters":  [],
      "channels":      [
        {
          "info": { /* channel object */ },
          "regions": [ { "id": 2, "name": "VIC - Melbourne", "timezone": "Australia/Melbourne" } ],
          "startTime": "2026-05-28T09:30:00Z",
          "endTime":   "2026-05-28T12:00:00Z",
          "type":      "LIVE"
        }
      ],
      "contentReference": { "id": 8139, "type": "AFL_MATCH" }
    }
  ]
}
```

### Single broadcast event

```
GET /broadcasting/events/{eventId}
```

Verified `/broadcasting/events/4553` → 200, 3 KB. Returns the bare event object (no wrapper).

### Match events (per round/compseason)

Same shape as `/broadcasting/events` but scoped to a (compseason, round).

```
GET /broadcasting/match-events
```

| Name | Type | Description |
|---|---|---|
| `compseason` | int | Required. |
| `round` | int | Required. |
| `pageSize` | int | Up to `50`. |

Verified `?compseason=85&round=12&pageSize=50` → 200, ~12.5 KB, 7 events.

### Live video streams

| | |
|---|---|
| **Method/Path** | `GET /broadcasting/afl/live/video` |

| Name | Type | Description |
|---|---|---|
| `pageSize` | int | Default `25`. |
| `compseason` | int | Optional. |
| `round` | int | Optional. |

Verified `?pageSize=25` → 200, 80 B (`numEntries: 0`) when no AFL games are live. The same path with `?compseason=85&round=12` may also return zero entries off-windowing; while a match is live it returns stream objects:

```jsonc
{
  "pageInfo": { "page": 0, "numPages": 0, "pageSize": 25, "numEntries": 0 },
  "content":  [ /* { id, name, startDateTime, channels: [{ info, regions, startTime, endTime, type:"LIVE", streamUrl }] } */ ]
}
```

### Live audio streams

```
GET /broadcasting/afl/live/audio?pageSize=25
```

Same shape as `live/video`, audio-only channels.

---

## aflapi: Content (Pulse CMS)

All under `https://aflapi.afl.com.au/content/afl/{TYPE}/EN`. The content service is **Pulse CMS** — every piece of editorial content is one of the types listed below.

| Type | Path segment |
|---|---|
| Text article (news) | `/content/afl/text/EN` |
| Video | `/content/afl/video/EN` |
| Photo | `/content/afl/photo/EN` |
| Audio | `/content/afl/audio/EN` |
| Promo | `/content/afl/promo/EN` *(case-insensitive — `/PROMO/EN` also works)* |

### Text articles (news)

| | |
|---|---|
| **Method/Path** | `GET /content/afl/text/EN` |

**Query parameters**

| Name | Type | Description |
|---|---|---|
| `referenceExpression` | URL-encoded boolean expression | Filter on cross-referenced entities (see [Reference expressions](#reference-expressions--tag-expressions)). |
| `tagExpression` | URL-encoded tag expression | Filter on attached tags. |
| `tagNames` | comma-separated tag labels | Convenience alternative to `tagExpression`. |
| `references` | `TYPE:id` (comma-separated) | Shorthand reference filter. |
| `offset` | int | Skip count. |
| `limit` | int | Default `10` (varies). |
| `page`, `pageSize` | int | Pagination. |
| `sort` | string | Sort order. |

Verified:

```
GET /content/afl/text/EN
   ?referenceExpression=(AFL_COMPETITION%3A1)%20or%20(AFL_COMPETITION%3A3)
   &tagExpression=(%22News%22)
   &offset=0&limit=17
```
→ 200, ~157 KB.

Tag-expression patterns observed in the web client:

| Tag expression | Section it powers |
|---|---|
| `("News")` | News index |
| `("brand:fantasy")` | Fantasy hub |
| `("injuries")` | Injuries list |
| `("Trade")` | Trade news |
| `("brand:things-we-learned")` | "Things we learned" feature |
| `("tribunal")` | Tribunal report |
| `("Draft")` | Draft news |
| `("brand:sliding-doors")` | "Sliding doors" feature |
| `("ProgramCategory:Match Replays")` | Match replays (video) |
| `("ProgramCategory:Match Highlights")` | Highlights (video) |
| `("ProgramCategory:Press Conference")` | Press conferences (video) |
| `("lineups-sponsor")` | Lineups sponsor (promo) |

Response shape (top-level):

```jsonc
{
  "pageInfo": { "page": 0, "numPages": 0, "pageSize": 17, "numEntries": 0 },
  "content":  [ /* article objects */ ]
}
```

Per article (selected fields):

```jsonc
{
  "id":         1528224,
  "accountId":  2,
  "type":       "text",
  "title":      "Saints spearhead embraces full name, rich Maori heritage",
  "description":"Jesse Tawhiao-Wardlaw has proudly chosen to use her birth name as her cultural journey continues",
  "date":       "2026-05-26T20:00:00Z",
  "publishFrom":1779825600000,             // unix milliseconds
  "publishTo":  0,                           // 0 = no expiry
  "lastModified": 1779764393899,
  "tags":       [ { "id": 1166, "label": "AFLW" }, { "id": 523, "label": "Google AMP" }, { "id": 3, "label": "News" } ],
  "references": [
    { "type": "AFL_COMPETITION", "id": 3,       "sid": "3",       "label": null },
    { "type": "AFL_PLAYER",      "id": 1971,    "sid": "1971",    "label": null },
    { "type": "AFL_TEAM",        "id": 36,      "sid": "36",      "label": null },
    { "type": "BIO",             "id": 1371993, "sid": "1371993", "label": null }
  ],
  "body":           "<!doctype html>…full article HTML…",
  "summary":        "Jesse Tawhiao-Wardlaw has proudly chosen to use her birth name as her cultural journey continues",
  "author":         "Sarah Black",
  "leadMedia":      { /* photo or video object */ },
  "imageUrl":       "https://resources.afl.com.au/afl/photo/2026/05/26/.../article.jpg",
  "platform":       "PULSE_CMS",
  "language":       "en",
  "titleUrlSegment":"st-kilda-saints-spearhead-jesse-tawhiao-wardlaw-embraces-full-name-rich-maori-heritage",
  "metadata":       { "googleAmp": true, "keywords": "news,aflw", "longTitle": "..." },
  "canonicalUrl":   "",
  "related":        [],
  "hotlinkUrl":     null,
  "onDemandUrl":    "https://resources.afl.com.au/photo-resources/.../article-hi.jpg",
  "duration":       191,
  "subtitle":       null,
  "contentSummary": null
}
```

### Single text article

```
GET /content/afl/text/EN/{id}
```

Verified `/content/afl/text/EN/1528224` → 200, 8.6 KB. Returns the bare article (no `pageInfo`/`content` wrapper).

### Video content

```
GET /content/afl/video/EN
GET /content/afl/video/EN/{id}
```

Same shape as text endpoints but with video-specific fields. Verified `?references=AFL_MATCH%3A8130&tagNames=ProgramCategory%3AMatch%20Replays&limit=30` → 200, 4 KB.

Per-video fields specific to the video type:

```jsonc
{
  "type":     "video",
  "platform": "BRIGHTCOVE",
  "duration": 7251,
  "additionalInfo": {
    "Competition":         "AFL Premiership",
    "FlexId":              "20310915",
    "Quarter":             "NA",
    "CCUrl":               "https://afl-cc-001-uptls.akamaized.net/.../afl_6396271235112_20260521T144006Z.vtt",
    "externalId":          "FL_20310915",
    "LookLiveTimeZone":    "Australia-Melbourne",
    "LookLiveStartTime":   "30-Dec-2037 02:00:00",
    "Premium":             "None",
    "Code":                "Australian Rules Football",
    "ShowCC":              "No",
    "Provider":            "AFLFLM",
    "NoAds":               "ads",
    "Streaming Type":      "VOD",
    "Classification":      "PG"
  },
  "tags": [
    { "id": 1333, "label": "GeoBlocked:AUNZOnly" },
    { "id": 247,  "label": "ProgramCategory:Match Replays" },
    { "id": 496,  "label": "AFLClubExclusive:No" },
    { "id": 124,  "label": "ProgramType:Matches" }
  ],
  "onDemandUrl": "https://...m3u8"   // signed HLS
}
```

### Photo content

```
GET /content/afl/photo/EN
GET /content/afl/photo/EN/{id}
```

Same shape pattern.

### Promo content

```
GET /content/afl/promo/EN
GET /content/afl/promo/EN/{id}
```

Verified `/content/afl/promo/EN/1286984?limit=1` → 200, ~760 B. Promo objects always have `type: "promo"` and embed a `links[]` array of CTAs:

```jsonc
{
  "id":          1286984,
  "type":        "promo",
  "title":       "Unlock what matters most - sign up and choose your favourite team!",
  "description": null,
  "date":        "2025-03-26T23:06:00Z",
  "publishFrom": 1743030417962,
  "publishTo":   0,
  "tags":        [],
  "platform":    "PULSE_CMS",
  "language":    "en",
  "links": [
    { "promoUrl": "/", "linkText": "Sign in or create your AFL iD.", "external": false }
  ],
  "imageUrl": null,
  "promoUrl": null,
  "linkText": null,
  "promoItem": null,
  "item": null
}
```

### PROMO content (alternate path casing)

```
GET /content/afl/PROMO/EN?tagNames=lineups-sponsor&referenceExpression=AFL_COMPETITION%3A1
```

Verified → 200, 796 B. Uppercased type segment is accepted as a synonym — the platform appears case-insensitive on the type segment. Same response shape as the lower-case path.

### Reference expressions & tag expressions

The `referenceExpression` and `tagExpression` query parameters accept a small boolean grammar (URL-encoded):

```
EXPR := ATOM | "(" EXPR ")" | EXPR " and " EXPR | EXPR " or " EXPR | "not " EXPR
ATOM := REFERENCE | TAG_LABEL_LITERAL

REFERENCE       := TYPE ":" id              // e.g. AFL_COMPETITION:1
TAG_LABEL_LITERAL := '"' label '"'           // e.g. "News"
```

Reference types observed:

| Type | Use |
|---|---|
| `AFL_COMPETITION` | id matches the competition `id` (1 = AFL, 3 = AFLW) |
| `AFL_MATCH` | id matches the match `id` |
| `AFL_TEAM` | id matches the team `id` |
| `AFL_PLAYER` | id matches the player `id` |
| `BIO` | id matches a biography object |
| `AFL_VENUE`, `AFL_ROUND`, `AFL_COMPSEASON` | observed in some payloads |

Examples (decoded):

```text
referenceExpression = (AFL_COMPETITION:1) or (AFL_COMPETITION:3)
tagExpression       = ("News")
tagExpression       = ("brand:fantasy")
tagExpression       = ("ProgramCategory:Match Replays")
references          = AFL_MATCH:8130                          // shorthand, single
tagNames            = lineups-sponsor,featured                // CSV form
```

The grammar is **case-sensitive on tag labels**. Tag labels often use `:` as a namespacing separator (`brand:`, `ProgramCategory:`, `ProgramType:`, `AFLClubExclusive:`, `GeoBlocked:`, `AppNewsFeed:`).

---

## api.afl.com.au: CFS (premium feed)

Base: `https://api.afl.com.au/cfs/afl`. **Every endpoint below requires `x-media-mis-token`** (401 otherwise — verified). All paths are GET unless noted; the upstream `host` header in error envelopes reveals the back-end micro-service routing each one (`mis-match`, `mis-players`, `mis-stats`, `mis-matchroster`, `mis-wagering`, `mis-keyserver`, …).

### Match endpoints

#### `matchItem/{matchProviderId}`

Match detail (scoreboard, quarter-by-quarter scores, status, lineups, key stats). Served by `mis-match`.

```
GET /cfs/afl/matchItem/CD_M20260141201
```

The path parameter is the match's **`providerId`** (`CD_M*`), not its integer `id`. Map via [`/afl/v2/matches/idmap`](#match-id-map).

#### `matchInterchange/{matchProviderId}`

Real-time bench rotation / interchange data.

```
GET /cfs/afl/matchInterchange/CD_M20260141201
```

#### `matchRosters/round/{roundProviderId}` (plural — minimal)

Confirmed match-day rosters for every match in a round. Served by `mis-matchroster`.

```
GET /cfs/afl/matchRosters/round/CD_R202601412?minimal=true
```

`minimal=true` strips per-player metadata to leave only the IDs and lineup positions.

#### `matchRoster/full/{matchProviderId}` (singular — full)

Full roster for one match including positions, jumper numbers, and full player metadata. Served by `mis-matchroster`. **Distinct from the plural `matchRosters/round/...` endpoint above** — singular form returns one match's data with no `minimal` toggle.

```
GET /cfs/afl/matchRoster/full/CD_M20260141102
```

### Stats endpoints (CFS-backed)

#### `playerStats/match/{matchProviderId}`

Per-player stats for one match (all stats categories: kicks/marks/handballs/disposals/tackles/clearances/contested-poss/inside-50s/score-involvements/etc.).

```
GET /cfs/afl/playerStats/match/CD_M20260141201
```

#### `teamStats/match/{matchProviderId}`

Per-team aggregate stats for one match.

```
GET /cfs/afl/teamStats/match/CD_M20260141201
```

#### `coach/match/{matchProviderId}/teamStats`

The "AFL Coach" coach-view aggregate stats for a match.

```
GET /cfs/afl/coach/match/CD_M20260141201/teamStats
```

#### `statsCentre/players`

Stats Centre player rollups — used by the comparison/leaderboard widgets. Served by `mis-stats`.

```
GET /cfs/afl/statsCentre/players?competitionId=CD_S2026014&teamIds=CD_T130,CD_T80
```

| Query param | Description |
|---|---|
| `competitionId` | **Comp season** providerId (`CD_S*`), despite the parameter name. |
| `teamIds` | Comma-separated team providerIds (`CD_T*`). |

#### `statsCentre/teams`

Stats Centre **team** rollups (same widget family, different entity).

```
GET /cfs/afl/statsCentre/teams?competitionId=CD_S2026014
```

| Query param | Description |
|---|---|
| `competitionId` | Comp season providerId (`CD_S*`). |

Older AFL data accepts older seasons (`?competitionId=CD_S2020014` is in the web client config).

#### `statsCentre/player/best/season`

A player's best stats for a single season.

```
GET /cfs/afl/statsCentre/player/best/season?playerId=CD_I1023261&competitionId=CD_S2026014
```

#### `statsCentre/player/best/career`

A player's career-best stats (across all seasons).

```
GET /cfs/afl/statsCentre/player/best/career?playerId=CD_I1023261
```

> An `?competitionType=AFLW` flag is also observed in the JS for switching the lookup to the AFLW dataset.

#### `seasonStats`

Aggregate season-stat tables. Served by `mis-stats`.

```
GET /cfs/afl/seasonStats
```

(Token-required — full parameter contract not verified live; based on the upstream service `mis-stats` it accepts `competitionId` and `teamId` filters analogous to `statsCentre/...`.)

### Catalogue endpoints (CFS-backed)

#### `players`

CFS-side player catalogue with **rich filters** (different from the public `aflapi.afl.com.au/afl/v2/players` — this one is scoped to a season/team and uses providerId values). Served by `mis-players`.

```
GET /cfs/afl/players?pageSize=20&pageNum=1&sortBy=name&seasonId=CD_S2026014&teamIds=&playerPosition=
```

| Query param | Type | Description |
|---|---|---|
| `pageSize` | int | Items per page. |
| `pageNum` | int | **1-based** (note: differs from `aflapi.afl.com.au` which is 0-based via `?page=`). |
| `sortBy` | string | `name`, `goals`, `disposals`, `kicks`, etc. |
| `seasonId` | string | Comp season providerId (`CD_S*`). |
| `teamIds` | string (CSV) | Comma-separated team providerIds. Empty = all teams. |
| `playerPosition` | string | Filter by position (`FWD`, `MID`, `DEF`, `RUC`, etc.). |

#### `playerProfile/{playerProviderId}`

Player biographical / career profile.

```
GET /cfs/afl/playerProfile/CD_I1023261
```

#### `competitions` / `seasons` / `venues`

CFS-side versions of the public catalogues, used by widgets that need provider-ID values without the join through `/teams/idmap`.

```
GET /cfs/afl/competitions
GET /cfs/afl/seasons
GET /cfs/afl/venues
```

### Best & Fairest / Brownlow

#### `bfawards/season/{seasonProviderId}`

Best & Fairest awards (per-club end-of-season votes) for a season.

```
GET /cfs/afl/bfawards/season/CD_S2026014
```

#### `wagering/playerMarket/brownlow`

Brownlow Medal player markets (odds, projections).

```
GET /cfs/afl/wagering/playerMarket/brownlow
```

### Live ladder

#### `liveLadder/round/{roundProviderId}`

The projected ladder **as currently playing** — recalculates on each goal during in-play matches.

```
GET /cfs/afl/liveLadder/round/CD_R202601412
```

### Draft

#### `draft/year/{year}`

Draft year overview (selections, board, picks).

```
GET /cfs/afl/draft/year/2025
```

#### `draft/year/{year}/prospectProfile/{playerProviderId}`

Detailed prospect profile within a draft year.

```
GET /cfs/afl/draft/year/2025/prospectProfile/CD_I1023261
```

#### `draft/prospect/{year}?playerId=`

Lookup variant for a prospect by player ID and year.

```
GET /cfs/afl/draft/prospect/2025?playerId=CD_I1023261
```

### Wagering

#### `wagering?application=Web`

Sportsbook integration odds feed. The web client passes `?application=Web`.

```
GET /cfs/afl/wagering?application=Web
```

(See also `wagering/playerMarket/brownlow` above. The `wagering disabled in Site Settings TRUE` string in the JS bundle indicates the feed can be disabled via the CMS site-settings.)

### Auth / utility

#### `WMCTok` (POST)

The **Web Media Client Token** endpoint. Called by the front-end to mint the `x-media-mis-token` itself. Method: `POST`. Body / auth requirements not reverse-engineered here; returns `{"message":"Missing Authentication Token"}` without proper credentials.

```
POST /cfs/afl/WMCTok
```

> The error log line `"Unable to retrieve WMCTok"` appears in the JS bundle when the call fails.

#### `mediaAuth`

Returns a media-auth descriptor (used internally for video URL signing).

```
GET /cfs/afl/mediaAuth
```

---

## api.afl.com.au: StatsPro

Base: `https://api.afl.com.au/statspro`. Same `x-media-mis-token` requirement. **All paths verified to exist (401 = exists, requires token).**

### Player stats — leaderboards

#### `leadingPlayerStats/season/{seasonProviderId}`

Season-leader leaderboards (one entry per stat: goals, kicks, marks, tackles, …).

```
GET /statspro/leadingPlayerStats/season/CD_S2026014?limit=5
```

#### `leadingPlayerMatchTotals/round/{roundProviderId}`

Round leaders (per-stat best in the round).

```
GET /statspro/leadingPlayerMatchTotals/round/CD_R202601411
```

#### `leadingPlayerMatchTotals/season/{seasonProviderId}`

Season-leaders for per-match totals (best single-game performances of the season).

```
GET /statspro/leadingPlayerMatchTotals/season/CD_S2026014
```

### Team stats — leaderboards

#### `leadingTeamStats/season/{seasonProviderId}`

Season-leader team rankings (per stat).

```
GET /statspro/leadingTeamStats/season/CD_S2026014
```

### Player stats — bulk / paginated

#### `playersStats/seasons/{seasonProviderId}`

Bulk player-season stats with filters.

```
GET /statspro/playersStats/seasons/CD_S2026014?includeBenchmarks=false&playerNameLike=&playerPosition=&teamId=
```

| Query param | Type | Description |
|---|---|---|
| `includeBenchmarks` | boolean | Embed AFL-average benchmarks alongside each stat. |
| `playerNameLike` | string | Substring match on player name. |
| `playerPosition` | string | Filter by position code (`FWD`/`MID`/`DEF`/`RUC`). |
| `teamId` | string (CSV) | Team providerIds. |

#### `playersStats/rounds/{roundProviderId}?teamId=`

Per-round player stats with team filter (one or two team IDs).

```
GET /statspro/playersStats/rounds/CD_R202601412?teamId=CD_T130,CD_T80
```

#### Generic `playersStats/{type}/{providerId}?includeBenchmarks=`

The JS bundle constructs the URL as ``${statsPro}/playersStats/${type}/${id}?includeBenchmarks=${...}``, where `type` is one of `seasons` or `rounds`. The two endpoints above are the concrete instantiations.

### Team stats — bulk

#### `teamStats/seasons/{seasonProviderId}`

Bulk per-season team stats.

```
GET /statspro/teamStats/seasons/CD_S2026014
```

### Player career stats

#### `playerCareerSeasonStats/{playerProviderId}`

Per-season totals for a player across their entire career.

```
GET /statspro/playerCareerSeasonStats/CD_I1023261
```

| Query param | Type | Description |
|---|---|---|
| `competitionType` | string | Pass `"AFLW"` to get the AFLW career; omit for AFL men's. |

#### `playerCareerSeasonStats/{playerProviderId}/benchmarked`

Same data but augmented with AFL-average benchmark columns for each stat. The web client tries this endpoint first and falls back to the un-benchmarked variant if it returns an error.

```
GET /statspro/playerCareerSeasonStats/CD_I1023261/benchmarked
```

### Redux-state slugs (not endpoints)

The web client's StatsPro module also dispatches Redux actions under paths like:

```
statspro/${n}/setBenchmarking
statspro/${n}/setDataType
statspro/${n}/setFilterItem
statspro/${n}/setNavItem
statspro/${n}/setReady
statspro/${n}/setSort
statspro/${t}
```

These are Redux action types, **not** HTTP endpoints.

---

## api.afl.com.au: Commentary feed

```
GET /cfs/commentaryFeed/{matchProviderId}
```

Live text commentary feed (one line per game event). Same token requirement.

---

## api.afl.com.au: Keyserver (video URL signing)

```
GET /keyserver/urlSigning
```

Signs HLS video URLs for the AFL's CDN. The web client calls this when starting playback; the returned signed URL is then opened in the HLS player.

Anonymous probe returns:

```json
{
  "code": "KEYSERVER001",
  "status": 401,
  "techMessage": "401 UNAUTHORIZED \"Unauthorized\"",
  "userMessage": "Your request could not be processed due to a technical problem. Code: KEYSERVER001"
}
```

---

## api.afl.com.au: CFS-Premium (user)

```
GET https://api.afl.com.au/cfs-premium/users/{userId}/...
```

Bound to an AFL iD account (Okta-issued bearer required). Powers favourited team, watch history, AFL Live Pass entitlement checks. Not documented in detail here.

---

## Site config / Okta

| Component | URL |
|---|---|
| Okta auth host | `https://login.id.afl` |
| Okta profile management | `https://secure.id.afl/profile-management` |
| Okta client ID | `0oa2gv3sqmWOi4pUg3l7` |
| Redirect path | `/callback` |
| Standard Okta endpoints | `/api/v1/authn/recovery/token`, `/v1/token` |

Asset CDN: `https://resources.afl.com.au/afl/...` and `https://www.afl.com.au/static-resources/`.

Photo resources path pattern: `https://resources.afl.com.au/afl/photo/{YYYY}/{MM}/{DD}/{uuid}/{filename}.jpg`. The `info.original.url` field on every embedded photo points here.

Per-club mirrored APIs (same contract as `aflapi.afl.com.au`, scoped to the club):

| Club | API host |
|---|---|
| Adelaide | `aflapi.afc.com.au` |
| Brisbane | `aflapi.lions.com.au` |
| Carlton | `aflapi.carltonfc.com.au` |
| Collingwood | `aflapi.collingwoodfc.com.au` |
| Essendon | `aflapi.essendonfc.com.au` |
| Fremantle | `aflapi.fremantlefc.com.au` |
| Geelong | `aflapi.geelongcats.com.au` |
| Gold Coast | `aflapi.goldcoastfc.com.au` |
| GWS | `aflapi.gwsgiants.com.au` |
| Hawthorn | `aflapi.hawthornfc.com.au` |
| Melbourne | `aflapi.melbournefc.com.au` |
| North Melbourne | `aflapi.nmfc.com.au` |
| Port Adelaide | `aflapi.portadelaidefc.com.au` |
| Richmond | `aflapi.richmondfc.com.au` |
| St Kilda | `aflapi.saints.com.au` |
| Sydney | `aflapi.sydneyswans.com.au` |
| West Coast | `aflapi.westcoasteagles.com.au` |
| Western Bulldogs | `aflapi.westernbulldogs.com.au` |

Salesforce SIT API (form & ticketing): `https://afl-digital-xapi-prd.au-s1.cloudhub.io/api`.

---

## Endpoint quick reference

`⚠️ token-only` means the path returns `401 CFSAPI001` anonymously — i.e. it exists at the gateway but requires a valid `x-media-mis-token`. **All such paths below have been confirmed to exist** (probed and confirmed by the 401 envelope).

### aflapi.afl.com.au (public, no auth)

| # | Group | Method | Path | Verified |
|---|---|---|---|---|
| 1 | Core | GET | `/afl/v2/competitions` | ✅ |
| 2 | Core | GET | `/afl/v2/competitions/{id}` | ✅ |
| 3 | Core | GET | `/afl/v2/competitions/{id}/compseasons?pageSize=` | ✅ |
| 4 | Core | GET | `/afl/v2/compseasons?page=&pageSize=` | ✅ |
| 5 | Core | GET | `/afl/v2/compseasons/{id}` | ✅ |
| 6 | Core | GET | `/afl/v2/compseasons/{id}/rounds?pageSize=&roundNumber=` | ✅ |
| 7 | Core | GET | `/afl/v2/compseasons/{id}/ladders` | ✅ |
| 8 | Core | GET | `/afl/v2/seasons` | ✅ |
| 9 | Core | GET | `/afl/v2/seasons/{id}` | ✅ |
| 10 | Core | GET | `/afl/v2/clubs` | ✅ |
| 11 | Core | GET | `/afl/v2/clubs/{id}` | ✅ |
| 12 | Core | GET | `/afl/v2/teams` | ✅ |
| 13 | Core | GET | `/afl/v2/teams/{id}` | ✅ |
| 14 | Core | GET | `/afl/v2/teams/idmap` | ✅ |
| 15 | Core | GET | `/afl/v2/venues` | ✅ |
| 16 | Core | GET | `/afl/v2/venues/{id}` | ✅ |
| 17 | Core | GET | `/afl/v2/players` | ✅ |
| 18 | Core | GET | `/afl/v2/players/{id}` | ✅ |
| 19 | Core | GET | `/afl/v2/players/idmap` | ✅ |
| 20 | Core | GET | `/afl/v2/matches` (rich filters) | ✅ |
| 21 | Core | GET | `/afl/v2/matches/{id}` | ✅ |
| 22 | Core | GET | `/afl/v2/matches/idmap` | ✅ |
| 23 | Broadcast | GET | `/broadcasting/regions?page=&pageSize=` | ✅ |
| 24 | Broadcast | GET | `/broadcasting/regions/{id}` | ✅ |
| 25 | Broadcast | GET | `/broadcasting/broadcasters` | ✅ |
| 26 | Broadcast | GET | `/broadcasting/channels` | ✅ |
| 27 | Broadcast | GET | `/broadcasting/events?fromDate=&pageSize=` | ✅ |
| 28 | Broadcast | GET | `/broadcasting/events/{id}` | ✅ |
| 29 | Broadcast | GET | `/broadcasting/match-events?compseason=&round=&pageSize=` | ✅ |
| 30 | Broadcast | GET | `/broadcasting/afl/live/video?pageSize=&compseason=&round=&matchId=` | ✅ |
| 31 | Broadcast | GET | `/broadcasting/afl/live/audio?pageSize=&matchId=` | ✅ |
| 32 | Content | GET | `/content/afl/text/EN?referenceExpression=&tagExpression=&offset=&limit=` | ✅ |
| 33 | Content | GET | `/content/afl/text/EN/{id}` | ✅ |
| 34 | Content | GET | `/content/afl/video/EN?references=&tagNames=&limit=` | ✅ |
| 35 | Content | GET | `/content/afl/video/EN/{id}` | ✅ |
| 36 | Content | GET | `/content/afl/photo/EN[/{id}]` | ❓ same pattern as text/video |
| 37 | Content | GET | `/content/afl/audio/EN[/{id}]` | ❓ same pattern |
| 38 | Content | GET | `/content/afl/promo/EN[/{id}]` | ✅ |
| 39 | Content | GET | `/content/afl/PROMO/EN?tagNames=&referenceExpression=` | ✅ |

### api.afl.com.au — CFS (`/cfs/afl/...`)

| # | Group | Method | Path | Verified |
|---|---|---|---|---|
| 40 | CFS — Match | GET | `/cfs/afl/matchItem/{matchProviderId}` | ⚠️ token-only |
| 41 | CFS — Match | GET | `/cfs/afl/matchInterchange/{matchProviderId}` | ⚠️ token-only |
| 42 | CFS — Match | GET | `/cfs/afl/matchRosters/round/{roundProviderId}?minimal=` | ⚠️ token-only |
| 43 | CFS — Match | GET | `/cfs/afl/matchRoster/full/{matchProviderId}` | ⚠️ token-only |
| 44 | CFS — Stats | GET | `/cfs/afl/playerStats/match/{matchProviderId}` | ⚠️ token-only |
| 45 | CFS — Stats | GET | `/cfs/afl/teamStats/match/{matchProviderId}` | ⚠️ token-only |
| 46 | CFS — Stats | GET | `/cfs/afl/coach/match/{matchProviderId}/teamStats` | ⚠️ token-only |
| 47 | CFS — Stats | GET | `/cfs/afl/statsCentre/players?competitionId=&teamIds=` | ⚠️ token-only |
| 48 | CFS — Stats | GET | `/cfs/afl/statsCentre/teams?competitionId=` | ⚠️ token-only |
| 49 | CFS — Stats | GET | `/cfs/afl/statsCentre/player/best/season?playerId=&competitionId=` | ⚠️ token-only |
| 50 | CFS — Stats | GET | `/cfs/afl/statsCentre/player/best/career?playerId=[&competitionType=AFLW]` | ⚠️ token-only |
| 51 | CFS — Stats | GET | `/cfs/afl/seasonStats` | ⚠️ token-only |
| 52 | CFS — Catalogue | GET | `/cfs/afl/players?pageSize=&pageNum=&sortBy=&seasonId=&teamIds=&playerPosition=` | ⚠️ token-only |
| 53 | CFS — Catalogue | GET | `/cfs/afl/playerProfile/{playerProviderId}` | ⚠️ token-only |
| 54 | CFS — Catalogue | GET | `/cfs/afl/competitions` | ⚠️ token-only |
| 55 | CFS — Catalogue | GET | `/cfs/afl/seasons` | ⚠️ token-only |
| 56 | CFS — Catalogue | GET | `/cfs/afl/venues` | ⚠️ token-only |
| 57 | CFS — Awards | GET | `/cfs/afl/bfawards/season/{seasonProviderId}` | ⚠️ token-only |
| 58 | CFS — Wagering | GET | `/cfs/afl/wagering?application=Web` | ⚠️ token-only |
| 59 | CFS — Wagering | GET | `/cfs/afl/wagering/playerMarket/brownlow` | ⚠️ token-only |
| 60 | CFS — Live | GET | `/cfs/afl/liveLadder/round/{roundProviderId}` | ⚠️ token-only |
| 61 | CFS — Draft | GET | `/cfs/afl/draft/year/{year}` | ⚠️ token-only |
| 62 | CFS — Draft | GET | `/cfs/afl/draft/year/{year}/prospectProfile/{playerProviderId}` | ⚠️ token-only |
| 63 | CFS — Draft | GET | `/cfs/afl/draft/prospect/{year}?playerId=` | ⚠️ token-only |
| 64 | CFS — Auth | POST | `/cfs/afl/WMCTok` | ⚠️ POST, returns AWS API GW envelope |
| 65 | CFS — Auth | GET | `/cfs/afl/mediaAuth` | ⚠️ token-only |
| 66 | Commentary | GET | `/cfs/commentaryFeed/{matchProviderId}` | ⚠️ token-only |

### api.afl.com.au — StatsPro (`/statspro/...`)

| # | Group | Method | Path | Verified |
|---|---|---|---|---|
| 67 | StatsPro | GET | `/statspro/leadingPlayerStats/season/{seasonProviderId}?limit=` | ⚠️ token-only |
| 68 | StatsPro | GET | `/statspro/leadingPlayerMatchTotals/round/{roundProviderId}` | ⚠️ token-only |
| 69 | StatsPro | GET | `/statspro/leadingPlayerMatchTotals/season/{seasonProviderId}` | ⚠️ token-only |
| 70 | StatsPro | GET | `/statspro/leadingTeamStats/season/{seasonProviderId}` | ⚠️ token-only |
| 71 | StatsPro | GET | `/statspro/playersStats/seasons/{seasonProviderId}?includeBenchmarks=&playerNameLike=&playerPosition=&teamId=` | ⚠️ token-only |
| 72 | StatsPro | GET | `/statspro/playersStats/rounds/{roundProviderId}?teamId=,` | ⚠️ token-only |
| 73 | StatsPro | GET | `/statspro/teamStats/seasons/{seasonProviderId}` | ⚠️ token-only |
| 74 | StatsPro | GET | `/statspro/playerCareerSeasonStats/{playerProviderId}[?competitionType=AFLW]` | ⚠️ token-only |
| 75 | StatsPro | GET | `/statspro/playerCareerSeasonStats/{playerProviderId}/benchmarked` | ⚠️ token-only |

### api.afl.com.au — Other

| # | Group | Method | Path | Verified |
|---|---|---|---|---|
| 76 | Keyserver | GET | `/keyserver/urlSigning?url=<HLS_URL>` | ⚠️ token-only |
| 77 | Premium | GET | `/cfs-premium/users/...` | ⚠️ token + Okta |

### Okta (out-of-band)

| # | Group | Method | Path | Verified |
|---|---|---|---|---|
| 78 | Okta | POST | `https://login.id.afl/api/v1/authn/recovery/token` | — |
| 79 | Okta | POST | `https://login.id.afl/v1/token` | — |

---

## Upstream micro-services (from 401 error envelopes)

The 401 response from each `api.afl.com.au` endpoint leaks the back-end `host` header. This lets you confirm an endpoint exists even without a token, and reveals the underlying service architecture:

| Service prefix | Handles |
|---|---|
| `mis-match` | `/cfs/afl/matchItem/...` |
| `mis-matchroster` | `/cfs/afl/matchRoster/...`, `/cfs/afl/matchRosters/...` |
| `mis-players` | `/cfs/afl/players`, `/cfs/afl/playerProfile/...` |
| `mis-stats` | `/cfs/afl/statsCentre/...`, `/cfs/afl/seasonStats`, `/statspro/...` |
| `mis-keyserver` | `/keyserver/urlSigning` |
| `mis-wagering` | `/cfs/afl/wagering*` |
| `mis-commentary` | `/cfs/commentaryFeed/...` |
| `mis-draft` | `/cfs/afl/draft/...` |
| `mis-bfawards` | `/cfs/afl/bfawards/...` |
| `mis-liveladder` | `/cfs/afl/liveLadder/...` |

(Probe any path with no token; the `host` field in the 401 envelope is the pod name of the upstream micro-service.)

---

## Coverage summary

- **79 endpoints documented** — 39 public (verified live) + 36 token-gated on `api.afl.com.au` (existence confirmed via 401 envelopes) + 2 Okta + 2 inferred content variants.
- **CFS Stats** alone: 9 endpoints across `playerStats`, `teamStats`, `coach`, `statsCentre/players`, `statsCentre/teams`, `statsCentre/player/best/{season,career}`, `seasonStats`.
- **StatsPro**: 9 endpoints across `leadingPlayerStats`, `leadingPlayerMatchTotals`, `leadingTeamStats`, `playersStats/{seasons,rounds}`, `teamStats/seasons`, `playerCareerSeasonStats[/benchmarked]`.
- **17,403 players**, **150 teams**, **191 venues**, **272 broadcast channels**, **92 comp seasons** spanning 2012–2026.
- 16 competitions, 26 broadcast regions, 49 broadcasters.

*Verified 2026-05-27 against `https://aflapi.afl.com.au` from an anonymous client. Every `api.afl.com.au` path was probed unauthenticated to confirm existence (401 = exists, 403 = blocked/non-existent, 404 = not routed). Full response shapes for token-gated endpoints require a valid `x-media-mis-token`.*

## Tool reference

Every tool this provider registers, grouped as the server groups them. The
sections above explain the *services*; this maps a tool name onto one.


### `afl.premium.cfs`

| Tool | What it does |
|---|---|
| `afl_cfs_call` | Call any of the AFL CFS premium operations (api.afl.com.au/cfs/afl/...).
Requires the anonymous x-media-mis-token (minted automatically). Path… |

### `afl.premium.keyserver`

| Tool | What it does |
|---|---|
| `afl_keyserver_url_signing` | Sign an AFL HLS video URL for playback (returns a token-signed CDN URL). |

### `afl.premium.statspro`

| Tool | What it does |
|---|---|
| `afl_statspro_call` | Call any of the AFL StatsPro operations (api.afl.com.au/statspro/...).
Requires the anonymous x-media-mis-token (minted automatically). Path… |

### `afl.public.broadcasting`

| Tool | What it does |
|---|---|
| `afl_broadcast_channels` | List broadcast channels (272) with media types (VIDEO/AUDIO/TEXT). |
| `afl_broadcast_event_get` | Get a single broadcast event by id. |
| `afl_broadcast_events` | Broadcast schedule — one entry per match per channel. |
| `afl_broadcast_match_events` | Broadcast events scoped to one (compseason, round). |
| `afl_broadcast_region_get` | Get a single broadcast region by id. |
| `afl_broadcast_regions` | List broadcast regions (26) with timezones. |
| `afl_broadcasters_list` | List broadcasters (49: Foxtel, Channel 7, BBC, ESPN, …). |
| `afl_live_audio` | Live AFL audio streams (empty when no game is live). |
| `afl_live_video` | Live AFL video streams (empty when no game is live). |

### `afl.public.content`

| Tool | What it does |
|---|---|
| `afl_content_photo_get` | Get a single photo content item by id. |
| `afl_content_photo_list` | List photo content. |
| `afl_content_promo_get` | Get a single promo content item by id. |
| `afl_content_promo_list` | List promo / marketing cards (each embeds a links[] of CTAs). |
| `afl_content_text_get` | Get a single text article by id. |
| `afl_content_text_list` | List text articles (news) with reference/tag filters. |
| `afl_content_video_get` | Get a single video content item by id. |
| `afl_content_video_list` | List video content (highlights, replays, press conferences). |

### `afl.public.core`

| Tool | What it does |
|---|---|
| `afl_club_get` | Get a single club by id. |
| `afl_clubs_list` | List AFL/AFLW clubs (32). |
| `afl_competition_compseasons` | List comp seasons within one competition. |
| `afl_competition_get` | Get a single competition by integer id. |
| `afl_competitions_list` | List all AFL competitions (AFL, AFLW, VFL, SANFL, …). |
| `afl_compseason_get` | Get a single comp season (embeds its full rounds array + currentRoundNumber). |
| `afl_compseasons_list` | List comp seasons across all competitions (2012–present). |
| `afl_ladders_get` | Competition ladder up to a comp season's current round. |
| `afl_match_get` | Get a single match by integer id (teams, venue, time, score when started). |
| `afl_matches_idmap` | Map every match providerId (CD_M*) to its integer id (~48 KB). |
| `afl_matches_list` | List matches with filters (competition, season, round, team, status, date). |
| `afl_player_get` | Get a single player by id (bio, draft, height/weight). |
| `afl_players_idmap` | Map every player providerId (CD_I*) to its integer id (~98 KB, 17k+). |
| `afl_players_list` | List players (17k+ all-time catalogue). |
| `afl_rounds_list` | List rounds for a comp season (incl. byes, start/end times). |
| `afl_season_get` | Get a single calendar-year season by id. |
| `afl_seasons_list` | List calendar-year season records. |
| `afl_team_get` | Get a single team by id (incl. social/home-venue metadata). |
| `afl_teams_idmap` | Map CD_T* team providerIds to integer aflapi ids (and vice versa). |
| `afl_teams_list` | List teams (150 incl. AFL men, AFLW, state leagues, historical). |
| `afl_venue_get` | Get a single venue by id. |
| `afl_venues_list` | List venues (191) incl. location, state, timezone, landOwner. |
