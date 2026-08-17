# Yahoo Fantasy Sports (`yahoo`) — sanctioned reads **and writes**

**24 tools · approval required · shapes unverified**

NFL, NBA, MLB and NHL. The only major fantasy platform with an **officially supported
write API** — set a lineup, add/drop, claim waivers, propose trades — rather than a
reverse-engineered one.

## ⚠️ You cannot use this yet, and neither can anyone else

**Access is approval-gated.** Registering an app yourself is not enough. Apply at
[sports.yahoo.com/developer](https://sports.yahoo.com/developer):

> 1. **Application submission** — your organization, product and use cases
> 2. **Application review** — "we'll reach out with any follow-up questions"
> 3. **Access** — "**if you're approved**, we'll follow up with next steps"

Verified 2026-08-13 on two separately registered apps — Yahoo rejects the fantasy scopes
outright until the app is approved:

```
scope=(none)   302 → consent page reached
scope=fspt-r   error=invalid_scope
scope=fspt-w   error=invalid_scope
```

An app cannot request a scope its registration does not carry, and Yahoo attaches the
Fantasy Sports permission **on approval**. Until then every endpoint returns
`401 oauth_problem="additional_authorization_required"` even with a perfectly valid
token.

**This provider is complete and waiting.** When approval lands, three environment
variables switch it on — no further build.

## What approval commits you to

Two of these are product constraints, not paperwork:

- **Attribution is mandatory** — "Fantasy data provided by Yahoo Fantasy" must appear in
  your product with the official logo, unmodified (no recolouring, rotation, effects, or
  combination with other marks).
- **"Developers may not modify, reverse engineer, decompile, or otherwise alter the API
  or separate its underlying data."**
- One developer account; no automated account creation.
- Usage is monitored and throttled if excessive.

An agent that autonomously manages a team is exactly the use case a reviewer will look
at hardest. Describe it honestly in the application.

## Setup, once approved

```bash
python3 scripts/yahoo-oauth-setup.py
```

It walks the OAuth dance and **preflights the scope check in a single request**, so an
unapproved app is caught before you walk a consent flow that would succeed and then 401
on everything. It ends by printing:

```bash
export YAHOO_CLIENT_ID=...
export YAHOO_CLIENT_SECRET=...
export YAHOO_REFRESH_TOKEN=...
```

The refresh token is the durable one — the engine mints access tokens silently from it,
which is why Yahoo is the only platform where an agent can run a **whole season on one
human interaction**.

## The JSON is unusual, and this is the main thing to know

Yahoo serves XML by default. `format=json` (already set on every tool) returns a
structure that mixes arrays with **numeric-keyed objects** and interleaves metadata:

```json
{"fantasy_content": {"users": {"0": {"user": [
    {"guid": "..."},
    {"games": {"0": {"game": [...]}, "count": 1}}
]}, "count": 1}}}
```

Two habits will save you:

- **`users`, `games`, `teams`, `players` are OBJECTS keyed `"0"`, `"1"`, … with a
  `count` sibling** — not lists. Iterating them as arrays fails.
- **A resource is often a two-element ARRAY** of `[metadata, {sub-resource}]` rather than
  one merged object. `team` goes further and nests an array of single-key objects.

Walk it defensively. Do not assume list semantics anywhere.

## Key formats

Every id is a compound string, and a malformed one is the usual 400:

| Key | Format | Example |
|---|---|---|
| `game_key` | code or numeric | `nfl`, `449` |
| `league_key` | `{game}.l.{id}` | `449.l.12345` |
| `team_key` | `{league}.t.{id}` | `449.l.12345.t.3` |
| `player_key` | `{game}.p.{id}` | `449.p.31883` |

A bare code (`nfl`) means the **current** season.

## Tools

### Discovery — start here

| Tool | What it gives you |
|---|---|
| `yahoo_my_games` | Which games you play — the `game_key` everything needs |
| `yahoo_my_leagues` | Your leagues → `league_key` |
| `yahoo_my_teams` | Your teams → `team_key`, which every write needs |

### Reference

| Tool | What it gives you |
|---|---|
| `yahoo_game` | Season metadata, whether the game is over |
| `yahoo_game_stat_categories` | Stat ids → names. Without it, stats are bare numbers |
| `yahoo_game_roster_positions` | Legal slots and which are starting positions |

### League

| Tool | What it gives you |
|---|---|
| `yahoo_league` | Name, size, scoring type, **current week** |
| `yahoo_league_settings` | Roster slots, scoring weights, waiver type, trade deadline |
| `yahoo_league_standings` | Records, points for/against, streak |
| `yahoo_league_scoreboard` | A week's matchups with actual **and projected** points |
| `yahoo_league_teams` | Every team with `faab_balance` and `waiver_priority` |
| `yahoo_league_players` | The player pool by availability (25 per page) |
| `yahoo_league_transactions` | Adds, drops, trades — **with winning FAAB bids** |
| `yahoo_league_draft` | Every pick in order |

### Team

| Tool | What it gives you |
|---|---|
| `yahoo_team` | Waiver priority, FAAB balance, moves used |
| `yahoo_team_roster` | A week's lineup, slot by slot, plus `is_editable` |
| `yahoo_team_matchups` | The team's whole season |
| `yahoo_team_stats` | Aggregated stats by season or week |

### Players

| Tool | What it gives you |
|---|---|
| `yahoo_player_stats` | Stats for one or many players (batch the keys) |
| `yahoo_player_ownership` | Rostered, on waivers, or free — per league |

### Writes — opt-in, and deliberately hard to enable

| Tool | What it does |
|---|---|
| `yahoo_set_lineup` | **PUT** a full roster: every player's slot for a week |
| `yahoo_add_drop` | **POST** an add, drop, add/drop, or FAAB waiver claim |
| `yahoo_propose_trade` | **POST** a trade proposal, or accept/reject/cancel one |

## How writes are gated

Three deliberate frictions, because these are the first tools in the catalogue that
change something on someone's account:

**1. A wildcard never enables them.** `*`, `all`, any preset, and even the provider glob
`yahoo.*` all skip `.write`. Only the exact group name works:

```bash
sportsdata-mcp serve --groups "free,yahoo.*,yahoo.write"
```

**2. They do not claim to be read-only.** Every other tool carries
`readOnlyHint: true`, which tells a client it may call freely. These carry
`readOnlyHint: false` and `destructiveHint: true`.

**3. The body is XML, verbatim.** Yahoo accepts no other format on writes. Each tool's
description carries the exact template; what you write is what is sent.

### Three things that will bite you on writes

**A lineup write must include the ENTIRE roster**, not just the players moving, and every
`position` must be one of that player's `eligible_positions`. Read `yahoo_team_roster`
first and check **`is_editable`** — a locked week rejects the write.

**A waiver claim succeeds as PENDING, not done.** It processes on the league's waiver
run, so the roster will not change immediately. Treating the 201 as completion will make
an agent think it has a player it does not have.

**A trade proposal is an offer.** It needs the other manager, and often a league review
period (`trade_ratify_type`). Success means "offered", never "done" — and once ratified
it is irreversible, which is why the recommendation is to keep trades on `always_ask`.

**Always read back.** A 200 is not proof the intended change happened.

## See also

- [docs/FANTASY-AGENTS-PLAN.md](../docs/FANTASY-AGENTS-PLAN.md) — where Yahoo sits among the platforms
- [FPL.md](FPL.md) — buildable today, no gatekeeper
- [ESPNFantasy.md](ESPNFantasy.md), [Sleeper.md](Sleeper.md)
