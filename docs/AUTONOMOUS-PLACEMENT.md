# Building an autonomous bet-placing agent

Requested as a detailed design. Written as one, with the boundary stated up front so it
is not a surprise three sections in.

## What this document is, and is not

**It is** the full architecture: the state machine, the gates, the failure modes, the
reconciliation, the kill switches, and the preconditions that would have to hold before
any of it should run. Most of this is transferable from work already shipped here — the
FPL, ESPN and MyFantasyLeague write planes are the same problem with a cheaper blast
radius, and every hard lesson in them applies.

**It is not** an operational guide to the last mile: capturing and replaying an
authenticated placement request, defeating a book's bot detection, or storing gambling
credentials. That part is deliberately absent, and the reason is not squeamishness — it
is that the HTTP call is the *trivial* part of this system and the only part that is
irreversible. Everything below is the work; the POST is twenty lines.

If the preconditions in §7 are ever met, the remaining gap is one captured request, and
whoever holds the accounts can close it in an afternoon.

---

## 1. Why this is different from the fantasy write planes

Three write planes already exist in this codebase and all three took the same shape:
policy → proposal → approval → single write → read-back. That shape is right here too.
What changes is the cost of being wrong.

| | fantasy | betting |
|---|---|---|
| worst single error | a lost gameweek | the stake, gone |
| reversible? | next week | **never** |
| read-back proves | the lineup is what you approved | only that money left |
| error rate tolerable | "rare" | **effectively zero** |
| ToS position | undocumented but tolerated | automated placement is a breach |
| failure compounds? | no | **yes** — tilt, chasing, stake creep |

The last row is the one that has no fantasy analogue. A lineup agent that misbehaves sets
a bad lineup. A staking agent that misbehaves can lose money faster than a human can
notice, and the thing that stops it is not the agent's judgement but a hard limit it
cannot reason its way past.

## 2. The state machine

Every bet is one row moving through states. Nothing skips.

```
        ┌──────────┐
        │ CANDIDATE│  value_scout / odds_specialist produced an edge
        └────┬─────┘
             │  policy: stake within limits? book allowed? market allowed?
       ┌─────┴──────┬──────────────┐
       ▼            ▼              ▼
   REJECTED     PROPOSED        BLOCKED        (each terminal, each logged)
                    │
                    │  human approves (or policy permits unattended)
                    ▼
                ┌────────┐
                │ ARMED  │  a stake, a price, an expiry, an idempotency key
                └───┬────┘
                    │  price re-checked against the quote
              ┌─────┴─────┐
              ▼           ▼
          EXPIRED      PLACING      ← the only irreversible transition
                          │
                    ┌─────┴─────┐
                    ▼           ▼
                 PLACED      FAILED
                    │
                    │  reconcile against the book's own bet list
              ┌─────┴─────┐
              ▼           ▼
           CONFIRMED   ORPHANED     ← placed but not found: the worst state
```

**`ORPHANED` is the state that matters.** A placement that times out mid-flight may or
may not have landed. The agent must never resolve that by guessing, and never by
retrying — see §5.

## 3. The policy layer

Directly analogous to `fantasy/policy.py`, and the same rule applies: **a policy is a gate
the code enforces before a request is built, not a sentence in a prompt.** A prompt loses
arguments; a constructor that raises does not.

```
per book:
  enabled:            false          # default off, per book, not globally
  max_stake:          0              # per bet; 0 means propose-only
  max_daily_stake:    0              # rolling 24h, across ALL books
  max_open_exposure:  0              # sum of unsettled stakes
  max_bets_per_day:   0
  min_edge_pct:       ...            # below this, do not even propose
  allowed_markets:    []             # explicit allow-list, never a deny-list
  quiet_hours:        23:00-07:00
  require_approval_above: 0          # stake above which a human must say yes
```

Five rules that should be **structural, not configurable**:

1. **Default off.** A fresh install places nothing. Enabling is per book, deliberate.
2. **`max_daily_stake` is global, not per book.** Per-book limits multiply; a bankroll
   does not. This is the single most important limit and it must be enforced across the
   whole system, not per agent instance.
3. **In-play is never automatic.** Prices move in seconds and a stale quote is a
   different bet. Live markets are propose-only, always.
4. **No chasing.** If today's realised P&L is negative beyond a threshold, the agent
   proposes and does not place. This is the tilt guard, and it must not be a setting the
   agent can read and reason about — it is checked outside the model's reach.
5. **A stake is never computed by the model.** `kelly_fraction` returns a fraction; the
   staking rule turns it into a number in code. The model's job is finding the edge, not
   sizing it. (This is already how the platform works and it is not an accident.)

## 4. What the model never gets to assert

The same principle that made the fantasy planes safe, applied harder. Anything the model
supplies is something the model can hallucinate, so these are **read, computed, or
refused** — never accepted as arguments:

| value | where it comes from |
|---|---|
| the price | re-fetched from the book immediately before placing |
| the stake | computed from the policy and the bankroll ledger |
| current exposure | the ledger, not the conversation |
| today's P&L | the ledger |
| whether a market is in-play | the book's own event status |
| the idempotency key | generated, not chosen |

If a proposal's tool signature accepts a `stake` parameter, the limit is advisory. It
must not.

## 5. Idempotency, and the one rule that cannot bend

**A placement is never retried. Ever. For any reason.**

This is already enforced one layer down — `sportsdata-mcp` retries POSTs on 429 only,
never on 5xx — and it exists because a replayed fantasy transfer costs points. Here it
costs the stake twice.

The protocol:

1. Generate an idempotency key **before** the request and persist it with the intent.
2. Send it with the placement, if the book supports one. Most do not.
3. On any non-2xx, timeout, or connection error: transition to `ORPHANED`, **do not
   resend**, and page immediately.
4. Resolve `ORPHANED` by **reading the book's own bet list**, never by inference. Until
   that read succeeds, the agent places nothing further at that book.
5. A human confirms the resolution. This is not automatable: it is the one case where
   the system genuinely does not know what it did.

Point 4's second clause is a circuit breaker. One unresolved orphan halts that book,
because the alternative is compounding an unknown.

## 6. Reconciliation — the part that is usually skipped

Read-back for a bet is not "did the POST return 200". It is **does the book's own
account show this bet, at this stake, at this price**.

```
after placing → wait → fetch the book's pending-bets list →
  match on (event, market, selection, stake) →
    found, price matches      → CONFIRMED
    found, price differs      → CONFIRMED, flagged (books re-price; log the slippage)
    not found                 → ORPHANED, page, halt this book
    found twice               → DUPLICATE, page loudly, halt everything
```

`found twice` should be impossible. It must still be checked, because the cost of it
happening silently is unbounded, and every other assumption in this document has been
wrong at least once in the fantasy planes.

Settlement then flows into the existing `bet_tracker`, which already journals, settles
and reports P&L — that half is built and works.

## 7. Preconditions

Autonomous placement should not run until **all** of these hold. They are not a wish
list; each one maps to a failure that has already happened in a cheaper system here.

1. **The safe path has run for a full season first.** Slip preparation (§8) with a human
   placing, producing a measured record. If the recommendations are not profitable when
   a human places them, automating placement automates a loss.
2. **The measured record is positive on CLV**, not on P&L. P&L over a season is noise;
   closing-line value is the signal. `backtester` and the CLV machinery already exist.
3. **Reconciliation is proven** against the book's real bet list, including a
   deliberately induced orphan.
4. **The daily and exposure limits are enforced outside the agent process** — in the
   ledger, so a second agent instance cannot double-spend them.
5. **A kill switch exists that is not code the agent can reach**: a file, an env var
   checked at every placement, or an account-level self-exclusion the agent cannot lift.
6. **The account holder has decided about the ToS** with the terms actually read. This is
   not an engineering question and it is not mine to answer.
7. **Someone other than the agent looks at the ledger daily.** Automation without
   observation is how a bad week becomes a bad month.

## 8. What to build instead, and build now

Slip preparation. It is the same system minus the irreversible transition, it needs none
of the preconditions above, and on Sportsbet it uses a **native product feature** rather
than a workaround:

| book | native handoff |
|---|---|
| Sportsbet | **Fast Code** (`/fastcode/betlive/…`) and **Share-a-Bet** (`/betslip/…/share-a-bet`) |
| others | to be surveyed as each book's SGM work is done |

The flow:

1. `value_scout` / `odds_specialist` find the selection and the best price.
2. `sportsbet_sgm_price` prices the combination, if it is a multi.
3. `bankroll_manager` returns a Kelly **fraction**; the staking rule sizes it in code.
4. **`slip_builder`** emits a Fast Code or share link plus a human-readable summary.
5. `bet_notifier` delivers it — ntfy and Slack are already wired.
6. The account holder taps place, in their own session.
7. `bet_tracker` reconciles *prepared* against *placed*, so an ignored recommendation is
   visible rather than assumed taken.

Step 7 is what makes this more than a convenience: it produces exactly the measured
record precondition 1 and 2 require. **The safe path is also the path that earns the
right to the unsafe one.**

## 9. Honest risk register

| risk | likelihood | cost | mitigated by |
|---|---|---|---|
| double placement | low | 2× stake | never retry; idempotency key; duplicate check |
| stale price | **high** | negative EV on every bet | re-fetch immediately before placing; in-play never automatic |
| runaway loop | low | bankroll | daily cap enforced in the ledger; bets-per-day cap |
| account closed for automation | **medium-high** | balance seized | no mitigation exists — this is the ToS decision |
| silent orphan | medium | unknown exposure | reconcile against the book's list; halt on unresolved |
| model reasons past a limit | low | limit is advisory | limits never in tool signatures; enforced in code |
| tilt / chasing | **high, over time** | compounding | P&L guard outside the model's reach |
| agent runs while owner is away | certain | undetected drift | daily human review; kill switch |

The two rows in bold with no engineering mitigation — account closure and tilt — are the
reasons this document ends where it does. Everything else is solvable; those are choices.

---

## The caching trap (added 2026-08-27, measured)

The engine caches GET responses for 60 s. **Two of the seven pricers are GETs — Unibet and
Entain** — and a re-quote inside that window returns the price that was approved rather
than the price on offer, measured at 0 ms. The other five are POSTs, which the cache key
already refuses.

A drift gate that compares a cached price against the approved one always passes, so the
check protects nothing while appearing to work. Both GET pricers now declare
`never_cache: true`, and a test asserts that **no** pricer can be cacheable — because
"the other five happen to be POSTs" is luck, not a property anyone chose.

Entain was missed when this was first written: the note named only Unibet. The audit in
`tests/unit/test_price_freshness.py` is what found the second one, which is the argument
for auditing the property rather than listing the endpoints by hand.

## Where this stands

Nothing here is built. The scope is recorded so the decision can be revisited once the
SGM pricing work is done across the books, which is the current priority — and which
produces, as a side effect, most of the selection-identity machinery §2 would need.

Related: `docs/SGM-AND-PLACEMENT-SCOPE.md` (per-book findings),
`../sportsdata-agents/docs/FANTASY.md` (the three write planes this design is drawn from).
