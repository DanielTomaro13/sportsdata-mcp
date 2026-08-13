# Fantasy agents — implementation plan

An agent that runs a fantasy team for a whole season: sets lineups, makes transfers,
works waivers, evaluates trades, and escalates what the owner wants to decide.

This is the scoping document. It covers what each platform can do **today**, what a write
plane would require, and what is needed to build it.

---

## The finding that reorders everything

**Yahoo is the only major fantasy platform with a sanctioned, documented write API.**

Everything else means reverse-engineering a private endpoint that can change without
notice and whose terms generally prohibit automated access. Yahoo publishes an OAuth2 API
with `PUT`/`POST` for roster changes, add/drops, waiver claims and trades. It is rate
limited, versioned, and intended to be used this way.

That makes Yahoo the right flagship — not because it is the biggest platform, but because
it is the only one where "agent has full control of a team" is a supported use case rather
than a tolerated one.

Verified: `GET fantasysports.yahooapis.com/fantasy/v2/game/nfl` →
`401 OAuth oauth_problem="unable_to_determine_oauth_type"`. A real OAuth surface.

---

## The autonomy ladder

"Automated" is not one thing. Every platform below is rated against this scale, because
the interesting question is not *can it act* but *how long can it run without you*.

| Level | Behaviour |
|---|---|
| **L0** | Advice only — the agent tells you, you execute |
| **L1** | Proposes each action, you approve, it executes |
| **L2** | Acts within a policy, escalates only the exceptions |
| **L3** | Fully autonomous for a season — reports after the fact |

**L3 is gated by exactly one thing on every platform: how long the credential lives, and
whether it can be renewed without a human.** Everything else — deadlines, decisions,
retries — is solvable in code.

Two things are worth saying plainly before the per-platform ratings:

**L3 is achievable on several platforms. It is not obviously desirable on any of them.**
Chips and trades are season-defining and irreversible; an agent that plays your wildcard
badly in October costs you the season. My recommendation everywhere is **L2 with chips
and trades pinned to `always_ask`**, which is a policy choice, not a technical limit.

**An undocumented write endpoint can change mid-season.** Yahoo and MyFantasyLeague are
versioned and will not. FPL, ESPN and SuperCoach can break on any Tuesday, and the agent
must fail loudly rather than silently skip a deadline.

---

## Platform-by-platform

### 1. Yahoo Fantasy — **sanctioned, read + write** ★ recommended flagship

| | |
|---|---|
| Today in catalogue | **Nothing.** Provider does not exist yet |
| Auth | OAuth2 (client id + secret → refresh token). The engine already has `oauth_refresh` |
| Writes | **Officially supported** |
| Sports | NFL, NBA, MLB, NHL |

**Read endpoints to scope** (`/fantasy/v2/`):

```
users;use_login=1/games                    which games the user plays
users;use_login=1/games/leagues            their leagues
game/{game_key}                            game metadata, stat categories
league/{league_key}/settings                scoring, roster slots, waiver rules
league/{league_key}/standings               standings
league/{league_key}/scoreboard;week=N       matchups
league/{league_key}/players;status=A        available players (free agents)
league/{league_key}/players;status=FA       free agents only
league/{league_key}/transactions            adds, drops, trades
league/{league_key}/draftresults            draft
team/{team_key}/roster;week=N               a roster for a week
team/{team_key}/matchups                    that team's season
player/{player_key}/stats                   player stats
```

**Write endpoints** — the reason this platform leads:

```
PUT  team/{team_key}/roster                 SET LINEUP (starters/bench per position)
POST league/{league_key}/transactions       add, drop, add/drop, waiver claim
POST league/{league_key}/transactions       trade propose / accept / reject
```

#### Automation: **L3 achievable — the only platform where it is uncontroversial**

| | |
|---|---|
| Credential | OAuth2 access token (1 hour) + **refresh token** |
| Renews without a human? | **Yes** — the refresh token mints new access tokens silently |
| Human touches per season | **One**, ever: the initial browser consent |
| Breaks when | You change your Yahoo password, or revoke the app |
| Endpoint stability | Versioned and documented — will not shift mid-season |

**What full automation needs here:** a registered app (client id + secret), one browser
consent, and the refresh token stored locally. The engine's existing `oauth_refresh`
already does the token dance — this is the same mechanism `tab` and other providers use
today.

**Verdict:** build this first. It is the only platform where an autonomous agent is
operating within the intended use of the API, and the only one where L3 needs no
compromise.

---

### 2. FPL — **best reverse-engineered target**

| | |
|---|---|
| Today in catalogue | **16 tools**, complete read coverage |
| Auth | Session cookie (`pl_profile`, `sessionid`) |
| Writes | Undocumented but clean REST |
| Sport | Premier League only |

**Already capable today** — the entire decision surface is public:
`fpl_players` (price, form, ownership, xG/xA), `fpl_player_detail` (gameweek history,
fixture difficulty), `fpl_fixtures`, `fpl_gameweeks` (**deadlines**), `fpl_teams`
(strength ratings), `fpl_set_piece_notes`, `fpl_live_gameweek`, `fpl_manager*` (any
manager's squad, history, picks), leagues. Only `fpl_my_team` needs the cookie.

**Write endpoints to scope:**

```
POST /api/transfers/          {entry, event, chip, transfers:[{element_in, element_out,
                               purchase_price, selling_price}]}
POST /api/my-team/{id}/       {chip, picks:[{element, position, is_captain,
                               is_vice_captain}]}   ← lineup + captain
```
Chips (wildcard, free hit, bench boost, triple captain) ride the `chip` field on those
same calls rather than having their own endpoint.

**What is still unknown:** the exact CSRF mechanism and required headers on the write
calls. That is one browser capture away (see *What I need*).

#### Automation: **L2 comfortably; L3 only if you store credentials locally**

| | |
|---|---|
| Credential | `pl_profile` + `sessionid` cookies |
| Renews without a human? | **Only** by replaying the login POST |
| Human touches per season | 0 if auto-relogin, otherwise 1 per session expiry |
| Breaks when | Session expires, or FPL adds MFA/CAPTCHA to login |
| Endpoint stability | Undocumented — could change without notice |

**The one genuine unknown in this whole plan: how long an FPL session lasts.** It is a
Django backend, so the default would be two weeks — which across a 38-gameweek season
means roughly 19 manual re-auths, i.e. L2 with a fortnightly chore. If it is season-long,
L2 is effortless. *This is measurable in one login and is the single highest-value thing
to find out.*

**What full automation (L3) needs here:** FPL is the one platform with a plain login
`POST`, so re-auth can be scripted. That means storing your FPL password **in your own OS
keychain on your own machine**, which the agents platform's `secrets.py` already supports
(env → 0600 file → keychain). That is a legitimate local pattern — it is not the same as
handing a password to a third party — but it *is* a password at rest, and it is your call
whether a fantasy team is worth that. If FPL ever adds a CAPTCHA to login, this route
closes and the platform drops to L2 permanently.

**Verdict:** Phase 1 for writes. One sport, 38 hard deadlines, a small action space —
the cleanest place to prove the agent loop.

---

### 3. ESPN Fantasy — **broadest reads, feasible writes**

| | |
|---|---|
| Today in catalogue | **27 tools** (6 public, 21 behind the cookie) |
| Auth | `espn_s2` + `SWID` cookies (Disney OneID — no scripted password login) |
| Writes | Undocumented, well-trodden |
| Sports | NFL, NBA, MLB, NHL, WNBA |

**Already capable today** — and this is the deepest read coverage of any platform here:
league settings, rosters, standings, matchups, draft, completed *and* pending
transactions, box scores, live scoring, positional ratings, player cards with
projections, plus the undocumented `allon` mega-view. **Public leagues need no cookie at
all** (verified 200 on a public league).

**Write endpoint to scope:**

```
POST .../seasons/{year}/segments/0/leagues/{id}/transactions/
     type: LINEUP | WAIVER | FREEAGENT | TRADE_PROPOSE | TRADE_ACCEPT | TRADE_REJECT
```

#### Automation: **L2 for a full season, essentially unattended**

| | |
|---|---|
| Credential | `espn_s2` + `SWID` cookies |
| Renews without a human? | **No** — Disney OneID has no scriptable login |
| Human touches per season | **~1** — these cookies are long-lived (commonly ~1 year) |
| Breaks when | You log out everywhere, change your password, or the cookie ages out |
| Endpoint stability | Undocumented, but stable for years in practice |

**What full automation needs here:** paste the two cookies once, and set a **staleness
alarm** — the agent should verify the cookie works *days before* a deadline, not at the
deadline, so a silent expiry gets caught with time to fix it. That check is cheap and it
is the difference between a missed week and a minor chore.

**Verdict:** Phase 2. Multi-sport reach makes it the highest-value target after FPL, the
read side is already done, and a once-a-year cookie paste is the lightest ongoing burden
of any platform here.

---

### 4. Sleeper — **perfect reads, hardest writes**

| | |
|---|---|
| Today in catalogue | **14 tools**, everything public |
| Auth | None for reads |
| Writes | **No public API.** The app uses a private GraphQL endpoint |
| Sports | NFL, NBA |

**Already capable today** — verified end-to-end on a real 12-team league with zero
credentials: rosters, users, matchups, **439 transactions**, drafts, playoff brackets,
traded picks, trending adds/drops.

**Write reality:** `sleeper.com/graphql` returns 400 to an unauthenticated POST. Writes
require a bearer token issued to the mobile app and a schema that is neither published
nor stable.

#### Automation: **L0 permanently — but the L0 is flawless and free**

| | |
|---|---|
| Credential | **None at all** for reads |
| Renews without a human? | Nothing to renew |
| Human touches per season | **Zero** for analysis; every action is manual |
| Breaks when | Never — there is no session to expire |

The mirror image of every other platform: the *advice* side is perfectly autonomous and
can never break on a credential, while the *execution* side is closed. An agent can watch
your Sleeper league all season, tell you exactly what to do and when, and never once ask
you for anything — it simply cannot press the button.

**What full automation would need:** a bearer token issued to the mobile app plus an
unpublished GraphQL schema. Not worth it.

**Verdict:** read-only, indefinitely. Superb for analysis; recommend not attempting
execution.

---

### 5. SuperCoach — **thin reads, hardest auth**

| | |
|---|---|
| Today in catalogue | **6 tools** |
| Auth | News Corp SSO (multi-step browser flow) |
| Writes | Undocumented |
| Sports | AFL, NRL |

**Already capable today:** the player feed (price, scores, ownership, status per round),
fixtures, teams, competition state, public leagues.

**Missing reads to scope:** the user's own team, their leagues, trade history, captain
selections. These sit behind the SSO.

#### Automation: **L1 realistically; L2 unproven**

| | |
|---|---|
| Credential | News Corp SSO session |
| Renews without a human? | **No** — multi-step SSO |
| Human touches per season | Unknown; likely the most of any platform |
| Breaks when | Session expires (SSO sessions are typically shortest) |
| Endpoint stability | Undocumented |

**What full automation needs here:** the session lifetime measured first. If SSO sessions
are short — which is typical — this platform cannot exceed L1 without a browser-driving
workaround that I would not recommend building.

**Verdict:** Phase 4 at earliest. Highest effort-to-value ratio of the set. Worth doing
only because it is the AU-facing game and nothing else covers it.

---

### 6. MyFantasyLeague — **sanctioned writes, niche** ★ worth adding

| | |
|---|---|
| Today in catalogue | Nothing |
| Auth | API key |
| Writes | **Officially supported** via `import` |

Verified: `export?TYPE=players&JSON=1` returns **195 KB** of player data with no auth.

```
export?TYPE=league|rosters|players|transactions|standings|liveScoring|playerScores
import?TYPE=lineup|waiverRequest|tradeProposal|import       ← sanctioned writes
```

#### Automation: **L3 achievable — an API key does not expire**

| | |
|---|---|
| Credential | API key |
| Renews without a human? | Nothing to renew |
| Human touches per season | **Zero** after setup |
| Endpoint stability | Documented and versioned by year |

**Verdict:** small user base, but a *documented* write API, a long-lived key and a cheap
provider to add. The second-best autonomy story after Yahoo.

---

### 7. Fantrax — **reads only**

Verified: `fxea/general/getLeagues` → `200 {}`, `getTeamRosters` → clean
`INVALID_LEAGUE_ID` error. A real external API.

```
fxea/general/getLeagues | getTeamRosters | getStandings | getDraftResults
                        | getPlayerIds  | getADP
```

**Verdict:** cheap read-only provider. No public write surface found.

---

### Ruled out

| Platform | Why |
|---|---|
| **NFL.com Fantasy** | API returns 404; retired |
| **CBS Fantasy** | API exists but requires a partner key not issued to individuals |
| **Ottoneu** | Cloudflare challenge on the API path |
| **DraftKings / FanDuel DFS** | Lobby endpoints 403 to non-browser clients; DFS entry automation is explicitly prohibited and financially risky |

---

## Summary table

| Platform | Read tools | Write API | Credential | **Autonomy** | Human touches / season | Priority |
|---|---:|---|---|---|---|---|
| **Yahoo** | 0 | ✅ sanctioned | OAuth2 refresh | **L3** | **1 ever** | **1st** |
| **MyFantasyLeague** | 0 | ✅ sanctioned | API key | **L3** | **0** | 4th |
| **ESPN** | 27 | ⚠️ undocumented | Long-lived cookies | **L2** | ~1 | **3rd** |
| **FPL** | 16 | ⚠️ undocumented | Session cookie | **L2** (L3 if stored creds) | 0–19 ⚠️ | **2nd** |
| **SuperCoach** | 6 | ⚠️ SSO | SSO session | **L1** | many | 6th |
| **Sleeper** | 14 | ❌ private GraphQL | none | **L0** advice, perfect | **0** | read-only |
| **Fantrax** | 0 | ❌ none found | — | **L0** | 0 | 5th |

⚠️ The FPL range is the plan's one big unknown — it depends entirely on session lifetime,
which one login measures.

**Read that table as: Yahoo and MyFantasyLeague are the only platforms where "set it up
once and forget it for a season" is genuinely true.** ESPN comes close on a yearly cookie.
FPL is excellent *if* sessions are long. Sleeper is the odd one — zero maintenance
forever, but it can only ever advise.

### What full autonomy requires regardless of platform

Credentials are the gate, but four other things separate "it works when I watch it" from
"it ran the season":

**A staleness alarm, not a deadline failure.** The agent must verify its credential works
**days before** a deadline, not at it. A cookie that expired on Tuesday should be a
Tuesday chore, not a Saturday disaster. This is cheap and it is the single highest-value
piece of reliability engineering in the whole build.

**Read-back on every write.** Fire the transfer, then re-read the squad and confirm it
happened. Undocumented endpoints can accept a request and do nothing; a `200` is not
proof.

**Idempotency keys.** A retried waiver claim that double-spends budget is the worst bug
available here.

**Escalate failures louder than successes.** A silent failure at 12:55 for a 13:00 lock
costs a week. Successes can be a weekly digest; failures should page.

Get those four right and the difference between L2 and L3 is a policy setting, not an
engineering problem.


---

## Architecture

Four layers. Three already exist in `sportsdata-agents`.

### 1. Write plane in `sportsdata-mcp` *(new)*

746 of 747 tools are `GET` with `readOnlyHint: true`. Writes break that invariant, so
they must be visibly different:

- a separate `*.write` group, **excluded from `free` and from `all`**
- `readOnlyHint: false`, `idempotentHint: false`
- refuse to fire without an explicit per-provider opt-in env var
- every write requires an idempotency key and reads back to confirm

### 2. Policy engine *(new — the user's "settings")*

```yaml
league: fpl:1234567
  lineup:      auto              # set optimal XI before each deadline
  captain:     auto
  transfers:   auto_if_free      # use a free transfer; never take a -4 hit
  chips:       always_ask        # wildcard/FH/BB/TC are season-defining
  waivers:     auto_under        # claim if bid ≤ 15% of remaining budget
  trades:      always_ask        # never fire; route to me
  drops:       never
  quiet_hours: 23:00-07:00
  max_actions_per_week: 3
```

### 3. Approval routing *(exists)* — `observability/notify.py`, ntfy + Slack are wired.
A proposal becomes a notification with an expiry: *"Transfer Salah → Saka, cost £0.2m,
uses your free transfer. Expires in 4h."* Approve or it lapses.

### 4. Scheduling *(exists)* — `app/supervisor.py` already runs a conductor loop against a
cron driver. Deadlines come from `fpl_gameweeks`, `espnfantasy_status`, `sleeper_state`.

### Cross-cutting requirements

**Plan-then-act.** Every action produces a diff, logged, before it fires.

**Idempotency.** A retried waiver claim that double-spends budget is the worst available
bug. Client-side key plus read-back on every write.

**Deadline awareness.** The agent must act *before* lock, driven by real fixture times.

**Failure escalates louder than success.** A lineup that fails to set at 12:55 for a
13:00 lock must page immediately.

**Audit log.** Every action, its inputs, its diff and its outcome — reversible where the
platform allows.

---

## Phasing

**Phase 0 — recommender, no writes, no credentials.** All four current platforms.
"Here is your XI, captain, transfer, and why." Runs against real teams using public
identifiers only. *This is the phase that answers the question that matters: are the
agent's decisions actually better than the owner's?*

**Phase 1 — Yahoo provider + sanctioned writes.** Build the provider, then lineup writes
behind approval. The only platform where this is a supported use case.

**Phase 2 — FPL writes.** Transfers and lineup via the session cookie.

**Phase 3 — ESPN writes.** Multi-sport reach; read side already complete.

**Phase 4 — MyFantasyLeague** (sanctioned) and **Fantrax** (read-only).

**Never — Sleeper writes.** Read-only by decision, not by omission.

---

## What is needed to proceed

### Non-sensitive identifiers (public, safe to share)

| Platform | What | Where to find it |
|---|---|---|
| FPL | Manager id | The number in your team URL |
| FPL | **Session lifetime** ⚠️ | After logging in, check the `sessionid` cookie's Expires in devtools — this decides FPL's autonomy ceiling |
| Sleeper | Username | Your Sleeper handle |
| ESPN | League id + is it private? | The `leagueId` in the URL |
| SuperCoach | Team id | Your team URL |

### For the Yahoo provider

Register an app at `developer.yahoo.com/apps/create` → client id + secret, into your own
environment as `YAHOO_CLIENT_ID` / `YAHOO_CLIENT_SECRET`. The engine's existing
`oauth_refresh` handles the token dance.

### For write payloads — the browser-capture technique

To learn a write's exact shape without sharing any credential:

1. Log in, open devtools → **Network**
2. Perform the action manually once (make a transfer, set a lineup)
3. Right-click the request → **Copy as cURL**
4. **Delete the `Cookie`, `Authorization` and `X-CSRF` header values** before sharing

That yields the URL, method, headers and JSON body — everything needed to build the
write tool — with nothing sensitive in it. `scripts/probe-fantasy-auth.py` does the same
job for reads.

### Not needed, ever

Account passwords. Every read above works without one, and every write works from a
session cookie or OAuth token that the owner places in their own environment. A password
is both more dangerous and less useful than the token it would be exchanged for.
