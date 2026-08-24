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
   JS bundle.
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
