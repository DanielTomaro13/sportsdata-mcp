# ESPN Fantasy writes — the plan

ESPN is the highest-value target after FPL: the deepest read coverage of any platform
here (27 tools), five sports on one credential, and a cookie that in practice lasts about
a year. The read side is done. This is what the write side needs.

Everything in "What is already true" below was verified, not assumed — the probes are in
the session that produced this document, and each is repeatable in one command.

---

## What is already true

| | |
|---|---|
| Read tools | **27** — settings, rosters, standings, matchups, draft, completed *and* pending transactions, box scores, live scoring, positional ratings, player cards, plus the undocumented `allon` mega-view |
| Sports | NFL (`ffl`), MLB (`flb`), NBA (`fba`), NHL (`fhl`), WNBA (`wfba`) — one credential, five games |
| Public leagues | work with **no credential at all** |
| Private leagues | `espn_s2` + `SWID`, sent as one Cookie header via `ESPN_FANTASY_COOKIE` |
| Write host | **`lm-api-writes.fantasy.espn.com`** — a *different host from reads*, and one the spec does not currently know about |

**The write host is real and separate.** A `GET` against it returns `405 Method Not
Allowed` while the same path on `lm-api-reads` returns `200` — it exists and accepts only
write methods.

**The endpoint shape is confirmed:**

```
POST https://lm-api-writes.fantasy.espn.com/apis/v3/games/{game}/seasons/{year}
     /segments/0/leagues/{leagueId}/transactions/
```

Unauthenticated it answers `401` with a clean, typed error body:

```json
{"messages": ["Unauthorized:  Credentials are missing."],
 "details": [{"type": "AUTH_MISSING_CREDENTIALS", ...}]}
```

That typed `details[].type` is a gift: it makes auth failure machine-detectable via
`error_signals`, so an expired cookie can be told apart from a rejected roster move
without string-matching prose.

### One bug found while scoping this, and already fixed

`sportsdata-mcp connect espnfantasy` saved the cookie pair to `ESPN_S2`. The spec reads
`ESPN_FANTASY_COOKIE`. Nothing errored — the wizard said "connected", wrote the file, and
every private-league call still went out anonymous and 401'd. Fixed, and
`tests/unit/test_connect_env_names.py` now asserts every connector targets an env var its
provider actually reads, so the class of bug cannot recur silently.

---

## The one real unknown

**The transaction payload shape is not verified.** The endpoint, host, method and auth
model are known; what a `LINEUP` body looks like field-for-field is not.

This is exactly where FPL was before its writes shipped, and it was resolved the same way
it must be here: read the platform's own JavaScript bundle, then confirm against a single
captured request. Guessing the shape and shipping it would be the one genuinely
irresponsible move available — a malformed roster move against a real league is not
recoverable by an apology.

The `type` values are well attested (`LINEUP`, `WAIVER`, `FREEAGENT`, `TRADE_PROPOSE`,
`TRADE_ACCEPT`, `TRADE_REJECT`), and ESPN's model is understood to be
*items*-shaped — each item naming a player, a source and a target lineup slot — but
"understood to be" is not a contract, and the spec should not claim `shapes_verified:
true` until a real 200 has been seen.

---

## Phasing

### Phase A — read-side hardening (no credential needed, no writes)

1. **Add the write base URL** to the spec (`base_urls.writes`) so a write endpoint can be
   declared at all. Today there is no way to express one.
2. **Add `error_signals`** for `AUTH_MISSING_CREDENTIALS` and its siblings, so a 401
   inside a 200-shaped body is a clean failure rather than a confusing payload.
3. **Give the connector a real verification.** `verify_url` is empty for ESPN because a
   generic check needs a league id. With one league id it becomes checkable — and until
   it is checkable, `connect espnfantasy` writes a credential it has never proven works.

*Deliverable: private-league reads verifiably working, and a connector that can say
"verified" honestly.*

### Phase B — capture the contract

4. **Read ESPN's fantasy JS bundle** for the transaction request builder — this is how
   FPL's payloads were recovered, and it is public code.
5. **Confirm with one captured request**: change a lineup in the browser, copy the
   request *shape* out of devtools. Only the shape is needed; the cookie must never leave
   your machine.

*Deliverable: a written contract, the same way `fpl.yaml` documents FPL's.*

### Phase C — the write tools

6. **`espnfantasy_set_lineup`** in a new `espnfantasy.write` group — reachable only by
   exact group name, never by `*`, `all`, a preset, or `espnfantasy.*`, exactly as
   `fpl.write` is.
7. **`espnfantasy_add_drop`** (FREEAGENT / WAIVER) second, because a waiver claim spends
   a budget and is the one place an idempotency key genuinely matters — a retried claim
   that double-spends FAAB is the worst bug available on this platform.
8. **Trades last, or never.** `TRADE_PROPOSE` sends a message to another human. That is a
   different category of action from moving your own bench player, and it should stay at
   `ask` permanently rather than being policy-configurable.

### Phase D — the agent plane

9. **Split `execute.py` per platform.** It currently hardcodes `fpl_set_lineup`,
   `fpl_transfers` and `fpl_my_team`. Policy, approvals and verification are already
   platform-agnostic; only the execute layer needs an adapter. This is the moment to do
   it — not before, because a second platform is what tells you where the seam belongs.
10. **Extend the staleness alarm to ESPN.** `watch.py` skips any policy whose platform is
    not `fpl`, and `check_credential` calls `fpl_my_team` directly. ESPN needs its own
    check — and it needs it *more* than FPL does, because an annually-expiring cookie
    fails exactly once a year, silently, and probably in the middle of a season.
11. **An ESPN agent spec**, wired the same way `fpl_manager` is: native propose-tools
    only, never the raw write group.

---

## Risks, and what each one costs

| Risk | Likelihood | Cost | Mitigation |
|---|---|---|---|
| Payload shape wrong | medium until captured | a rejected or **wrong** roster move | never ship on a guess; read-back after every write (already built) |
| Waiver double-spend on retry | low | FAAB budget, unrecoverable | never retry writes (already enforced); add a real idempotency key before waivers ship |
| Cookie expires mid-season | **certain, once a year** | a missed week if silent | the staleness alarm — the single highest-value item in this list |
| ESPN changes the endpoint | low (stable for years) | writes stop | typed error bodies make the failure loud, not silent |
| Multi-sport slot rules differ | high | an illegal lineup accepted as legal | verify against the league's own `settings` slot map, not a hardcoded table |

The lineup-slot point deserves emphasis: FPL has one formation rule, and ESPN has one
per sport per league — flex slots, IR slots, position eligibility that changes when a
player gains a second position. A read-back that compares against the *league's declared
slot map* is the only version of this that works across five sports.

---

## What is needed to proceed

**Non-sensitive, and enough to start Phase A immediately:**

- One **ESPN league id** and its **season year** (visible in the league URL — a public
  identifier, not a credential), plus which game it is (`ffl`, `fba`, …).

**For Phase B, from you, on your own machine:**

- Run `sportsdata-mcp connect espnfantasy` (now that it writes the right env var).
- Make one lineup change in the browser with devtools open, and share the request
  **shape** — method, URL, and body with the values replaced by their types.

**Never needed:** your ESPN password, your `espn_s2` value, or your `SWID`. The
connector reads them locally, scoped to one host, and never prints them; nothing in this
plan requires a credential to leave your machine.

---

## Recommendation

Phase A is worth doing now regardless — it is small, needs nothing from you but a league
id, and it fixes a connector that currently writes a credential it never verifies.

Phase C should not start until Phase B is done. The temptation with a well-trodden
undocumented API is to ship the shape everyone says it is; the read-back plane will
catch a bad write after the fact, but "after the fact" on someone's league is still a
real roster move that really happened.
