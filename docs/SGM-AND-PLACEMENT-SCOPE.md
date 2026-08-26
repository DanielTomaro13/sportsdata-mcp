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

# Where the four books leave the comparator

Three books now price a combination you choose, and the fourth prices the fair benchmark:

| Book | Tool | Correlation-adjusted? | Tells you when it drops a leg? |
|---|---|---|---|
| Sportsbet | `sportsbet_sgm_price` | yes | refuses instead of dropping |
| TAB | `tab_sgm_price` | yes | yes — `redundantPropositions` |
| PointsBet | `pointsbet_sgm_price` | yes | **no — nothing at all** |
| Pinnacle | *(none needed)* | no — the price is the product | n/a |

That is enough to build the thing this scope was for: quote the same legs at the three
Australian books, and compare each against the independent product of Pinnacle's own
straight prices. The gap is the book's correlation charge, and it is now measurable rather
than assumed.

The remaining books — betr, Dabble, Unibet, Entain — are worth doing for coverage, but the
comparator no longer blocks on them.
