# Scope: SGM pricing, and an agent that places bets

Two requests, deliberately kept in one document because the second depends on the first
and they have very different answers. Scope only — no design, no estimates.

---

## 1. Same Game Multi pricing

### What exists

Eight providers already expose something SGM-shaped, and **every one of them takes an
event id and returns combinations the book has already built**:

| tool | what it gives |
|---|---|
| `pinnacle_matchup_parlay_markets` | parlay markets + prices for one matchup |
| `sportsbet_trending_sgm` | trending SGM combinations for one event |
| `betr_pop_sgm_bet_data` | popular SGM suggestions for one event |
| `pointsbet_preprice_multis` | pre-priced "5 for $25" bundles |
| `tab_multi_builder` | suggested legs for one sport |
| `tab_match`, `dabble_fixture_details` | the full book, SGM-eligible markets marked |

### What does not exist, and is the actual ask

**Pricing a combination the user chose.** "Salah anytime scorer + over 2.5 goals +
Liverpool win" is not in anyone's trending list, and its price is not the product of the
three legs — books apply a correlation adjustment server-side, which is the entire
reason SGM exists as a product. There is no tool here that takes legs and returns a price.

### The scope

1. **Find each book's SGM pricing endpoint.** This is the whole job. It is a POST that
   takes leg identifiers and returns one adjusted price, and it is not in any public
   documentation — same reverse-engineering as FPL and ESPN writes, from each book's own
   JS bundle. **bet365's are already named** —
   `betbuilderpregamecontentapi/pricev2` and the in-play `pricev2ip`, found exactly that
   way; see [BET365-SCOPE.md](BET365-SCOPE.md#6-the-sgm-finding) for the full set and
   what is still unknown about the payload.
2. **Model the leg identity problem.** A leg is `(event, market, selection)` and every
   book names all three differently. The catalogue already resolves competitions and
   markets (`lookup_book_ids`, the market dictionary); selections are the unsolved layer.
3. **A `sgm_price` tool per book**, plus one cross-book comparator — the payoff, because
   correlation adjustments differ sharply between books and the same three legs can be
   meaningfully mispriced at one of them.
4. **De-vig and fair-price the combination**, so the existing value machinery
   (`value_scout`, `odds_specialist`) can judge an SGM the way it judges a single.

### Risks worth naming now

- **These endpoints are undocumented and authenticated on some books.** Expect the FPL
  treatment: read the bundle, verify against one live response, `shapes_verified: false`
  until it returns a real 200.
- **Prices are quoted per-session and expire.** An SGM price fetched five minutes ago is
  not the price you will get, so anything built on this needs a freshness rule, not a
  cache.
- **Several of these books already IP-block CI** (see `.github/drift-known-blocked.txt`),
  so this cannot be verified from GitHub — only from the operator machine.

---

## 2. An agent that places bets on bookmaker sites

### The honest answer first

**I will not build an agent that places real-money bets autonomously, and this platform
is explicitly designed not to.** That is not a gap to be filled later — it is a load-
bearing invariant, stated in `docs/AGENTS.md` ("no product agent places a bet or moves
money"), enforced by a name-based deny filter in `mcp/manager.py`, and asserted by tests.
Sizing tools compute a *fraction* and never a stake, for the same reason.

The reasons are practical as well as principled:

- **It is irreversible and it is money.** Every other write plane in this codebase — FPL,
  ESPN, MFL — got a policy engine, an approval queue and a read-back precisely because a
  wrong lineup costs a gameweek. A wrong bet costs the stake, and there is no read-back
  that undoes it.
- **Automated placement breaches every one of these books' terms**, which is grounds for
  account closure and seized balances — a worse outcome than any edge it could capture.
- **It requires storing gambling-account credentials and driving a logged-in session.**
  That is a credential class this codebase has deliberately never held.

### What I would build instead, which gets most of the value

A **bet-slip preparation** agent, which is the same workflow minus the irreversible step:

1. `value_scout` / `odds_specialist` find the selection and the best price, as today.
2. `bankroll_manager` returns a Kelly *fraction*; the owner's own staking rule turns that
   into a number.
3. **New: build the slip and hand it over.** A deep link into the book's own betslip with
   the selections pre-loaded, or a copyable summary — so placing it is one tap, by a
   human, in their own session.
4. `bet_tracker` journals what was actually placed and settles it, as today.

The human stays the actor. Everything expensive — finding the edge, comparing books,
sizing — is automated; the one step that cannot be undone is not.

### Scope, if you want that

1. Per-book **deep-link format** for a pre-loaded betslip (most AU books support one).
2. A `slip_builder` native tool: selections + stake → link + human-readable summary.
3. Extend `bet_notifier` to deliver it (ntfy/Slack already wired).
4. Extend `bet_tracker` to reconcile "prepared" against "placed", so an ignored
   recommendation is visible rather than assumed taken.

If you want automated placement regardless, that is your call to make on your own
accounts — but it is not something I will build, and it would have to live outside this
platform's invariant rather than inside it.

---

# Bookmaker 1: Sportsbet

Probed live 2026-08-25. Everything below is observed, not assumed.

## SGM pricing — SOLVED, shipped as `sportsbet_sgm_price`

> **Resolved 2026-08-25.** The section below is the investigation as it stood before an
> AFL match was on the board. It is kept because the dead ends are worth knowing: the
> path registry named `/sgm-builder/selections/price`, and the pricer the site actually
> calls is `/multi-pricer/combinations/price`. Static analysis found the wrong one.
>
> The contract, captured from a live SGM build and verified with a plain curl:
>
> ```
> POST /apigw/multi-pricer/combinations/price
> {classExternalId, competitionExternalId, eventExternalId,
>  outcomesExternalIds: [{marketExternalId, outcomeExternalId}, …]}
> → {price: {quoteId, numerator, denominator}}     # 7/5 = $2.40
> ```
>
> Unauthenticated. Every id is an **externalId**, not the internal id every other tool
> in the spec uses — that was the real trap. Full documentation in
> `documentation/Sportsbet.md`.

### The investigation (superseded)

**`POST https://www.sportsbet.com.au/apigw/sgm-builder/selections/price`**

Read out of their own bundle, from a path registry that also names the siblings:

| config key | path |
|---|---|
| `sameGameMultiBuilderPath` | `/sgm-builder/selections/price` |
| `multiPricerPath` | `/multi-pricer/combinations/price` |
| `multiPricerRacingPath` | `/multi-pricer-racing/combinations/price/racing` (SRM) |
| `marketPricingPath` | `/sportsbook-product-catalog/sportsbook/market-pricing` |

It sits under `/apigw`, which is already this spec's `base_urls.default`, so no new host.

### What the probes established

| probe | result | what it means |
|---|---|---|
| `GET` | **405** | POST-only — it is a pricing call, not a resource |
| `POST {}` | 400 `ERR-MP-001` *"More than 1 outcome need to be selected for Same Game Multi bet"* | schema-valid, so the selection field is OPTIONAL in schema; and it is reachable **without auth** — a business error, not a 401 |
| `POST {"anythingElse": …}` | 400 `ERR-VE` | strict schema, `additionalProperties: false` |
| query params | ignored — same `ERR-MP-001` | selections do not travel in the query string |
| bare array body | `ERR-VE` | not a top-level array |

Roughly twenty candidate key names and shapes were rejected (`outcomeIds`,
`selectionIds`, `selections`, `outcomes`, `legs`, `parts`, nested `{bet:…}`,
`{sgm:…}`, the full betslip-leg object, …).

### The one missing piece, and how to get it

The betslip leg shape IS known, from the same bundle:

```js
{ type: "sameGameMulti", eventId, externalEventId, winPrice,
  parts: [{ outcomeId, partDesc }] }
```

…but that is the *betslip* shape, and the pricer rejects it. The pricer's own caller
lives in a lazily-loaded chunk that only downloads on an **SGM-enabled event page**, and
at the time of probing **0 of 20 upcoming events were SGM-enabled** — the board was
tennis and e-soccer only.

Two ways to close it, both cheap:

1. **Re-probe during an AFL/NRL/soccer window**, when SGM-enabled events exist and the
   builder chunk loads. Preferred: no human needed.
2. **One captured request.** Open an SGM-enabled event, add two legs, copy the request
   from devtools. Thirty seconds, and it settles the schema exactly — the same technique
   that resolved FPL's write contract.

Once the body is known this is a small spec addition: one POST endpoint,
`shapes_verified: false` until a live 200, and outcome ids already come from
`sportsbet_event_markets` (verified: `market.selections[].id`, e.g. `1245163881`).

## Placement — Sportsbet supports the safe version natively

The scope above proposes handing a prepared slip to a human rather than placing bets.
On Sportsbet that is not a workaround; it is **two shipped product features**:

| path | feature |
|---|---|
| `/fastcode/betlive/fastcode`, `/fastcode/betlive/fastcodes` | **Fast Code** — a short code that loads a prepared bet |
| `/betslip/pre-placed/share-a-bet`, `/my-account/my-bets/pending-bets/share-a-bet` | **Share-a-Bet** — a shareable slip link |

So the slip-preparation agent has a first-class path here: build the selection, produce a
Fast Code or share link, notify, and let the account holder tap place in their own
session. Nothing automates the irreversible step, nothing stores gambling credentials,
and nothing breaches their terms — the feature exists precisely to pass a slip to a person.

**Still not building autonomous placement**, for the reasons in the section above. This
finding strengthens the alternative rather than changing the answer.


---

# Bookmaker 2: TAB

**SGM pricing: SOLVED**, shipped as `tab_sgm_price`. Captured the same way Sportsbet's
was — driving a real SGM build on a live AFL match and recording the request. Static
analysis was not attempted this time; the browser capture took one pass.

```
POST /v1/pricing-service/enquiry     (the base url the spec already uses)
{clientDetails:{jurisdiction, channel}, bets:[{type:FIXED_ODDS,
 legs:[{type:SAME_GAME_MULTI, propositions:[{type:WIN, propositionId}]}]}],
 returnValidationMatrix:true}
→ {bets:[{status, legs:[{odds:{decimal}, redundantPropositions:[…]}]}]}
```

Verified live: H2H Bulldogs (1.95) + Naughton first goal (11.00) → **15.00**, against a
naive product of 21.45.

**The trap here is different from Sportsbet's.** Sportsbet refuses a leg it will not
combine; TAB *silently drops* it and returns the same price. Adding the Bulldogs +1.5 line
behind the H2H win left the price at 15.00 with the line marked `redundant` — so a
three-leg request became a two-leg bet without erroring. `redundantPropositions` must be
read before any price is reported.

**Engine change this required:** dotted **wire** names on body params, so
`api_name: clientDetails.jurisdiction` nests without forcing the model to hand-build the
envelope. A dot cannot be a Python parameter name, so it had to be the wire name.

**Placement:** not surveyed yet. TAB's own handoff mechanisms (bet codes / shared slips)
should be checked when the placement work is revisited — see `AUTONOMOUS-PLACEMENT.md`.


---

# Bookmaker 3: Pinnacle

**Recommendation: build nothing.** Pinnacle does not have the product the other two do,
and adding an `sgm_price` tool here would be a tool that lies about what the book offers.

Probed live 2026-08-30 across 16,040 matchups in four sports.

## Pinnacle prices a parlay as the product of its legs

The other two books apply a correlation adjustment — that is the entire reason to ask them
rather than multiply. Pinnacle does not:

| matchup | shared markets | identical prices | identical limits |
|---|---|---|---|
| 1634606564 (CFL) | 26 | **26/26** | 26/26 |
| 1630889899 (NFL) | 25 | **25/25** | 25/25 |
| 1634691036 (NFL) | 3 | **3/3** | 3/3 |
| 1634691035 (NFL) | 3 | **3/3** | 3/3 |

`/markets/related/parlay` and `/markets/related/straight` are different URLs returning
**byte-identical payloads** — normalised SHA-1 of both responses matches on every matchup
tested.

So the price of a Pinnacle combination is computable locally: **multiply the leg prices**.
There is no server-side quote to request, and a tool that pretended otherwise would be
inventing an endpoint.

## Same-game parlays are mostly not offered at all

`parlayRestriction` on each matchup, across 16,040 of them:

| value | count | meaning |
|---|---|---|
| `None` | 14,949 | unstated |
| `unique_matchups` | 1,007 | **legs must come from DIFFERENT games** — no SGM |
| `forbidden` | 42 | no parlay at all |
| `allowed` | **42** | same-game legs permitted |

Forty-two matchups out of sixteen thousand allow a same-game parlay, and even on those the
price is the product. Pinnacle is a low-margin sharp book; correlated same-game pricing is
a recreational product and it largely does not sell one.

## What to do instead

1. **Read `parlayRestriction` before offering a Pinnacle combination.** It is already on
   every matchup object from `pinnacle_sport_matchups` — no new call needed. Offering an
   SGM on a `unique_matchups` or `forbidden` matchup is an error the data already prevents.
2. **Compute the combination price locally** as the product of the leg prices, converting
   from American odds first.
3. **Use Pinnacle as the fair-price benchmark, not as an SGM venue.** This is the more
   valuable role: Pinnacle's straight prices are the sharpest on the board, so a
   correlation-adjusted SGM quoted by Sportsbet or TAB can be compared against the
   *independent* product of Pinnacle's own legs. The gap between those two numbers is the
   book's correlation charge, which is exactly the thing a cross-book SGM comparator should
   surface.

Point 3 is the real prize and it needs no new endpoint — only the existing
`pinnacle_matchup_markets` plus arithmetic.

## Note on the existing tool

`pinnacle_matchup_parlay_markets` currently returns the same data as
`pinnacle_matchup_markets`. It is not wrong to keep — Pinnacle's authenticated API may
differentiate where the guest API does not, and the endpoint is real — but its description
should not imply a distinct parlay price, because today there is none.

## Placement

Not surveyed. Pinnacle is not an Australian book and its account model differs from
Sportsbet's and TAB's; if placement is revisited, it needs its own pass rather than an
assumption carried over.


---

# Bookmaker 4: PointsBet

**SGM pricing: SOLVED**, shipped as `pointsbet_sgm_price`. Browser capture again, one
pass, on the same AFL fixture the other two were verified against — which means the three
books can now be quoted on comparable legs.

```
POST /api/v2/sgm/price               (api.au.pointsbet.com, no auth)
{EventKey: "2860313",
 SelectedOutcomes: [{MarketKey, OutcomeKey}, …]}
→ {success, price, message, invalidSelections}
```

`MarketKey` is `fixedOddsMarkets[].key` from `pointsbet_event` and `OutcomeKey` is that
market's own `outcomes[].key`. Both ids were already in a tool we shipped; nothing new was
needed to resolve them.

Verified live 2026-08-27: Match Result Bulldogs (1.96) + Total Over 169.5 (1.90) →
**3.60**, against a naive product of 3.724.

**The trap is TAB's, made worse.** PointsBet also collapses a leg that another leg
implies — Bulldogs H2H plus Bulldogs +1.5 returns **1.96 flat**, the head-to-head price
unchanged, against a naive 3.724 — but unlike TAB it echoes **nothing**. There is no
`redundantPropositions` equivalent, no leg list, no count. A three-leg request priced as
two is indistinguishable from an honest three-leg quote. The only defence is procedural:
never report a PointsBet SGM price without restating the legs that were sent.

Two smaller ones. `enableCorrelatedMulti` reads like an eligibility flag and is not — it
was `true` on all 82 markets of the verified event while the pricer still refused First
Goalscorer, so eligibility is only knowable by asking. And `OutcomeKey` is unique only
within its market (`"11"` is a different bet in two markets on the same event), so an
outcome key carried to the wrong market key prices something else and still returns
success.

**Engine change this required:** none to the request path — the body is flat. One change
to the error path: a refusal is HTTP 200 with `price: 0`, a zero sitting in the field the
caller asked for, so the provider declares an `error_signals` rule. That surfaced a
general gap worth fixing — the error builder took only `message`, so "Selection Suspended"
reached the caller without naming *which* selection, turning a recoverable failure into a
dead end. `_error_evidence` now appends the non-empty sibling collections
(`invalidSelections` here) and deliberately ignores scalars, so PointsBet's fake `price: 0`
is never repeated back.

**Placement:** not surveyed — see `AUTONOMOUS-PLACEMENT.md`.

---

# Bookmaker 5: BetR

**SGM pricing: SOLVED**, shipped as `betr_sgm_price`. Browser capture again, one pass, on
the same AFL fixture as the other three.

```
POST /SameGameMultiPrice             (web20-api.bluebet.com.au, no auth)
{MasterEventID: 2255977,
 Markets: [{EventId, OutcomeId, MarketType}, …]}
→ {Price: 2.2, ErrorNo: 0}
```

Leg ids come from `betr_master_event`, already shipped. Note `EventId` is a MARKET GROUP,
not the match — the most confusable thing in BetR's id space.

Verified live 2026-08-27, with the adjustment running both directions: Bulldogs (1.95) +
Under 139.5 (6.25) → **11.00** against a naive 12.19 (−9.7%), while Bulldogs (1.95) +
Under 201.5 (1.10) → **2.25** against a naive 2.145 (+4.9%).

**BetR is the best-behaved of the four on redundancy and the worst on everything else.**
It *refuses* a leg another leg implies (`ErrorNo 4527`) rather than silently dropping it,
so you can never end up holding a shorter bet than you asked for — the failure TAB and
PointsBet both have. Against that, it has two silent-wrongness paths neither of them does:

1. **It trusts a price you send it.** The site puts `FixedWin` on every leg, and the
   server uses it as a *floor* on the answer. Send 99.0 and the response is
   `{Price: 99.0, ErrorNo: 0}` — a fabricated quote reported as a clean success. Omitting
   the field returns the true price in every case tested, so the spec does not expose it.
   This is the only endpoint of the four where a malformed request produces a *better*
   quote rather than an error.
2. **`MarketType` is required but unvalidated.** Drop it from a verified pair and 2.20
   becomes 21, again with `ErrorNo 0`.

Two smaller ones. `MasterEventID` looks like the field that scopes legs to one match and
is **ignored entirely** — omitted, zeroed and misspelled all returned the same price. And
`4527` is a catch-all whose wording names one of its three causes: an implied leg, a
duplicate leg, and legs from two *different matches* all report "redundant leg in bet".

**Engine change this required:** the 200-with-an-error detail lookup was case-sensitive
and lowercase-only, so BetR's `Message` was invisible and "Same Game Multi must have at
least two legs" would have reached the caller as a bare `4500`. `DETAIL_FIELDS` is now
matched case-insensitively, in priority order rather than body order.

**Placement:** not surveyed — see `AUTONOMOUS-PLACEMENT.md`.

---

# Bookmaker 6: Dabble

**SGM pricing: BLOCKED, and not for want of a product.** Recommend building nothing yet.
This is a different negative from Pinnacle's: Pinnacle does not sell a correlated same
game multi, so there was nothing to fetch. Dabble sells them and advertises them — the
pricer exists, and it is simply not observable from outside the app.

## Why the technique that solved the other five does not apply

Sportsbet, TAB, PointsBet and BetR were each solved the same way in one pass: open the
book's own SGM builder in a browser, record the request it makes, verify it
unauthenticated. **Dabble has no web betting UI.** dabble.com.au is a marketing site whose
call to action is "Install Dabble Today!"; there is no web app behind a login. The only
client that builds an SGM is the native iOS/Android app, so there is no page to drive and
no bundle to read.

## What was established anyway (verified live 2026-08-27)

Dabble does sell the product — its own site advertises "We've got SGMs! ... SGM Tracker" —
and the fixture payload carries the machinery around it:

- **`isSgmAllowed` identifies the eligible legs**, and it means different things on
  different sports. On EPL Crystal Palace v Man City, 76 of 503 markets are SGM-allowed
  and **every one of them has `isSingleAllowed: false`** — a separate feed with its own
  naming vocabulary (`MatchWinner`, `TeamOverUnder_Goal_Home`, `MatchWinnerOverUnderDouble`)
  and its own id-generation batch, distinct from the fixture's first-party markets
  (`match_winner`, ids sharing the fixture's own prefix). On AFL Western Bulldogs v
  Collingwood, 175 of 203 are SGM-allowed *and* single-allowed — the same markets serve
  both products.
- **Every fixture declares an SGM market GROUP that is never populated.** EPL has
  `"Popular SGMs"`, AFL has `"Same Game Multi's"`; both appear in `marketGroups` and
  neither has an entry in `marketGroupMappings`. The group is filled by a call the fixture
  payload does not make — which is the clearest evidence that a separate SGM endpoint
  exists.
- **`selfMultiExtension.allowSelfMulti` is `false`** on every fixture sampled across eight
  competitions, so it is not the flag that gates the feature.
- **Roughly forty candidate pricer routes were probed** against a clean 404 baseline
  (`/sgm/price`, `/frontend-api/same-game-multi`, `/frontend-api/market-groups/{id}`, the
  group-id and fixture-id variants, and so on). Every one returned 404. There is no
  swagger or openapi document; `/health` is the only additional 200 on the host.

Route guessing is the approach that already cost a day on Sportsbet before a browser
capture solved it in one pass, so it was stopped rather than continued.

## What would unblock it

Only observing the app itself: proxying the phone's traffic, or reading the shipped app
binary. Both are decisions for the account holder on their own device rather than
something to set up from here — the first needs a root certificate installed on the
phone, and the second means pulling apart a third-party binary. If you ever run that
capture yourself, the single request to save is the one the app fires when a **second**
leg is added to an SGM; that alone is enough to ship the tool, and everything else in this
document is already in place.

## What Dabble gives you today, without the pricer

The legs and their prices, correctly separated by product. `dabble_fixture_details` tags
every market with an engine-derived `product` ∈ {single, sgm, pickem, srm, racing}, keyed
off Dabble's OWN capability flags rather than the SGM vendor's naming — a decision made in
June specifically so a vendor swap could not break it, and it has since been vindicated:
the `sportcast_` prefixes that were there in June are gone, and the tagger still returns
76 `sgm` markets on the EPL fixture and 0 false positives on AFL.

So Dabble can already contribute the **naive** product of its own leg prices to a
comparison. What it cannot contribute is its correlation-adjusted number, which is the
only interesting one — so it stays out of the comparator until the pricer is captured.

**Placement:** not surveyed, and further away than any other book here — placement would
also be app-only. See `AUTONOMOUS-PLACEMENT.md`.

---

# Bookmaker 7: Unibet

**SGM pricing: SOLVED**, shipped as `unibet_sgm_price`. Browser capture again, on the same
AFL fixture as the rest. Unibet runs on **Kambi**, so this is Kambi's `onDemandPricing` and
the same call shape should hold for any other Kambi-powered book.

```
GET /offering/v2018/ubau/onDemandPricing/event/{eventId}/outcome/{id,id,…}.json
    ?lang=en_AU&market=AU&channel_id=1        (no auth)

→ {eventId, selectedOutcomeIds:[…], selectedOdds:{decimal: 3400, …},
   combinableOutcomeIds:[…]}
```

A plain **GET** — the only one of the five that is not a POST. Outcome ids come from
`unibet_kambi_call(operation="event_betoffer")` and go in the path, comma-joined.

Verified live 2026-08-27: Bulldogs head-to-head (1.92) with Over 170.5 (1.88) prices
**3.40**, against a naive 3.6096.

## This is the best-behaved book of the five

Two properties nothing else here has:

1. **It echoes what it priced.** `selectedOutcomeIds` names the exact set the price applies
   to. TAB tells you which legs it *dropped*; PointsBet tells you nothing at all; Unibet
   hands back the whole list. Duplicate ids are still deduplicated silently — the echo is
   how you notice.
2. **It refuses with a real HTTP 400 and a typed body.** Every other book answers a refusal
   with HTTP 200 and a zero in the price field. Unibet is the only one that needs no
   `error_signals` declaration, and its errors name what was wrong: `invalidOutcomes` lists
   the offending ids.

## …and it has the loudest possible wrong answer

**Kambi reports odds in thousandths.** `decimal: 3400` is **3.40**. Every outcome in the
betoffer feed is scaled the same way (`odds: 1920` is 1.92, `line: 1500` is +1.5). Nothing
in the payload says so. A comparator that forgets this reports one book at 1000x the
others, which is worse than any of the subtler traps in the previous six sections because
it will look like the arbitrage of a lifetime.

Two smaller ones. **1001.0 is a ceiling** — six, eight, ten, twelve and fourteen legs all
returned exactly `1001000` while the naive product kept climbing, so a long multi's
"price" is a payout cap. And **`combinableOutcomeIds` is eligibility, not compatibility**:
it lists what can ever appear in a Bet Builder on the event (940 of 1137, so it does
filter something) but does not drop what clashes with your current picks — both the
opposite head-to-head side and the line the head-to-head implies stayed listed and then
400ed. Its real use is separating an *ineligible* leg from a *conflicting* one, which the
error message does not do.

**Engine change this required:** none. But the endpoint declares `response_pick`, because
the upstream repeats the event's entire bet-offer book — 626 offers, 647 KB of a 610 KB
response — which `event_betoffer` already serves. Projected down to ~11 KB.

**Placement:** not surveyed — see `AUTONOMOUS-PLACEMENT.md`. Worth noting that the same
capture showed the betslip validation call (`cf-al-auth-api.kambicdn.com/.../coupon/
validate.json`), which is placement-adjacent and deliberately not modelled.

---

# Bookmaker 8: Entain (Ladbrokes / Neds)

**SGM pricing: SOLVED**, shipped as `entain_sgm_price`. Captured on Ladbrokes' own SGM tab.
Worth noting where it was NOT: Entain's persisted-GraphQL registry already carries
`SportingEventPopularSameGameMultis`, so the obvious guess was another GraphQL operation.
It is not one — the pricer is on the plain REST gateway.

```
GET /v2/same-game-multi/GetOdds          (api.ladbrokes.com.au, no auth)
    ?same_game_multies={"<eventId>":{"event_id":"<eventId>",
                        "selections":[{"market_id","entrant_id"},…]}}
→ {prices:{"<eventId>":{available:true, odds:{numerator:27, denominator:10}}}}
```

Ids come from `entain_sport_event_card`, already shipped. The map key and the inner
`event_id` are **not** redundant — a mismatch is a 400 — and the map shape is the batch:
several events price in one call, each answered under its own key. That is unique among
the six and the reason the raw envelope is exposed rather than a friendlier single-event
parameter.

Verified live 2026-08-27 on AFL Melbourne v Carlton: Melbourne (2.15) with Over 173.5
(1.88) prices **3.70**, against a naive 4.042.

## `27/10` is 3.70

Prices are fractional, and **decimal = numerator/denominator + 1**. Confirmed against the
site's own displayed odds on the same event — Melbourne shows 2.15 and returns `23/20`,
Over shows 1.88 and returns `22/25` — and every price in `sport/event-card` uses the same
shape, so this is Entain's convention rather than the endpoint's quirk.

This is the mirror image of Unibet's trap and the more insidious of the two. Forgetting
Unibet's ÷1000 gives a number so large it demands attention. Forgetting Entain's +1 gives
2.70 where the truth is 3.70: nothing looks wrong, the book simply appears to be pricing
worse than it is, and it silently loses every comparison it should have won.

## It has the best refusal in the catalogue — and the worst hole

When Entain detects a clash it returns `{available: false, conflicting_selections:
[{market_id, entrant_id}, …]}`, naming the exact offending pair. Nothing else here comes
close; PointsBet says "Selection Suspended", BetR says "redundant leg in bet" for three
different causes. It correctly refused Over with Under, both line sides, two margin bands,
and cross-market impossibilities like *Melbourne to win* with *Carlton by 1-39*.

**But the detector is not complete.** Every exactly-two-entrant SGM-available market on the
verified event was tested — 41 of them. Thirty-five refused their mutually exclusive pair
correctly. Five priced it:

| Market | Impossible pair | Quoted |
|---|---|---|
| Match Betting | Melbourne + Carlton | **146.51** |
| 4th Quarter Match Betting | Carlton + Melbourne | 81.67 |
| 3rd Quarter Match Betting | Carlton + Melbourne | 74.50 |
| 1st Quarter Match Betting | Carlton + Melbourne | 72.29 |
| 2nd Quarter Match Betting | Carlton + Melbourne | 70.78 |

The failing set is the win-market family with two entrants and an *implicit* draw. The
three-entrant version that lists `Tie` as an entrant (`1st Half Betting`) is refused
correctly, which is what makes the pattern legible rather than random.

A bet that cannot win, quoted at 146.51 with an availability flag saying yes, is
indistinguishable from a longshot with enormous edge — precisely what an automated value
screener hunts for. This is the single most dangerous behaviour found across all eight
books, because every other trap makes a real bet mispriced, and this one makes an
impossible bet look like the best opportunity on the board.

## Can it be defended against? Partly, and the honest answer is worth stating

**No field in the payload marks mutual exclusivity.** `num_winners` looks like it should
and does not, in either direction: `Melbourne Alternate Handicaps` is `num_winners: 1` with
96 nested lines that legitimately combine, while `Race To 15` is `num_winners: 3` with two
mutually exclusive entrants. It is a settlement field. That hypothesis was tested and
discarded; it is written down so the next person does not spend the same afternoon on it.

So there is no complete rule that also keeps every legitimate same-market pair. There are
two client-side defences that between them remove the class:

1. **Honour `same_game_multi_available` — the pricer ignores its own flag.** Of 14 markets
   the event card marks unavailable, 12 priced anyway when paired with an ordinary Match
   Betting leg. The two worst impossible quotes live exactly there: `Highest Scoring Half`
   at 143.65 and `1st Half Match Betting` at 110.18 are both flagged unavailable and both
   priced. Filtering on the flag before building is free.
2. **Never combine two legs from the same `market_id`** unless you understand that market.
   Every hole found is a same-market pair. Legitimate same-market pairs exist — nested
   Alternate lines, multi-winner props like Anytime Goal Kicker — so a blanket rule costs
   some coverage. For a cross-book comparator, which combines different markets anyway,
   that cost is near zero.

One near-miss recorded so it is not re-flagged: `To Win Either Half` for both teams prices
at 1.80 and that is **correct** — one team can win each half. The impossible ones all came
back long (70–146); short prices on same-market pairs are usually legitimate.

**It also silently collapses a redundant leg** with `available` still true and no leg echo:
Melbourne to win plus Melbourne on the line returned `23/20`, the single-leg price.

**Engine change this required:** none. And no `error_signals` — malformed requests are real
400s, and a refusal carries no `odds` key at all rather than a fake zero.

**Placement:** not surveyed — see `AUTONOMOUS-PLACEMENT.md`.

---

# Where the eight books leave it

Every Australian book in the catalogue has now been surveyed. Six price a combination you
choose, one prices the fair benchmark, one is blocked.

| Book | Tool | Units | Echoes what it priced? | The trap that will cost you |
|---|---|---|---|---|
| Sportsbet | `sportsbet_sgm_price` | decimal | refuses instead of dropping | — |
| TAB | `tab_sgm_price` | decimal | dropped legs only | collapses a leg, but says so |
| PointsBet | `pointsbet_sgm_price` | decimal | **nothing at all** | collapses a leg silently |
| BetR | `betr_sgm_price` | decimal | refuses instead of dropping | **`FixedWin` is trusted as a price floor** |
| Unibet | `unibet_sgm_price` | **thousandths** | **the full set** | ÷1000; 1001.0 is a cap |
| Entain | `entain_sgm_price` | **fractional +1** | nothing at all | **quotes bets that cannot win** |
| Pinnacle | *(none needed)* | american | n/a | the price simply IS the product |
| Dabble | *(blocked — app-only)* | — | unknown | unknown |

Three outcomes, and the difference decides what to do next: six are **solved**, Pinnacle
needs **nothing built** because its parlay price is the product of its legs, and Dabble is
**blocked on observation** rather than on product — its pricer exists and is only reachable
from the app.

## Four rules the comparator must carry

Each one is here because a specific book behaves this way, not on principle.

1. **Normalise the scale first.** Four books quote plain decimals, Unibet quotes
   thousandths (`3400` = 3.40) and Entain quotes fractions needing a `+1` (`27/10` = 3.70).
   No payload announces its units. The two errors fail differently and both matter: Unibet
   un-scaled is 1000x too large and screams; Entain un-adjusted is 2.70 instead of 3.70,
   looks perfectly reasonable, and quietly loses every comparison it should have won.
2. **Never report a price without restating the legs that produced it.** Four of the six
   can hand back a price for a different bet than you asked for — TAB and PointsBet and
   Entain by collapsing a redundant leg, BetR by honouring a `FixedWin` you supplied. Only
   Unibet echoes the full set back; everywhere else it is the caller's own bookkeeping.
3. **`available: true` is not proof the bet is coherent.** Entain quoted four impossible
   combinations at 70–146 on a 22-market sample. Every other trap here makes a real bet
   mispriced; this one makes an unwinnable bet look like the best opportunity on the board,
   which is exactly what an automated screener would select for.
4. **A zero price is a refusal, not a quote.** PointsBet and BetR answer refusals with
   HTTP 200 and a zero in the field you asked for; both needed `error_signals`. Unibet and
   Entain use real status codes. Assume the 200-with-a-zero shape for any book added later
   until checked.

## What this is now enough to build

Quote the same legs at six books, normalise the units, and compare each against the
independent product of Pinnacle's own straight prices. The gap between a book's
correlation-adjusted number and that independent product is the book's correlation charge
— measurable now rather than assumed, and comparable across books for the first time.

The five capability-tagged pricers plus Entain answer one query
(`sport.same_game_multi` + `sport.prices`), and `tests/unit/test_sgm_comparator.py` pins
them as a set: that they exist, stay tagged, keep `read_only` on every POST, still state
that the price is not the product with a dated worked example, declare an error signal
exactly when the book fakes a price, and — for the two that are not plain decimal — still
say how to convert.

## Placement

Deliberately not surveyed for any of the eight. `AUTONOMOUS-PLACEMENT.md` covers the
architecture and the safety machinery an autonomous placement agent would need;
`PLACEMENT-TAB.md` works it through for one book. The operational last mile — capturing
authenticated placement calls, storing gambling credentials, evading bot detection — is
deliberately absent from both, and none of the six pricers above can move money: they are
all `read_only`, and a test asserts it.
