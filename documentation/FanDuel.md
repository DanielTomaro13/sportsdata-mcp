# FanDuel (US) API Documentation

Unofficial reference for the anonymous JSON/GraphQL endpoints behind FanDuel
Racing (TVG) **and** the FanDuel Sportsbook. Verified against live traffic
(probed 2026-06-03/04). **US data** (US tracks + US sports, region NJ).

> **No auth, no API key.** Two surfaces under one provider:
> - **Racing** (`fanduel.racing`) — a **full-query GraphQL** API (POSTs the whole
>   query text, not a persisted hash).
> - **Sportsbook** (`fanduel.sportsbook`) — REST keyed by the static *public* `_ak`
>   web key, region NJ.
>
> The two halves require **different `Origin` headers** (`racing.fanduel.com`
> rejects the sportsbook origin and vice-versa). The provider default carries the
> racing origin; the sportsbook dispatcher overrides `Origin` + `x-sportsbook-region`
> via its own headers.

## Hosts

| Host | Role |
|---|---|
| `api.racing.fanduel.com/cosmo/v1/graphql` | The racing GraphQL API (featured/today races, tracks, pools, talent picks). |
| `service.racing.fanduel.com` | Racing REST aux: site messages, homepage quick-links. |
| `api.sportsbook.fanduel.com` | The sportsbook REST API (event pages, in-play, promos, configs). |
| `fdx-api.sportsbook.fanduel.com` | Live event scores. |

## The `graphql_query` dispatcher

FanDuel Racing is the first **full-query** GraphQL provider in this repo. Unlike
the persisted-query providers (Entain, Sportsbet — which send a sha256 hash), it
POSTs `{operationName, query, variables}` with the literal query text. That text
lives server-side in the spec's `graphql.operations` block, so the model only
supplies an **operation name + variables** (discovered via
`fanduel://racing/operations`).

Every operation carries **`default_variables`** — the boilerplate
`brand=FDR`, `product=TVG5`, `device=Desktop`, `wagerProfile=FDR-Generic`,
filters and sorts — merged *under* whatever the caller passes. So most calls need
**no variables at all**; override only what varies (e.g. `{results: 12}` or
`{trackCode: "GP", raceNumber: "5"}`).

> **Queries are sent verbatim.** FanDuel validates that every declared variable is
> used; a trimmed query that orphans a variable (e.g. dropping the
> `@include(if: $isLoggedIn)` fields) is rejected with `variable … never used`.

### `fanduel_racing_call` operations

| Operation | Returns | Capability |
|---|---|---|
| `getRaceDate` | The current race date (no variables — the simplest probe). | — |
| `getTracks` | All tracks today (id, name, code, race count, greyhound flag, location). | `racing.meetings_by_date` |
| `getTodayRaces` | Every race today across tracks (status, type, video, distance, post time). | `racing.next_to_jump` |
| `getFeaturedRaces` | Top/featured races **with `bettingInterests` → `currentOdds`** (runners, silks, trainer/jockey). | `racing.race_card` |
| `getRace` | **One race's full card** by `trackCode` + `raceNumber` — runners + `currentOdds` + morning-line, for *any* race (not just featured). | `racing.race_card` |
| `getTopPools` | Carry-over / jackpot pools by wager type. | — |
| `getGraphTalentPicks` | Expert talent picks (filterable by `trackCode` + `raceNumber`). | — |

The dispatcher's union capabilities are `racing.next_to_jump`,
`racing.meetings_by_date`, `racing.race_card`.

### Discovery flow

```
fanduel_racing_call(getTracks)                          → trackCode (e.g. "GP")
fanduel_racing_call(getTodayRaces)                       → trackCode + raceNumber
fanduel_racing_call(getRace, {trackCode:"GP", raceNumber:"5"})  → one race's card + odds
fanduel_racing_call(getFeaturedRaces, {results: 12})     → featured races + currentOdds
```

## REST aux — racing (group `fanduel.racing`)

| Tool | Host / Path | Notes |
|---|---|---|
| `fanduel_racing_messages` | `service.racing` `/capi/v1/messages/namespace` | Site copy / disclaimers for a namespace. |
| `fanduel_racing_quicklinks` | `service.racing` `/pes/v1/homepage/quicklinks` | Homepage quick-link tiles. |
| `fanduel_racing_promotions` | `promos-api` `/api/customisedPromotions/retrieveStructured` | Structured racing promotions (POST; `{}` body returns all). |

## Sportsbook — `api.sportsbook.fanduel.com` (group `fanduel.sportsbook`)

`fanduel_sb_call` is a templated-REST dispatcher that carries the static public
`_ak` web key + the sportsbook `Origin`/`x-sportsbook-region: NJ` headers, so the
caller supplies only the variable query params. Browse `fanduel://sportsbook/operations`.

| Operation | Path | Notes |
|---|---|---|
| `application_context` | `/sbapi/application-context` | Nav scaffolding — pick blocks via `dataEntries` (POPULAR_BETTING, QUICK_LINKS, AZ_BETTING, EVENT_TYPES, …). |
| `content_page` | `/sbapi/content-managed-page` | A managed sport/landing page (events + markets) by `customPageId` (e.g. `mlb`, `nfl`, `nba`). |
| `event_page` | `/sbapi/event-page` | Full event page: tabs of markets + selections for one `eventId`. Also carries the Same Game Parlay flags — see below. |
| `inplay_counter` | `/sbapi/in-play/counter` | Count of events currently in-play. |
| `inplay_livedata` | `/ips/inplayservice/v1.0/livedata` | Live scores/media for comma-separated `eventIds`. |
| `promotions` | `/promos/api/v2/promotions` | Sportsbook promotions for a `context`. |
| `season_data` | `/ips/seasondata` | Season metadata / rankings. |
| `static_config` | `/config/static/NJ.json` | Static app config (banners, feature blocks). |
| `polling_config` | `/config/pollingConfig/NJ.json` | Client refresh-cadence config. |

Dispatcher capabilities: `sport.event_markets`, `sport.match_detail`,
`sport.competition_screen`, `sport.in_play`, `content.promo`.

| Discrete tool | Path | Capability |
|---|---|---|
| `fanduel_sb_live_score` | `fdx-api` `/api/v1/live/event/{eventId}/score/NJ` | `sport.match_score` |

### Discovery flow (sportsbook)

```
fanduel_sb_call(content_page, {customPageId: "mlb"})   → eventId (attachments.events)
fanduel_sb_call(event_page,   {eventId})                → every market + selection
  └ attachments.markets[].sgmMarket                     → the SGP-eligible legs
fanduel_sb_live_score(eventId)                          → live score
```

### Same Game Parlay

`event_page` already tells you which markets FanDuel will combine within one event, and
that is currently the whole of the SGP story here. Verified live 2026-08-27.

- **`attachments.markets[].sgmMarket`** is the per-market eligibility flag. On an MLB game
  (`35981997`), 26 of 44 markets were `true`.
- **The SGP tab** is the one with `isSameGameMulti: true` in `layout.tabs` — titled
  "Same Game Parlay™" pre-match and "Live SGP" in-play.
- **`tab` takes the numeric tab id**, and the ids are per event, not global: that MLB game
  used 32 / 61 / 123 / 244 / 249 / 262 / 385. Read `layout.tabs` from a call without `tab`
  to find them. Passing a name (`tab=sgp`) is silently ignored rather than rejected.
- **A thin event is not an event without SGP.** An NFL preseason game returned 3 markets
  and 2 tabs while its SGP card still reported `attachmentsFullyLoaded: false`, so a small
  market count says nothing about SGP availability.

**And the combined price comes from `fanduel_sgp_price`.**

```
POST https://sib.nj.sportsbook.fanduel.com/api/sports/fixedodds/transactional/v1/implyBets
     ?_ak=FhMFpcPWXMeyZxOx
{"betLegs": [{"legType": "SIMPLE_SELECTION",
              "betRunners": [{"runner": {"marketId": "734.180521459", "selectionId": 60427}}]},
             {"legType": "SIMPLE_SELECTION",
              "betRunners": [{"runner": {"marketId": "734.180522215", "selectionId": 7017823}}]}]}
```

Verified live 2026-08-27, unauthenticated, on NBA Boston Celtics @ Detroit Pistons: legs at
2.02 and 1.87 price as a parlay at **3.41275716**, against a naive 3.7765 — a 9.6%
correlation charge.

**Five things that are easy to get wrong**, four of them silently:

1. **`_ak` is load-bearing.** Drop it and the call still returns 200 and prices the
   SINGLES, silently omitting the same-game combination — the one thing you asked for.
   It is the same static public web key the rest of the sportsbook surface uses.
2. **`betRunners[].runner` is doubly nested.** Writing `runners`, or putting the runner
   object straight into `betRunners`, binds to nothing: the call returns 200 with
   `legFailures: INVALID_BET_LEG` and an empty `betRunners`.
3. **Read the entry with `isSGM: true`.** A two-leg request returns *three* combinations —
   two SINGLEs and the DOUBLE. Taking the first gives a single bet at 2.02 while you
   believe you hold a parlay at 3.41.
4. **Use `winAvgOdds.trueOdds.decimalOdds.decimalOdds`, not `averageOdds`.** The latter is
   a display rounding: 3.41 against 3.41275716. Comparing one book's rounded price with
   another's exact one manufactures edge that is not there.
5. **`betFailures: INVALID_COMBINATION` is usually not about your parlay.** It means the
   legs cannot form an *ordinary* multi because they are from the same game — which is the
   whole point of an SGP. It sits alongside a perfectly good `isSGM` entry.

If no `isSGM` entry comes back at all, FanDuel will not combine those legs. That happens
even when both markets are `sgmMarket: true`, so that flag is necessary and not sufficient.
A suspended runner reports `RUNNER_SUSPENDED` instead.

#### Why this endpoint is read-only by construction

`implyBets` is FanDuel's **betslip** service, not a read API — the only one of the seven
SGM pricers in this catalogue that is. Every combination it returns carries a
`betReference`: a signed token that is the input to actually placing the bet, alongside
stake ceilings and bonus-wallet state.

The spec declares `response_fields` so that token — and `betMinStake`, `betMaxStake`,
`betMaxPayout`, `bonusWalletConditions`, `applicablePromotions` and the cashout flags —
is stripped before anything reaches a caller. What survives is the price, the legs it
applies to, and the reason for any refusal. A test asserts the token cannot come back,
because that is the invariant rather than a preference.

**What was ruled out before the capture** (recorded so it is not redone): ~35 candidate
routes on `api.sportsbook.fanduel.com` against a clean 404 baseline; `fdx-api`, which 403s
everything including nonsense; ten documented-parameter variations on `event_page`, every
one byte-identical; and every tab id on a 7-tab event. None of it could have worked — the
pricer is on a different host, and it took a traffic capture to find.

## Cross-provider comparison

FanDuel Racing reuses the racing capability tags, so it composes with the other
books via `list_tools_by_capability` (e.g. `racing.race_card` → `fanduel_racing_call`
alongside `tab_racing_race`, `sportsbet_racecard`, `pointsbet_racing_race`). Note
FanDuel is **US** racing, so a like-for-like odds comparison applies when other US
sources are added; the tag still makes it discoverable.

`fanduel_sb_call` also carries **`sport.same_game_multi`**, for the same reason
`dabble_fixture_details` and `unibet_kambi_call` do: it surfaces the SGP-eligible markets.
For the correlation-adjusted PRICE of a combination, use **`fanduel_sgp_price`** — the
seventh pricer in `docs/SGM-AND-PLACEMENT-SCOPE.md`. FanDuel is US, so a like-for-like
comparison needs other US books rather than the Australian six.

## Not modelled

- `smp.nj.sportsbook.fanduel.com/sportsbook/v1/getMarketPrices` — **gone as of
  2026-08-27**: the host is live and 404s a nonsense path, but this route now answers an
  HTML "Service not Found". It was already not worth modelling (the markets and prices come
  from `event_page`), so this is a correction to the note rather than a loss.
- **The rest of `sib.nj.sportsbook.fanduel.com`.** Only its PRICING call is modelled; the
  placement routes on that service are deliberately absent, and the one endpoint that is
  modelled has its placement token projected away.
- `boapi.sportsbook.fanduel.com/popular/events/{id}` — overlaps `event_page`.
- `service.racing.fanduel.com/seo/v1/metainfo` — requires an `x-tvg-context` header
  (a hyphenated name can't be a tool param) and only returns SEO meta; low value.
- Storyblok CMS (`api.storyblok.com`) — third-party CMS, not a FanDuel host.
- **Other racing GraphQL ops.** Introspection is enabled (`__schema`) and exposes
  ~42 query fields. The public data ops are modelled (`raceDate`, `tracks`, `races`,
  `race`, `carryOverPools`, `talentPicks`); the remainder are account / wager /
  promotion-history ops that need an authenticated session, plus historical-stats
  ops (`pastRaces`, `runnerStats`, `tracksWithMetadata`, `wagerTypes`, …) left out
  to keep the surface focused.
- Account / wagering surfaces — out of scope for a read-only data provider.
