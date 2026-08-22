# MyFantasyLeague (MFL)

Fantasy football on [MyFantasyLeague.com](https://www.myfantasyleague.com) — dynasty and
redraft leagues, heavily customisable, and **the only fantasy platform in this catalogue
whose write API is documented by the vendor**.

That distinction is the reason it is here. FPL's and ESPN's write contracts were lifted
out of minified JavaScript and can change without notice. MFL publishes its entire
surface — 79 request types with named, described arguments — at
`https://api.myfantasyleague.com/{year}/api_info?STATE=details`. Everything in the spec
was transcribed from that page and checked against live keyless calls where the endpoint
permits one.

## The two things that will bite you

### 1. It answers HTTP 200 for errors

A bad league id, a missing cookie and a rejected write all come back **200** with an error
document:

```json
{"encoding":"utf-8","version":"1.0","error":{"$t":"Invalid league ID 12345"}}
```

The spec declares `error_signals: [{field: error}]`, which turns that into a real failure.
Without it every failure would arrive as data and be reported as a result — the silent
wrongness class. This is the single most important line in the spec.

### 2. Exports and imports disagree about JSON

| | honours `JSON=1`? | body |
|---|---|---|
| `/export` | yes | JSON |
| `/import` | **no** | XML, always |

Verified live: an import error returns `<error>Invalid League ID</error>` even with
`JSON=1`. The write tools therefore declare `response_format: xml`, and the engine decodes
XML into the same shape MFL's JSON mode produces — so one `error_signals` rule covers both,
and a successful `<status>OK</status>` decodes to `{"status": "OK"}`.

## Authentication — and a correction worth reading

MFL has two mechanisms and **they are not interchangeable**:

| | scope | works for writes? |
|---|---|---|
| `APIKEY` query param | one user + franchise + league | **No.** The vendor states it "does not work for import requests" |
| `Cookie: MFL_USER_ID=…` | the logged-in user | Yes — the only thing that authorises a write |

So MFL is **not** the "API key, no cookie chore" platform it appears to be from the
outside. Writes need a login-derived cookie, exactly like FPL and ESPN.

```bash
sportsdata-mcp connect mfl
```

reads it from your browser, verifies it with a live call, and stores it `0600`. No password
is ever handled. The cookie value is base64 and may contain `+`, `/` and `=`, which is why
it is sent as a header rather than a query parameter.

Public endpoints — `mfl_players`, `mfl_injuries`, `mfl_nfl_schedule` — need nothing at all.

## Rate limits

Real, enforced with **HTTP 429**, and applied **per IP address** — so they are shared with
anything else on your machine. Exact numbers are deliberately unpublished and vary.
Registered clients get roughly 2.5× by sending a registered `User-Agent`. The spec is
conservative by default (2 rps, burst 4).

## Ids, and how everything joins

- **Player ids** are MFL's own (`13593`), not NFL or ESPN ids. `mfl_players` is the
  translation table every other tool depends on; names come back as `"Surname, Firstname"`.
- **Franchise ids** are four digits (`0001`). `mfl_my_leagues` tells you yours in each
  league — every write needs it, and `0000` means "commissioner" in some contexts.
- **Draft picks** appear inside trades as tokens: `DP_02_05` is the current year's round 3
  pick 6 (both numbers are one less than the real ones), `FP_0005_2028_2` is a future pick,
  and `BB_10.50` is $10.50 of blind-bid money.

## Tools

**Reference** (no league, no credential): `mfl_players`, `mfl_injuries`, `mfl_nfl_schedule`.

**League** (cookie for a private league): `mfl_league` — read this first, it defines what a
legal lineup is — plus `mfl_rosters`, `mfl_free_agents`, `mfl_league_standings`,
`mfl_schedule`, `mfl_transactions`.

**Scoring**: `mfl_player_scores` (in *this* league's scoring, so comparable across your
roster and the free-agent pool and not comparable to any other league),
`mfl_projected_scores`, `mfl_live_scoring`.

**Yours** (cookie required): `mfl_my_leagues`, `mfl_pending_trades`.

## Writes

Six tools in `myfantasyleague.write`, a group that `*`, `all`, every preset and even
`myfantasyleague.*` deliberately skip:

```
--groups "free,myfantasyleague.*,myfantasyleague.write"
```

| tool | MFL `TYPE` | immediate? |
|---|---|---|
| `mfl_set_lineup` | `lineup` | yes |
| `mfl_add_drop` | `fcfsWaiver` | **yes — no window to cancel** |
| `mfl_waiver_claim` | `waiverRequest` | no, processes at the round |
| `mfl_blind_bid` | `blindBidWaiverRequest` | no, and **spends real budget** if won |
| `mfl_injured_reserve` | `ir` | yes |
| `mfl_trade_response` | `tradeResponse` | accepting is **irreversible** |

Three behaviours worth stating plainly:

- **`STARTERS` is a full replacement.** Anyone omitted is benched. A typo does not error;
  it quietly sits a player down.
- **`REPLACE` is not the default.** Omit it and your claims are *appended* to whatever is
  already queued for that round — which is how you submit the same claim twice.
- **`FRANCHISE_ID` means "act as someone else"** and is commissioner-only. Leaving it unset
  is acting as yourself; setting it is changing another person's team.

### ⚠ Shape status

All six carry `shapes_verified: false`. The *contract* is the vendor's own documentation —
far stronger ground than ESPN or FPL — but no live `200` has been observed from this
codebase yet, because that needs a real league and a real cookie. Always re-read
`mfl_rosters` afterwards.
