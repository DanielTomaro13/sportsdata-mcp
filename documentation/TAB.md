# TAB (Tabcorp, Australia) API Documentation

Unofficial reference for the anonymous JSON endpoints behind **tab.com.au**.
Every endpoint, parameter and response shape below was verified against live
traffic (probed 2026-06-04). Fields are reproduced from the wire.

> **No auth, no API key** for public data. All endpoints are `GET` and return
> JSON. Account / wagering (OAuth) surfaces exist but are **out of scope** for a
> read-only data provider — and a stale token actively breaks public reads (an
> empty `Authorization: Bearer` header makes a 200 endpoint 401).

## Hosts

| Host | Role |
|---|---|
| `api.beta.tab.com.au/v1` | Racing + sports info-service, recommendations, multi-builder, trending. |
| `cmsapi.tab.com.au` | CMS content feeds (homepage / offers / promotions / racing). |

### Akamai

The info-service host sits behind **Akamai**, which silently **RST-drops**
(connection reset, no HTTP status) any request missing a full browser header
bundle, and **throttles bursts**. The spec ships the header bundle in
`provider.default_headers` and throttles to ~2.5 req/s with transient-status
retry. A transport reset is *not* an HTTP status, so it can't be retried — keep
call rates modest. (`cmsapi.tab.com.au` is not Akamai-gated.)

## Conventions

- **`jurisdiction` is required on (almost) every endpoint** — one of `NSW`,
  `VIC`, `QLD`, `ACT`, `SA`, `TAS`, `NT`. The tools default it to **`NSW`**;
  override per call. Omitting it entirely yields `INVALID_SYNTAX_ERROR` (HTTP 400).
- **HATEOAS** — every response carries `_links` (with `self`, `selfTemplate`,
  and related rels like `meetings`/`races`/`form`). `selfTemplate` enumerates the
  optional query params an endpoint accepts.
- **Name-based paths** — sport / competition / match / recommendation paths embed
  human **names** with spaces, e.g. `…/sports/AFL Football/competitions/AFL/matches/Adelaide v Geelong`.
  Pass raw names; the HTTP layer percent-encodes them (`AFL%20Football`). Do **not**
  pre-encode.
- **Racing identifiers** — meetings are keyed by `raceType` (`R` thoroughbred,
  `G` greyhound, `H` harness) + `venueMnemonic` (e.g. `HAW` Hawkesbury). Races are
  addressed by `raceNumber` within a meeting.
- **Times** are ISO-8601 UTC.

---

## Racing — `api.beta.tab.com.au` (group `tab.racing`)

| Tool | Path | Capabilities | Notes |
|---|---|---|---|
| `tab_racing_dates` | `/tab-info-service/racing/dates` | — | Dates with meetings (today/tomorrow/future); use to get a timezone-correct date. |
| `tab_racing_meetings` | `/tab-info-service/racing/dates/{date}/meetings` | `racing.meetings_by_date` | All meetings for a date, each with its races + `_links.races`. |
| `tab_racing_meeting_races` | `/…/dates/{date}/meetings/{raceType}/{venueMnemonic}/races` | — | Races for one meeting; each links to its racecard + form. |
| `tab_racing_race` | `/…/races/{raceNumber}` | `racing.race_card`, `racing.race_results` | **Full racecard** — runners with fixed + parimutuel odds, silks, form ratings, pools, bet types; results + dividends once run. |
| `tab_racing_race_form` | `/…/races/{raceNumber}/form` | — | Detailed form guide per runner. |
| `tab_racing_next_to_go` | `/tab-info-service/racing/next-to-go/races` | `racing.next_to_jump` | Races about to jump across codes; each links to its racecard. |
| `tab_racing_jackpots` | `/tab-info-service/racing/jackpots` | — | Jackpot / carryover pools. |
| `tab_racing_futures_meetings` | `/tab-info-service/racing/dates/futures/meetings` | `racing.futures` | Ante-post / futures racing markets. |

> **Gotcha:** the racecard's `selfTemplate` advertises a `fixedOdds` query param,
> but sending `fixedOdds=true` returns `RESOURCE_NOT_FOUND_ERROR` (404). Don't send
> it — runners already carry both `fixedOdds` and `parimutuel` blocks. (The tool
> omits it.)

### Discovery flow (racing)

```
tab_racing_dates                                  → meetingDate ("today")
tab_racing_meetings(date)                          → raceType + venueMnemonic + raceNumber
tab_racing_meeting_races(date, raceType, venue)    → race list (+ form links)
tab_racing_race(date, raceType, venue, raceNumber) → runners, odds, pools, results
```

---

## Sports — `api.beta.tab.com.au` (group `tab.sports`)

| Tool | Path | Capabilities | Notes |
|---|---|---|---|
| `tab_sports` | `/tab-info-service/sports` | `sport.competitions_list` | All sports (HATEOAS root). |
| `tab_sport` | `/tab-info-service/sports/{sport}` | `sport.competitions_list` | One sport + its competitions. Also fronts `Jockey Challenge` / `Racing Extras`. |
| `tab_competition` | `/…/sports/{sport}/competitions/{competition}` | `sport.competition_screen` | Competition page: matches + bet options + top markets. |
| `tab_tournament` | `/…/competitions/{competition}/tournaments/{tournament}` | `sport.competition_screen` | Tournament page nested inside a competition (tennis, golf). Competitions whose page shows `matches: []` list their events here. |
| `tab_match` | `/…/competitions/{competition}/matches/{match}` | `sport.event_markets`, `sport.match_detail`, `sport.same_game_multi` | **Full match book** — markets, Same Game Multi, contestants, in-play, stats. |
| `tab_match_markets` | `/…/matches/{match}/markets` | `sport.event_markets`, `sport.prices` | Just the markets + selections + prices (leaner than the full match object). |
| `tab_sports_next_to_go` | `/tab-info-service/sports/nextToGo` | — | Sport events about to close, by close time. |
| `tab_sports_results` | `/tab-info-service/sports/results` | — | Recently resulted sport events. |
| `tab_multi_builder` | `/multi-builder/items/{sport}` | `sport.same_game_multi` | Multi-builder legs/combinations for a sport. |
| `tab_trending_props` | `/trending-bets-service/propositions-sports` | — | Trending sports propositions. |

### Discovery flow (sports)

```
tab_sports                                  → sport name (e.g. "AFL Football")
tab_sport(sport)                             → competition name (e.g. "AFL")
tab_competition(sport, competition)          → match name (e.g. "Adelaide v Geelong")
tab_tournament(sport, competition, tournament) → matches for tournament-nested sports
                                               (tennis, golf: the competition page
                                               itself shows matches: [])
tab_match(sport, competition, match)         → every market + SGM + stats
```

---

## Discovery / content (group `tab.discovery`)

| Tool | Path / Operation | Capabilities | Notes |
|---|---|---|---|
| `tab_featured_events` | `/recommendation-service/featured-events` | — | Featured events for the homepage. |
| `tab_live_events_summary` | `/recommendation-service/live-events-summary` | `sport.in_play` | Events currently in-play. |
| `tab_recommendation_featured` | `/recommendation-service/{category}/featured` | — | Featured items for a category, e.g. `Jockey Challenge`, `Racing Extras`. |
| `tab_cms_call` | dispatcher over `cmsapi.tab.com.au` | `content.promo` | CMS content feeds — see below. |

`tab_cms_call` operations (browse `tab://cms/operations`) — each ships the
standard `platform`/`os`/`jurisdiction`/`authentication-status` query defaults:

| Operation | Feed |
|---|---|
| `homepage` | `/content/tab-digital/api/v1/homepage.data.json` — homepage tiles + nav |
| `offers` | `/content/tab-digital/api/v1/offers.data.json` — bonus-bet offers |
| `promotions` | `/content/tab-digital/api/v1/promotions.data.json` — promo blocks |
| `racing` | `/content/tab-digital/api/v1/racing.data.json` — racing landing content |

> **Not modelled:** account / wagering OAuth endpoints (out of scope, need
> secrets); `/telize-service/geoip` and the `/v1` index (non-data infra).

---

## Your own account (groups `tab.account` / `tab.write`)

Two tools, and the only ones here that need a personal credential. Everything else works
anonymously or on the public data tier. Captured live 2026-08-27 from real bets.

| Tool | Call | What it does |
|---|---|---|
| `tab_price_slip` | `POST api.beta…/pricing-service/accounts/{n}/enquiry` | Prices a slip **and mints the `decoToken`s placement needs.** Read-only. |
| `tab_place_bet` | `POST webapi…/tab-betting-service/accounts/{n}/betslip` | **Places a real bet.** Irreversible. |

Note the **different host**: pricing is `api.beta.tab.com.au`, the betslip is
`webapi.tab.com.au`. Getting that wrong is a 404 on a call that otherwise looks right.

### Authentication — Auth0, and NOT the data tier

TAB has two identity systems and conflating them is a confusing failure:

- **`oauth`** — client-credentials against `api.beta`, for the public feeds. Nothing to do
  with a person's account.
- **`account`** — **Auth0** at `login.tab.com.au`, the human's account.

Public OIDC discovery (`https://login.tab.com.au/.well-known/openid-configuration`) shows
`refresh_token` among the supported grants and `none` among
`token_endpoint_auth_methods_supported` — a **public client**, so the refresh token in
`TAB_REFRESH_TOKEN` is the entire credential. Requests carry an ordinary
`Authorization: Bearer`.

### Why TAB is the better-behaved book to automate

1. **`decoToken` binds a leg to a price TAB quoted.** The enquiry issues one per priced
   leg and placement will not accept a leg without it. Sportsbet, by contrast, takes a
   price the client asserts with nothing tying it to a real quote.
2. **`transactionId` is an idempotency key.** Resending the *same* id after a timeout asks
   TAB whether that bet landed, rather than placing a second one. Generating a new id to
   retry is how you place the same bet twice. Sportsbet's placement cannot be retried at
   all.
3. **201 Created, and synchronous** — the bet is on when the call returns, where Sportsbet
   answers 202 Accepted and leaves confirmation to a separate read.
4. **The response confirms the economics**: `expectedReturn`, `betCost`, `ticketCost`,
   `accountBalance`, plus `ticketSerialNumber` as the receipt.

**A 201 is still not automatically success.** There is a top-level `errors` array *and* a
per-bet one — both empty on the verified bets. A 201 with a populated per-bet `errors` is
a bet that did not go on, so the status code alone is not the answer.

Full capture detail, including the exact payloads, is in `docs/PLACEMENT-TAB.md` §0.

## Cross-provider comparison

TAB shares capability tags with the other Australian books, so its tools are
directly comparable via `list_tools_by_capability`:

- `racing.race_card` → `tab_racing_race` alongside `sportsbet_racecard`,
  `pointsbet_racing_race`.
- `racing.meetings_by_date` → `tab_racing_meetings` alongside
  `sportsbet_racing_allracing`, `pointsbet_racing_meetings`.
- `sport.event_markets` / `sport.match_detail` → `tab_match` alongside
  `sportsbet_event_markets`, `pointsbet_event`.
- `racing.next_to_jump` → `tab_racing_next_to_go` alongside
  `sportsbet_racing_multis_events`.

See [`examples/comparator-prompt.md`](../examples/comparator-prompt.md) for a
worked cross-book odds comparison.

## Two racing tools worth knowing about

- **`tab_racing_runner_form`** — per-runner detailed form for one runner in a race: recent starts, times, track and distance records. Deeper than the form carried inline on a racecard.
- **`tab_racing_futures_race`** — a single futures market (e.g. a Cup outright) with its runners and prices, as opposed to `tab_racing_futures_meetings` which lists the meetings carrying futures.


---

## Pricing a Same Game Multi you chose

`tab_sgm_price` prices a combination TAB has not pre-built. `tab_multi_builder` returns
*their* suggestions; this one takes your propositions.

```
POST https://api.beta.tab.com.au/v1/pricing-service/enquiry
{
  "clientDetails": {"jurisdiction": "NSW", "channel": "web"},
  "bets": [{"type": "FIXED_ODDS", "legs": [{"type": "SAME_GAME_MULTI",
    "propositions": [{"type": "WIN", "propositionId": 1016},
                     {"type": "WIN", "propositionId": 8529}]}]}],
  "returnValidationMatrix": true
}
→ {"bets": [{"status": "ok", "legs": [{"odds": {"decimal": "15.00"}, …}]}]}
```

Same base URL as every other TAB tool. No auth. Verified live 2026-08-28 against AFL
Wst Bulldogs v Collingwood.

### The price is not the product of the legs

H2H Bulldogs is 1.95, Naughton first goal is 11.00. Multiplied that is **21.45**. TAB
prices the pair at **15.00**, because it applies a correlation adjustment — a Bulldogs win
makes a Bulldogs player scoring first more likely, so the combination is worth less than
independence implies. Other combinations price *up*. This is the entire reason to ask
rather than multiply.

### ⚠ Redundant legs are collapsed, not refused

This is the trap, and it is quiet. Ask for a leg that another leg already implies and TAB
does not reject the bet — it **drops the leg, prices what is left, and returns the same
odds**:

| request | result |
|---|---|
| H2H Bulldogs + Naughton 1st goal | **$15.00**, nothing redundant |
| …plus Bulldogs +1.5 line | **$15.00**, the line marked `redundant` |

Both sides of a line, or a line behind the head-to-head it implies, collapse this way. So
a three-leg request can silently become a two-leg bet at an unchanged price. **Always read
`redundantPropositions` before reporting a price** — the odds you got may not be the bet
you asked for.

### Only some markets combine

`tab_match_markets` marks each market with `sameGame` and `sameGameMultipleSelections`.
On the verified match, **52 of 109** markets were SGM-eligible. Proposition ids come from
`markets[].propositions[].id` and must be sent as **integers**.

### Jurisdiction is not cosmetic

Prices and market availability differ by state. `clientDetails.jurisdiction` is required
and must be one of NSW, VIC, ACT, QLD, SA, NT, TAS.

### Compared with Sportsbet

The two books share nothing but the idea:

| | Sportsbet | TAB |
|---|---|---|
| endpoint | `/apigw/multi-pricer/combinations/price` | `/v1/pricing-service/enquiry` |
| ids | `externalId` (market + outcome) | `propositionId` |
| price format | fractional `{numerator, denominator}` | decimal string |
| a leg it dislikes | refused (`ERR-VE`) | **silently dropped** |
| plain curl | works | blocked without browser headers |
