# ESPN Fantasy API Documentation

Unofficial reference for ESPN's **fantasy** v3 API — the platform behind fantasy
football/baseball/basketball/hockey/WNBA leagues. Probed live 2026-07-02 against
public league `1234` (season 2018) and the 2025/2026 game-level endpoints.

> **This is not the `espn` provider.** [`ESPN.md`](ESPN.md) covers `site.api.espn.com` /
> `sports.core.api.espn.com` — real-world scoreboards, teams, athletes, news. **This**
> provider reads *a user's own fantasy league*: settings, teams, rosters, matchups,
> draft, transactions, free agents. Different hosts, different id space, different auth.
> They compose well: fantasy rosters here, real-world injury/box-score context there.

## Contents

- [Hosts](#hosts)
- [The five games](#the-five-games)
- [Auth — public vs private leagues](#auth--public-vs-private-leagues)
- [The view model (read this first)](#the-view-model-read-this-first)
- [The id model](#the-id-model)
- [Tools](#tools)
- [View reference](#view-reference)
- [`x-fantasy-filter` cookbook](#x-fantasy-filter-cookbook)
- [Decoder tables](#decoder-tables)
- [Error semantics & gotchas](#error-semantics--gotchas)
- [Cross-provider comparison](#cross-provider-comparison)
- [Not modelled](#not-modelled)

## Hosts

| Host | Role |
|---|---|
| `lm-api-reads.fantasy.espn.com/apis/v3/games` | Everything league- and game-scoped. **The current host** — ESPN moved reads here around April 2024; the older `fantasy.espn.com/apis/v3/games` still answers but is not what the site uses. |
| `site.api.espn.com/apis/fantasy/v3/games` | Player news only (`espnfantasy_player_news`). Different host, different path prefix (`apis/fantasy/v3`, not `apis/v3`). |

No API key exists for either. Access control is entirely cookie-based (below).

## The five games

The game code is a **path segment on every call** (`game` param, default `ffl`).
Verified live from `espnfantasy_games`:

| Code | Game | Pro sport | `gameId` |
|---|---|---|---|
| `ffl` | Fantasy Football | NFL | 1 |
| `flb` | Fantasy Baseball | MLB | 2 |
| `fba` | Fantasy Basketball | NBA | 3 |
| `fhl` | Fantasy Hockey | NHL | 4 |
| `wfba` | Fantasy Women's Basketball | WNBA | 5 |

Every league tool works for all five — the response shape is the same; only the stat
ids and position ids differ per sport. `espnfantasy_games` reports each game's
**current** `seasonId` and `currentScoringPeriod.id`, which is how you resolve "this
week" without hardcoding a date.

## Auth — public vs private leagues

**Public leagues need nothing.** Every tool works anonymously against a public league.

**Private leagues need two browser cookies**, `espn_s2` and `SWID`. Set them as one
cookie string in `ESPN_FANTASY_COOKIE`:

```bash
export ESPN_FANTASY_COOKIE='espn_s2=AEB7%2Fabc...; SWID={1A2B3C4D-5E6F-7890-ABCD-EF1234567890}'
```

To get them: sign in at `fantasy.espn.com`, open DevTools → Application → Cookies →
`https://fantasy.espn.com`, and copy the `espn_s2` and `SWID` values. Keep the braces
on `SWID`. These are **session credentials for your ESPN account** — treat them like a
password: they go in the environment, never in a spec, config file, or commit (this is
the same rule as `DATAGOLF_KEY`). Rotate by logging out and back in.

The `private` auth key is declared `optional: true`, so when `ESPN_FANTASY_COOKIE` is
unset the request still goes out — anonymously. That means **one set of tools serves
both tiers**: public leagues work out of the box, and setting the env var silently
upgrades the same tools to reach your private leagues. A private league read without
the cookie returns **HTTP 401**.

> ESPN removed username/password auth (it now requires Google reCAPTCHA), so cookies
> are the only mechanism. There is no refresh flow — when the session expires, re-copy.

## The view model (read this first)

Nearly every league endpoint is **the same URL**. What comes back is decided by the
`view` query parameter:

```
/apis/v3/games/{game}/seasons/{seasonId}/segments/0/leagues/{leagueId}?view=mTeam&view=mRoster
```

Three rules, all verified live:

1. **Views are additive.** Each one grafts more onto the same league envelope —
   `mTeam` fills in `teams[].record`/`name`, `mRoster` adds `teams[].roster`,
   `mMatchup` adds a top-level `schedule`.
2. **Views MUST be repeated params, never comma-joined.** `?view=mTeam&view=mRoster`
   returns 727 KB; `?view=mTeam,mRoster` returns the 1.7 KB bare skeleton — **with
   HTTP 200 and no error**. A comma-joined list looks exactly like an empty league.
   Every `view` param in this provider is `string_list` (the engine emits repeated
   params) precisely to make this un-gettable-wrong.
3. **Unknown views are ignored silently.** `?view=zzzBogus` is a 200 with the
   skeleton. There is no view-validation error and no way to enumerate views from the
   API — the list below was established by sweeping candidates and diffing responses.

Because of rule 2 and 3, the failure mode for a wrong view is *quiet emptiness*. If a
tool returns a suspiciously small payload with no `teams[].name`, the view didn't take.

## The id model

```
espnfantasy_games                        → currentSeasonId, currentScoringPeriod.id
   └─ seasonId + your leagueId (from the fantasy site URL: ?leagueId=NNNN)
        ├─ espnfantasy_league_settings   → roster slots, scoring items
        ├─ espnfantasy_teams             → teams[].id  (fantasy team ids, 1..N)
        │    └─ espnfantasy_rosters      → roster entries → playerId
        │         └─ espnfantasy_player_card / espnfantasy_player_news  (playerId)
        ├─ espnfantasy_matchups          → schedule[].matchupPeriodId
        │    └─ espnfantasy_boxscore     (scoringPeriodId) → per-player points
        └─ espnfantasy_player_info       → the free-agent pool (filter by status)
```

**`scoringPeriodId` vs `matchupPeriodId`** — the distinction that trips everyone up:

- `scoringPeriodId` is the atomic scoring unit: an **NFL week** for `ffl`, a **single
  day** for the daily sports (`flb`/`fba`/`fhl`/`wfba` — note the 2026 baseball season
  reports `currentScoringPeriod.id: 128`, i.e. day 128, not week 128).
- `matchupPeriodId` is the **head-to-head contest**. In football they're 1:1. In the
  daily sports one matchup period spans a week of scoring periods.

Tools that score a week (`espnfantasy_boxscore`, `espnfantasy_transactions`,
`espnfantasy_positional_ratings`) take `scoringPeriodId`. `schedule[]` entries are keyed
by `matchupPeriodId`.

**Seasons before 2018** live at a different path — see `espnfantasy_league_history`.

## Tools

### `espnfantasy.reference` (6) — no league id needed

| Tool | Path / view | Capability | Notes |
|---|---|---|---|
| `espnfantasy_games` | `/` | `ref.seasons` | **Start here.** All 5 games + current season & scoring period. Top-level array. |
| `espnfantasy_season` | `/{game}/seasons/{id}` | `ref.seasons` | One season's status and dates. |
| `espnfantasy_pro_teams` | `?view=proTeamSchedules_wl` | `ref.teams`, `sport.fixtures_by_date` | 33 NFL teams with **bye weeks** and games per scoring period. |
| `espnfantasy_players` | `/players?view=players_wl` | `ref.players` | Player universe. **Defaults to 50** — filter to widen. |
| `espnfantasy_league_defaults` | `/leaguedefaults/{scoringTypeId}` | `fantasy.league_settings` | ESPN's stock presets: `1`=Standard, `3`=PPR, `5`=All-Play PPR, `6`=Knockout. |
| `espnfantasy_player_news` | `site.api` `/news/players` | `content.news` | Injury/usage blurbs for one `playerId`. |

### `espnfantasy.league` (14) — a specific league

| Tool | View(s) | Capability | Notes |
|---|---|---|---|
| `espnfantasy_league` | *any* | `fantasy.league_settings` | Escape hatch — pass any view combination, or batch several in one round trip. |
| `espnfantasy_league_settings` | `mSettings` | `fantasy.league_settings` | Scoring items, roster slots, playoff/waiver/keeper/trade rules. |
| `espnfantasy_teams` | `mTeam` | `ref.teams`, `stats.ladder` | Records, points for/against, seeds, owners. |
| `espnfantasy_rosters` | `mRoster` | `fantasy.rosters` | Who holds whom. **Large** (~900 KB for 10 teams). |
| `espnfantasy_standings` | `mStandings`+`mTeam` | `stats.ladder` | `mStandings` alone has no names — `mTeam` carries them. |
| `espnfantasy_matchups` | `mMatchup` | `fantasy.matchups` | Full season schedule with totals. |
| `espnfantasy_draft` | `mDraftDetail` | `sport.draft` | Every pick: round, team, player, keeper flag, auction bid. |
| `espnfantasy_transactions` | `mTransactions2` | `sport.transactions` | **`scoringPeriodId` required** — without it there is no `transactions` key. |
| `espnfantasy_pending_transactions` | `mPendingTransactions` | `sport.transactions` | Key is *absent* (not empty) when nothing is pending. |
| `espnfantasy_status` | `mStatus` | — | Current matchup period, `previousSeasons`, waiver dates. |
| `espnfantasy_nav` | `mNav` | — | Cheap league header before a heavy call. |
| `espnfantasy_everything` | `allon` | `sport.season_summary` | **Undocumented mega-view** — everything in one ~4.5 MB response. |
| `espnfantasy_communication` | `/communication/` | `content.news` | Message board / activity. 404s when the league never used it. |
| `espnfantasy_league_history` | `/leagueHistory/{id}` | `ref.seasons` | Pre-2018 + cross-season. Returns an **array**. |

### `espnfantasy.scoring` (5)

| Tool | View(s) | Capability | Notes |
|---|---|---|---|
| `espnfantasy_boxscore` | `mBoxscore`+`mMatchupScore` | `sport.match_boxscore`, `stats.player_match` | The start/sit post-mortem: lineups with actual **and** projected points. `scoringPeriodId` required. |
| `espnfantasy_matchup_score` | `mMatchupScore` | `fantasy.matchups` | Totals only — ~12× smaller than the box score. |
| `espnfantasy_scoreboard` | `mScoreboard`+`mMatchupScore` | `sport.match_score` | Matchup totals + the pro-game state behind them. |
| `espnfantasy_live_scoring` | `mLiveScoring`+`mMatchupScore` | `sport.match_score` | `*Live` fields populate only while pro games are in progress. |
| `espnfantasy_positional_ratings` | `mPositionalRatings` | `stats.advanced_metrics` | Points allowed by each defence per position. **In-season only** (see gotchas). |

### `espnfantasy.players` (2)

| Tool | View | Capability | Notes |
|---|---|---|---|
| `espnfantasy_player_info` | `kona_player_info` | `fantasy.free_agents`, `stats.fantasy_projections`, `sport.injuries` | **The waiver-wire tool.** Filter by status for free agents. |
| `espnfantasy_player_card` | `kona_playercard` | `stats.player_season`, `stats.player_game_log`, `stats.fantasy_projections` | Deep per-player splits; **requires** a filter naming the player ids. |

## View reference

Established by sweeping candidate views against a live league and diffing the
responses. Sizes are for a 10-team 2018 football league.

### Views that work

| View | Adds | Size | Used by |
|---|---|---|---|
| `mTeam` | `teams[]` ← name, record, points, seeds, owners | 15 KB | `espnfantasy_teams` |
| `mRoster` | `teams[].roster.entries[]` | 632 KB | `espnfantasy_rosters` |
| `mMatchup` | `schedule[]` (full season) | 174 KB | `espnfantasy_matchups` |
| `mMatchupScore` | `schedule[]` totals only | 28 KB | `espnfantasy_matchup_score` |
| `mSettings` | `settings` (scoring, roster, rules) | 8 KB | `espnfantasy_league_settings` |
| `mStandings` | `schedule` + standings records | 11 KB | `espnfantasy_standings` |
| `mBoxscore` | `schedule[].home.rosterForCurrentScoringPeriod` | 84 KB | `espnfantasy_boxscore` |
| `mScoreboard` | `schedule[]` + pro-game state | 91 KB | `espnfantasy_scoreboard` |
| `mSchedule` | schedule scaffolding | 1 KB | — |
| `mDraftDetail` | `draftDetail.picks[]` | 49 KB | `espnfantasy_draft` |
| `mTransactions2` | `transactions[]` (needs `scoringPeriodId`) | 7 KB | `espnfantasy_transactions` |
| `mPendingTransactions` | `pendingTransactions[]` when any exist | — | `espnfantasy_pending_transactions` |
| `mPositionalRatings` | `positionAgainstOpponent` (in-season only) | — | `espnfantasy_positional_ratings` |
| `mLiveScoring` | live point totals | 3 KB | `espnfantasy_live_scoring` |
| `mNav` | minimal league header | 3 KB | `espnfantasy_nav` |
| `mStatus` | `status` block | 1 KB | `espnfantasy_status` |
| `kona_player_info` | `players[]` + ownership/ratings | 97 KB | `espnfantasy_player_info` |
| `kona_playercard` | `players[]` + deep stat splits | 127 KB | `espnfantasy_player_card` |
| `allon` | **everything** (see below) | 4.05 MB | `espnfantasy_everything` |
| `players_wl` | game-level player universe | — | `espnfantasy_players` |
| `proTeamSchedules_wl` | game-level pro teams + schedule | 109 KB | `espnfantasy_pro_teams` |
| `kona_league_communication` / `kona_league_messageboard` | message board (on `/communication/` only) | — | `espnfantasy_communication` |

**`allon`** is not in ESPN's client, the community JS docs, or the Python library — it
was found by sweep. It returns `settings`, `status`, `teams`, `members`, `schedule`,
`draftDetail`, `players`, `playersHighlighted`, `creationInfo`, `lastUpdateInfo` and
`lastAccessInfo` in one response. Genuinely useful for a one-shot league snapshot;
genuinely expensive (~4.5 MB) — prefer a targeted tool for anything routine.

### Views that do nothing

Silently ignored (200 + bare skeleton), despite appearing in blog posts and issue
threads: `mRosterSettings`, `mTeamsForWeek`, `player_wl`, `mSecondaryMatchupScore`,
`mLiveScoringDetail`, `mNewspaper`, `mDraftDetailForLM`, `mPlayerHistory`,
`mStandingsRankings`, `mLeagueHistory`, `mLeagueSettings`. Don't reach for them —
they're indistinguishable from a typo.

## `x-fantasy-filter` cookbook

Several endpoints take a JSON filter in the `x-fantasy-filter` header (the
`fantasy_filter` param — pass a plain object, the engine serialises it).

> **The nesting differs by endpoint**, which is the single most common filter mistake:
>
> - **Game-level** `espnfantasy_players` → filter keys sit at the **root**:
>   `{"filterActive": {"value": true}}`
> - **League-level** `kona_*` views → everything nests under an **entity key**:
>   `{"players": {...}}`, `{"transactions": {...}}`, `{"schedule": {...}}`, `{"topics": {...}}`
>
> Getting this wrong doesn't error — the filter is ignored and you get the unfiltered
> set (verified: a root-level `limit` on the league path returned all 2,876 players).

**A `limit` must be paired with a sort.** Otherwise the API returns HTTP 400 with a
genuinely helpful body:

```json
{"messages":["Filter: Limit request must be accompanied by a sort"],
 "details":[{"type":"FILTER_LIMIT_MISSING_SORT"}]}
```

Top free agents by ownership (`espnfantasy_player_info`):

```json
{"players": {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
             "limit": 50,
             "sortPercOwned": {"sortPriority": 1, "sortAsc": false}}}
```

Free agents at one position — add `filterSlotIds` (ids from the
[lineup-slot table](#lineup-slot--position-ids)), e.g. RB only:

```json
{"players": {"filterStatus": {"value": ["FREEAGENT"]},
             "filterSlotIds": {"value": [2]},
             "limit": 25,
             "sortPercOwned": {"sortPriority": 1, "sortAsc": false}}}
```

One player's full splits (`espnfantasy_player_card`) — `additionalValue` takes
`"00"+season` for actuals and `"10"+season` for projections:

```json
{"players": {"filterIds": {"value": [3139477]},
             "filterStatsForTopScoringPeriodIds": {"value": 16,
                                                   "additionalValue": ["002025", "102025"]}}}
```

Only trades and waivers (`espnfantasy_transactions`):

```json
{"transactions": {"filterType": {"value": ["TRADE_ACCEPTED", "WAIVER", "FREEAGENT"]}}}
```

Activity feed (`espnfantasy_communication`):

```json
{"topics": {"filterType": {"value": ["ACTIVITY_TRANSACTIONS"]},
            "limit": 25,
            "sortMessageDate": {"sortPriority": 1, "sortAsc": false}}}
```

## Decoder tables

The API returns integer ids everywhere. These decode the common ones for **football**
(other games reuse the structure with their own ids).

### Lineup slot / position ids

Used by `lineupSlotId`, `defaultPositionId`, `eligibleSlots`, `filterSlotIds`:

| id | slot | id | slot | id | slot |
|---:|---|---:|---|---:|---|
| 0 | QB | 9 | DE | 18 | P |
| 1 | TQB | 10 | LB | 19 | HC |
| 2 | RB | 11 | DL | 20 | **BE** (bench) |
| 3 | RB/WR | 12 | CB | 21 | **IR** |
| 4 | WR | 13 | S | 23 | **FLEX** (RB/WR/TE) |
| 5 | WR/TE | 14 | DB | 24 | ER |
| 6 | TE | 15 | DP | 25 | Rookie |
| 7 | OP | 16 | D/ST | | |
| 8 | DT | 17 | K | | |

A player is **starting** when `lineupSlotId` is not 20 (bench) or 21 (IR).

### Pro team ids

Verified against live 2025 data (`espnfantasy_pro_teams`). Note `0` = free agent /
no team, and ids 31–32 are unused:

| id | | id | | id | | id | |
|---:|---|---:|---|---:|---|---:|---|
| 0 | FA | 9 | GB | 18 | NO | 27 | TB |
| 1 | ATL | 10 | TEN | 19 | NYG | 28 | WSH |
| 2 | BUF | 11 | IND | 20 | NYJ | 29 | CAR |
| 3 | CHI | 12 | KC | 21 | PHI | 30 | JAX |
| 4 | CIN | 13 | LV | 22 | ARI | 33 | BAL |
| 5 | CLE | 14 | LAR | 23 | PIT | 34 | HOU |
| 6 | DAL | 15 | MIA | 24 | LAC | | |
| 7 | DEN | 16 | MIN | 25 | SF | | |
| 8 | DET | 17 | NE | 26 | SEA | | |

### Stat source & split ids

On every `stats[]` entry — **the key to reading points correctly**:

| Field | Value | Meaning |
|---|---|---|
| `statSourceId` | `0` | **Actual** scored points |
| `statSourceId` | `1` | **Projected** points |
| `statSplitTypeId` | `0` | Season total |
| `statSplitTypeId` | `1` | Single scoring period (week) |
| `appliedTotal` | float | Fantasy points **after** this league's scoring rules |
| `appliedAverage` | float | Per-period average |
| `stats` | `{statId: value}` | Raw stat line — decode ids with the [stat map](#stat-ids) |

A player's stat array typically holds several entries; filter by
`statSourceId`/`statSplitTypeId` rather than taking `stats[0]`.

### Stat ids

The raw `stats` object is keyed by stat id. Football highlights:

| id | stat | id | stat | id | stat |
|---:|---|---:|---|---:|---|
| 0 | passingAttempts | 23 | rushingAttempts | 42 | receivingYards |
| 1 | passingCompletions | 24 | rushingYards | 43 | receivingTouchdowns |
| 3 | passingYards | 25 | rushingTouchdowns | 53 | receivingReceptions |
| 4 | passingTouchdowns | 39 | rushingYardsPerAttempt | 72 | lostFumbles |
| 20 | passingInterceptions | 41 | receivingReceptions | 74 | madeFieldGoalsFrom50Plus |

(136 football stat ids exist; the full map is in the `espn-api` library's
`football/constant.py` — `PLAYER_STATS_MAP`.)

### Player availability & transactions

| `status` | meaning |
|---|---|
| `FREEAGENT` | Unowned, addable now |
| `WAIVERS` | On waivers, claim required |
| `ONTEAM` | Rostered |

| `injuryStatus` | meaning |
|---|---|
| `ACTIVE` | Available |
| `QUESTIONABLE` / `DOUBTFUL` | Game-time decision |
| `OUT` / `INJURY_RESERVE` | Not playing |

Transaction `type` values include `FREEAGENT`, `WAIVER`, `TRADE_ACCEPTED`,
`TRADE_PROPOSAL`, `ROSTER`, `DRAFT`; each carries `items[]` of `ADD`/`DROP` with
`playerId`, `fromTeamId`, `toTeamId`.

## Error semantics & gotchas

| Symptom | Cause |
|---|---|
| **200 + 1.7 KB skeleton, no team names** | The view didn't take — comma-joined `view` list, or a view that doesn't exist. Views must be repeated params. |
| **HTTP 401** | Private league without `ESPN_FANTASY_COOKIE` (or expired cookies). |
| **HTTP 404 `Not Found`** | League doesn't exist *for that season*. Public league 1234 exists in 2018 and 404s in 2019+ — leagues are per-season objects. |
| **HTTP 404 `This Communication Group does not exist.`** | Normal — the league never used the message board. Not an error to fix. |
| **HTTP 400 `FILTER_LIMIT_MISSING_SORT`** | A `limit` in `x-fantasy-filter` without a sort key. |
| **`transactions` key absent** | `scoringPeriodId` was omitted from `espnfantasy_transactions`. |
| **`positionAgainstOpponent` absent** | Verified: completed/old seasons return 200 without the block. `mPositionalRatings` appears to be served in-season only. |
| **`espnfantasy_league_history` 404s** | The league has no history record. Check `espnfantasy_status` → `status.previousSeasons`; an empty list means this path will always 404 for that league. |
| **Filter appears ignored** | Wrong nesting — root-level on the game path, entity-nested on league paths. See the [cookbook](#x-fantasy-filter-cookbook). |
| **Multi-MB responses** | `allon` (~4.5 MB), `mRoster` (~900 KB), `mScoreboard` (~430 KB) on a 10-team league. Scale with league size; the provider allows a 45 s timeout. |

## Cross-provider comparison

Fantasy-league capability tags (`fantasy.*`) are ESPN-Fantasy-only today. The shared
tags compose with the rest of the server:

- `stats.fantasy_projections` → `espnfantasy_player_info` / `espnfantasy_player_card`
  alongside `supercoach_player_stats` (AFL) and Data Golf's fantasy projections —
  three different fantasy ecosystems behind one capability.
- `sport.injuries` → `espnfantasy_player_info` (fantasy injury status) alongside
  `espn_*` real-world injury feeds.
- `content.news` → `espnfantasy_player_news` alongside `espn`/`twitter` news surfaces.
- `ref.teams` / `ref.players` → the fantasy id space; join to real-world ids via player
  name + pro team (`proTeamId`, decoded above). **ESPN fantasy `playerId` values are
  ESPN athlete ids**, so they line up with the `espn` provider's athlete endpoints —
  the most useful join in the whole server: fantasy roster here → real box score /
  injury report there.
- `sport.draft` → `espnfantasy_draft` alongside real-world draft feeds (`nba_draft`,
  MLB).
- `stats.ladder` → fantasy standings alongside real competition ladders.

## Not modelled

- **Writes.** Setting lineups, adding/dropping, proposing trades all POST to
  `lm-api-writes.fantasy.espn.com`. Deliberately out of scope — this server is
  read-only, and a mis-fired write costs a real user a real roster move.
- **Username/password auth.** ESPN's login now requires Google reCAPTCHA; the
  registerdisney API-key flow the `espn-api` library shipped is commented out upstream.
  Cookies are the only path.
- **Public-league search.** There is no discovery endpoint — `/leagues` is 405 and
  `/leagues/find` parses "find" as a league id. You must know your `leagueId` (it's in
  the fantasy site URL).
- **`mTeamsForWeek`, `mRosterSettings`, `player_wl` and friends** — verified inert
  (see [views that do nothing](#views-that-do-nothing)).
- **Draft-room live feed** (`lm-api-reads`'s websocket draft channel) — a socket
  protocol, not REST.
