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

## 3a. What the logged-in inspection actually found — and why it changes the plan

Inspected live in a logged-in Chrome, 2026-08-27, **read-only: no odds clicked, no betslip
touched, nothing placed.**

### The authenticated API is not cookie-authenticated

Sportsbet's account surface sits behind `www.sportsbet.com.au/apigw/…`, and every call
carries these headers:

| Header | What it is |
|---|---|
| `accesstoken` | **a JWT** — the actual credential |
| `apptoken` | 15 chars, identical on every request — a static public app key, like FanDuel's `_ak` |
| `customer-id` | the account number |
| `channel` | `cxp` |
| `x-request-id` | a fresh UUID per call, trivially generated |
| `accept`, `content-type` | ordinary |

The decisive test: a **same-origin** `fetch` with `credentials: 'include'` — so the session
cookies *were* sent — returns `400 Validation error` on the exact query the page itself had
just run successfully. The cookie is not what authorises the call. The `accesstoken` is.

### The access token is short-lived

The JWT's `exp` was **nine minutes away** when measured, and one token served every call in
the observation window (no refresh observed, though a couple of minutes is not long enough
to rule one out).

**This breaks the `connect`-reads-a-cookie model for Sportsbet.** For FPL, ESPN and MFL a
cookie *is* the credential and lasts months. Here the cookie is not the credential, and the
thing that is expires in minutes. Reading it once and storing it buys under an hour of
automation.

### There IS a refresh token — captured 2026-08-27

Captured by watching a real logout/login in the account holder's own browser. **Request
bodies were never read** — the recorder passed them through untouched, because that is
where a password would be — and responses were reduced to field names and string *lengths*
before anything was reported.

The flow is a textbook OAuth authorisation-code exchange:

```
POST /apigw/ciam/revoke-token        204   (logout)
GET  /apigw/ciam/authorise           200   (session/plugin descriptor, HAL _links)
POST /apigw/ciam/authenticate/{id}   200   (the credential exchange — body never inspected)
POST /apigw/ciam/token               200   (the mint)
```

and the mint returns:

```jsonc
{ "access_token":  "string(826)",   // the short-lived JWT the /apigw calls carry
  "refresh_token": "string(42)",    // opaque, and the durable half
  "id_token":      "string(598)",
  "token_type":    "string(6)",
  "expires_in":     number }
```

**This is the answer that unblocks unattended operation.** The durable credential is the
42-character `refresh_token`, not the password. So the model becomes:

1. The account holder logs in **once, themselves**, in a browser.
2. `connect sportsbet` stores the **refresh token** — the same shape as every other
   connector, just a different string.
3. The engine mints a fresh `access_token` from it whenever the current one nears `exp`,
   and puts that in the `accesstoken` header.
4. Nothing re-authenticates, nothing holds a password, and the scanner runs indefinitely.

Revocation still works the way it should: `POST /apigw/ciam/revoke-token` is what the
logout button calls, so logging out anywhere kills the agent's access too. That is the
property a password would not have given.

### The refresh grant — confirmed, not assumed

Sportsbet's CIAM publishes a full OIDC discovery document at a **public** URL, no
credentials involved:

```
GET /apigw/ciam/.well-known/openid-configuration
```

```jsonc
{ "issuer":              "https://www.sportsbet.com.au/apigw/ciam",
  "token_endpoint":      "https://www.sportsbet.com.au/apigw/ciam/token",
  "revocation_endpoint": "https://www.sportsbet.com.au/apigw/ciam/revoke-token",
  "grant_types_supported": ["implicit", "authorization_code", "refresh_token", …],
  "token_endpoint_auth_methods_supported": [… "none"] }
```

It is PingFederate (`urn:pingidentity.com:oauth2:grant_type:validate_bearer` gives it
away), `refresh_token` is a supported grant, and `none` among the auth methods means a
**public client — no client secret to hold**.

The exact call was then confirmed by probing with a deliberately bogus token, so the real
one was never read or sent:

| Sent | Response |
|---|---|
| nothing | `400 invalid_request` — "grant_type is required" |
| `grant_type=refresh_token` | `400 invalid_request` — "refresh_token parameter is required" |
| `grant_type=refresh_token&refresh_token=BOGUS` | `400 invalid_grant` — "unknown, invalid, or expired refresh token" |

So the refresh is:

```
POST /apigw/ciam/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token&refresh_token=<stored>
```

No `client_id`, no secret.

### Why the refresh token's lifetime does not need measuring

It was tempting to go and measure how long the refresh token lives. It does not matter,
because the third probe above gives the signal directly:

> `invalid_grant` — "unknown, invalid, or expired refresh token"

That is unambiguous and it is the **only** thing the plane needs to know. The scanner
mints access tokens until a refresh returns `invalid_grant`, and *that* is what trips the
staleness alarm and asks for the one human step. Whether it fires after a day or a month
changes nothing about the code — it changes only how often the notification arrives.

Measuring the lifetime would mean introspecting a live refresh token, which means handling
the credential. The error contract is better information and costs nothing.

### On the `password` grant

Discovery also lists `password` among the supported grants, so a username/password login
against this endpoint would work. It is not used here and there is no code path for it:
the refresh token gives the same unattended operation, is revocable from any logout, and
cannot lock the account holder out.

### What is still unknown

- ~~How long the refresh token lives~~ — **does not need answering**; `invalid_grant` is
  the signal, see above.
- ~~The exact refresh grant~~ — **confirmed above.**
- **`expires_in`'s actual value.** Present in the mint response and not yet read. The
  earlier measurement caught an access token with nine minutes left, so the ceiling is
  small — but the plane should mint on `exp` from the JWT rather than on a constant.
- **The placement call itself.** Still the open item, and now the only one.

### What that leaves

1. ~~**Find the refresh flow.**~~ **ANSWERED — see above.** There is a `refresh_token`,
   and `connect` is viable again with it as the stored credential.
2. **Re-connect hourly.** Technically works, practically useless for an unattended scanner.
3. **Re-authenticate programmatically** — which means the account password, and is the one
   thing that stays out of scope here regardless of how convenient it would be.

Until (1) is answered, honest position: **Sportsbet cannot be driven unattended for longer
than one token lifetime.** Everything else in this document still stands; this is the
gating unknown, and it is a bigger one than the placement shape.

### Endpoints found on the way (both reads)

```
GET /apigw/history/bets?filterType=SETTLED&dateType=ALL&limit=10&includeLegData=true
                       &detailedCashout=true&includeForm=true&sortField=DATE&sortOrder=DESC
                       &excludeSgmCashoutQuotes=true
GET /apigw/mdm/round/my-bets/summary
```

The first is `sportsbet_bet_history` — the read-back tool §5 needs. `filterType` takes
`SETTLED`; a pending variant is what read-back would actually use, and `PENDING` alone was
rejected, so its exact parameters still need capturing.

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
