# Placing a bet on Sportsbet — the concrete plan

`AUTONOMOUS-PLACEMENT.md` is the architecture and the safety machinery, sport-agnostic.
This is book #1 made specific: what exists, what is missing, what it costs in wall-clock
time, and the order to build it in.

Sportsbet is first because its SGM pricer is solid, it is Flutter's Australian brand (so
the session model likely generalises furthest), and its quote response carries a
`quoteId` — which, as section 3 explains, may remove the hardest problem entirely.

---

## 1. The workflow, end to end

```
  ┌── agent ─────────────────────────────────────────────────────────────┐
  │                                                                       │
  │  1. FIND        comparator quotes the same legs at 6 books            │
  │  2. PROPOSE     one bet: book, event, legs, stake, quoted price       │
  │                                                                       │
  └───────────────────────────┬───────────────────────────────────────────┘
                              │
  ┌── you ────────────────────▼───────────────────────────────────────────┐
  │  3. APPROVE     "$25 on Bulldogs + Over 169.5 at 3.60 on Sportsbet"   │
  └───────────────────────────┬───────────────────────────────────────────┘
                              │
  ┌── agent ──────────────────▼───────────────────────────────────────────┐
  │  4. RE-QUOTE    ask Sportsbet again, RIGHT NOW                        │
  │  5. DRIFT GATE  approved 3.60, offered 3.40  ->  ABORT, do not place  │
  │  6. PLACE       one write, never retried                              │
  │  7. READ BACK   pull it from bet history; confirm stake AND price     │
  │  8. RECONCILE   anything unexpected pages you                         │
  └───────────────────────────────────────────────────────────────────────┘
```

Steps 1, 4, 5, 7 and 8 exist or are one step from existing. Step 6 is the only genuinely
new capability, and step 3 is the only one that is not code.

---

## 2. How long it actually takes

Measured cold, 2026-08-27, from Australia, through the real engine:

| Step | Sportsbet | Range across the six books |
|---|---|---|
| Fetch markets (resolve legs) | 208 ms | 84 ms (BetR) – 497 ms (PointsBet, 4 MB) |
| SGM price | **101 ms** | 101 ms – 1.4 s (BetR) |
| Place | *not captured* | assume 300 ms – 1 s |
| Read back from bet history | *not captured* | assume 200 – 500 ms |

**The machine path is roughly 1–3 seconds**, and Sportsbet is the fastest book measured.
That is not the interesting number.

**The interesting number is how long your approval takes**, because the price moves while
you are deciding. An agent that quotes, waits ninety seconds for a human, and then places
is placing a bet nobody priced. Everything in section 3 exists because of that gap.

> **A caching trap that would silently defeat the drift gate — now fixed.** The engine
> caches GET responses for 60 s (`SPORTSDATA_MCP_CACHE_TTL`). **Two pricers are GETs,
> Unibet and Entain**, and a re-quote inside that window returned the *approved* price
> rather than the current one, measured at 0 ms — a drift check comparing a price against
> itself, always agreeing. Both now declare `never_cache: true`, and a test asserts that no
> pricer can be cacheable at all, so a future book cannot reintroduce it. Sportsbet is a
> POST and was never affected, but the plane must not depend on that.

### How long to build

| Phase | What | Estimate |
|---|---|---|
| A | `betting/` plane with a **dry-run** executor — policy, approval binding, expiry, drift gate, budget, read-back interface. No credentials, no money. | the bulk of the work |
| B | Capture Sportsbet's placement call (needs your session) | one browser capture |
| C | `sportsbet_place_bet` in a `.write` group + a `connect sportsbet` profile | small once B is known |
| D | Live with a $1 stake, one leg, one bet | — |

Phase A is the part worth doing carefully and can be finished and tested before anything
touches an account.

---

## 3. The `quoteId` question — the one that changes the design

Sportsbet's SGM pricer already returns one:

```jsonc
{"price": {"quoteId": "f60b1e9d-b0cf-4ed8-bf38-b99de84a56cb",
           "numerator": 13, "denominator": 5}}     // 3.60
```

**If placement accepts that `quoteId` and honours its price**, the hard problem disappears:
the approval binds to the quote, the price you approved is the price you get, and drift
becomes impossible rather than merely detected. The agent's job shrinks to "place quote X
for $Y before it expires".

**If placement re-prices server-side**, the drift gate in step 5 is load-bearing and the
approval has to be short-lived — seconds, not minutes.

This is the single most valuable thing the capture will tell us, and it should be the
first question asked of the captured request. It also decides whether approvals can sit in
a notification for a minute or have to be near-instant.

---

## 4. What already exists

- **The price.** `sportsbet_sgm_price`, verified live, 101 ms.
- **The comparison.** Six books on identical legs, so "is this the best price available"
  is answerable at propose time.
- **The independent re-price.** The same pricer answers the drift check — this is what the
  comparator work bought.
- **The approval machinery.** `fantasy/policy.py`, `approvals.py`, `execute.py`,
  `verify.py` already do propose → policy → approve → one write → read back against a real
  account. The shape transfers; the thresholds do not.
- **The staleness alarm.** `fantasy/watch.py` verifies a credential on a schedule and
  escalates. A dead betting session must page *before* a bet fails, not after.

## 5. What is missing

1. **The placement call.** Not captured. Needs your logged-in session.
2. **A session.** Sportsbet has no `auth` block today — every tool built against it is
   anonymous. Adding one is new surface and should only happen if placement needs it.
3. **`connect sportsbet`.** A `Connector` entry: host, cookie names, a verify call. The
   machinery exists for FPL/ESPN/MFL; this is a row, not a feature.
4. **A budget with teeth.** `kelly_fraction` returns a fraction, not a stake, on purpose.
   Placement is the thing that overturns that, and it should be overturned deliberately —
   a hard period budget enforced inside `execute`, not advice offered to a model.
5. **Bet-history read-back.** Confirming a bet landed *at the price approved*, not merely
   that a bet exists.

---

## 6. Four rules this book specifically needs

1. **Approval binds to a bet AND its price.** "A bet on the Bulldogs" is not approvable.
   "$25 on Bulldogs + Over 169.5 at 3.60 on Sportsbet" is.
2. **Re-quote immediately before placing, bypassing the cache.** See the caching trap
   above. A re-quote that can return a cached number is not a re-quote.
3. **A price that moved is a refusal, not a rounding detail.** Abort and re-propose.
4. **Never retry a placement.** A write that timed out may already have landed. This is
   the one rule in `AUTONOMOUS-PLACEMENT.md` §5 that cannot bend, and it matters more here
   than in fantasy because the duplicate costs money.

---

## 7. Preconditions before anything is placed

- Phase A green, including a dry run that logs a full propose → approve → drift-abort cycle.
- The `quoteId` question answered.
- A hard budget set and enforced in `execute`.
- The staleness alarm running and verified to page.
- First live bet: **one leg, minimum stake**, reconciled by hand against the account.

## 8. Still out of scope

Bot-detection evasion, credential handling, and anything that logs in on your behalf. The
session comes from a login you perform; the agent uses it and never possesses the password.
If Sportsbet's placement endpoint turns out to be defended in a way a backend call cannot
satisfy, that is a finding to report — not a thing to work around.
