# Placement on TAB

What an autonomous bet-placing agent would look like **for TAB specifically**. The
architecture, the gates and the preconditions are in
[`AUTONOMOUS-PLACEMENT.md`](AUTONOMOUS-PLACEMENT.md) and are not repeated here — this
document is only the delta, and the same boundary applies: design and failure modes, not
an operational guide to placing money.

Everything below is observed from the SGM pricing work (2026-08-28, AFL Wst Bulldogs v
Collingwood) unless marked unverified.

---

## 1. TAB's identity model, and why it changes the state machine

A bet on TAB is `(jurisdiction, propositionId…)`. Both halves matter more than they look.

### Jurisdiction is part of the bet, not a preference

`clientDetails.jurisdiction` is **required** on the pricer and takes NSW, VIC, ACT, QLD,
SA, NT or TAS. Prices and market availability differ by state — this is a Tabcorp
regulatory structure, not a display setting.

Consequences for a placement plane:

- The **policy** must be per jurisdiction, not just per book. A stake limit that ignores
  which state a bet is priced in is comparing different products.
- **Reconciliation** must match on it. Two bets that look identical in every other field
  can be different bets.
- The account's own jurisdiction and the one used for pricing must be **asserted equal**
  before placing, not assumed. A price fetched as NSW and placed as VIC is a silent
  mispricing, and nothing in the response would reveal it.

### Proposition ids are the unit

`propositionId` (integer, from `tab_match_markets` → `markets[].propositions[].id`) is what
the pricer speaks. Only markets flagged `sameGame: true` combine — 52 of 109 on the
verified match.

TAB also surfaces a human-facing **"Show TAB Prop Number"** toggle on its event pages, and
runs phone betting on 133 390. Whether the displayed prop number is the same integer as the
API's `propositionId` is **unverified** — I could not activate the toggle to check. If it
is, TAB has an unusually clean human handoff (see §5) and confirming it is a two-minute job.

---

## 2. The failure mode unique to TAB: silent redundancy collapse

This is the single most important thing on this page, and it has no Sportsbet analogue.

**TAB does not refuse a leg it will not combine. It drops the leg, prices what remains, and
returns the same odds.** Verified:

| requested | returned | flagged |
|---|---|---|
| H2H Bulldogs + Naughton 1st goal | **$15.00** | nothing |
| …plus Bulldogs +1.5 line | **$15.00** | line marked `redundant` |

A three-leg request became a two-leg bet, at an unchanged price, with a `status: "ok"`.

### What this breaks

Every write plane in this codebase assumes **the intent is the request**. Fantasy planes
verify by comparing what you asked for against what the provider reports afterwards. On
TAB that comparison is wrong by construction: the thing that would be placed is not the
thing that was requested, and the difference is legitimate rather than an error.

### The rule it forces

> **The intent must be re-derived from the pricer's response, never from the request.**

Concretely, a TAB placement flow has an extra mandatory step:

```
propose (3 legs)
   ↓
price  → response says: 2 legs survived, 1 redundant, $15.00
   ↓
RE-STATE the intent as the surviving propositions          ← the extra step
   ↓
approve THAT — the owner approves a 2-leg bet, not a 3-leg one
   ↓
place, reconcile against the surviving set
```

An approval flow that shows the owner their three legs and places two is not an approval.
It is a misrepresentation, and it would be entirely accidental.

**A policy rule follows**: if `redundantPropositions` contains anything with
`status: "redundant"`, the bet is **never** placed unattended, regardless of stake or
settings. Something the owner asked for was discarded, and a human should see that.

---

## 3. No quote token

Sportsbet returns a `quoteId` — a per-request token that makes staleness explicit. **TAB's
response carries no equivalent.** The captured response is:

```json
{"bets": [{"type": "FIXED_ODDS", "status": "ok",
  "legs": [{"odds": {"decimal": "15.00"}, "propositions": […], "redundantPropositions": […]}]}]}
```

No id, no expiry, no timestamp. So price staleness cannot be delegated to the book — it has
to be handled here:

- **Re-price immediately before placing**, never reuse a price from the proposal.
- **Compare against the approved price with an explicit tolerance**, and if it moved beyond
  it, stop and re-propose rather than placing at the new number. The owner approved a
  price, not a selection.
- **In-play is propose-only.** With no quote token and prices moving in seconds, an
  unattended in-play placement is a bet at an unknown price.

---

## 4. Reconciliation on TAB

Read-back must match on the **surviving** propositions, the stake, and the jurisdiction:

```
place → fetch the account's pending bets →
  match on (jurisdiction, surviving propositionIds, stake)
    found once, price within tolerance   → CONFIRMED
    found once, price outside tolerance  → CONFIRMED + flagged (log the slippage)
    not found                            → ORPHANED — halt TAB, page, never retry
    found twice                          → DUPLICATE — halt everything, page loudly
```

`ORPHANED` matters more here than elsewhere because TAB blocks plain HTTP clients (see §6):
a request that fails at the edge looks identical to one that failed after landing.

---

## 5. The safe path on TAB

The prepared-slip handoff, as scoped for Sportsbet. TAB's mechanisms, in descending order
of confidence:

| mechanism | status |
|---|---|
| **Prop numbers** — a human-quotable selection identifier, toggleable on event pages | present; whether it equals `propositionId` is **unverified** |
| **Phone betting** — 133 390, an explicitly human channel | present |
| Bet-slip share link / bet code | **not found**; Sportsbet has both, TAB may not |

So TAB's handoff is likely weaker than Sportsbet's Fast Code and Share-a-Bet. If prop
numbers do equal `propositionId`, the agent can hand over a list of numbers plus the priced
odds and the owner enters them directly — which is a genuinely clean split. **Confirming
that is the next piece of work here**, and it is small.

---

## 6. TAB-specific risks

| risk | why it is TAB-specific | mitigation |
|---|---|---|
| **placing a bet the owner did not approve** | redundancy collapse silently changes the leg set | re-derive intent from the response; never place unattended when anything is redundant |
| **pricing in the wrong jurisdiction** | prices differ by state and nothing in the response flags a mismatch | assert account jurisdiction == pricing jurisdiction before placing |
| **stale price with no token to detect it** | no `quoteId` | re-price immediately before; explicit tolerance; in-play propose-only |
| **edge blocks look like failures** | TAB rejects clients without a full browser header bundle — a plain curl returns nothing at all | treat any transport-level failure as `ORPHANED`, never as "did not send" |

That last row deserves emphasis. During this work a plain `curl` to the pricer returned
`http=000` — no status, no body — while the same request through the engine (which ships
TAB's header bundle) returned 200. A placement client that interprets a connection failure
as "the bet was not placed" would be guessing, and on TAB it would guess wrong often enough
to matter.

---

## Status

Nothing is built. TAB's SGM **pricing** is shipped and verified (`tab_sgm_price`); this
document is the placement scope only, and the preconditions in
[`AUTONOMOUS-PLACEMENT.md`](AUTONOMOUS-PLACEMENT.md) §7 all still apply — none of them are
met today.
