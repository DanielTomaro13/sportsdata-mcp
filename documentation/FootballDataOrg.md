# football-data.org (`footballdataorg`) — European competitions

**10 tools · BYO key · three endpoints verified open**

From [football-data.org](https://www.football-data.org). Free tier: 12 competitions,
10 requests/minute.

## Why carry it when `premierleague`, `laliga` and `seriea` are official and keyless?

For **breadth, not depth**. Those three are the best source for their own competitions
and should stay your first choice for them.

This adds the competitions the catalogue has no official feed for — **Champions League,
Eredivisie, Primeira Liga, the Championship, Brazilian Série A** — behind one key and one
consistent shape.

```bash
export FOOTBALL_DATA_ORG_KEY=your_key_here
```

Auth is a header, `X-Auth-Token: <key>` — not a query parameter.

## What is verified

Three endpoints are **open** and were probed live 2026-08-10:

| Tool | Verified |
|---|---|
| `footballdataorg_competitions` | 189 competitions |
| `footballdataorg_areas` | 272 areas |
| `footballdataorg_matches` | Envelope confirmed (a keyless call sees no competitions) |

The other seven return
`403 {"errorCode":403,"message":"The resource you are looking for is restricted..."}`
without a key, so their shapes come from the vendor's documentation. Each tool's
description says which it is.

That is why the provider is `optional` rather than hard-required: dropping it entirely
would lose 189 competitions of free reference data.

## The rate limit is enforced hard

**10 requests per minute** on the free tier. This server throttles to 0.15 rps for that
reason, so calls pace themselves rather than 429. Responses carry
`X-Requests-Available-Minute`.

## `plan` tells you what your key can actually see

Every competition in `footballdataorg_competitions` carries a tier:

```json
{"code": "PL", "name": "Premier League", "plan": "TIER_ONE",
 "currentSeason": {"currentMatchday": 12}}
```

The free key covers **TIER_ONE only**. A 403 on a specific competition usually means it
is on a higher tier, not that your key is broken.

## Tools

| Tool | Needs a key | What it gives you |
|---|---|---|
| `footballdataorg_competitions` | no | Every competition, its code and current season |
| `footballdataorg_areas` | no | Countries and regions, for filtering |
| `footballdataorg_matches` | no* | Matches across competitions for a date range |
| `footballdataorg_competition` | yes | One competition with its seasons |
| `footballdataorg_standings` | yes | League table |
| `footballdataorg_competition_matches` | yes | All matches in one competition |
| `footballdataorg_teams` | yes | The clubs in a competition |
| `footballdataorg_scorers` | yes | Top scorers |
| `footballdataorg_team` | yes | One club with squad and running competitions |
| `footballdataorg_match` | yes | One match: lineups, goals, bookings, head-to-head |

\* the envelope works keyless, but you will see no competitions without a key.

## Competition codes

Short codes are easier than numeric ids and work everywhere `competition` is accepted:

| Code | Competition |
|---|---|
| `PL` | Premier League |
| `CL` | UEFA Champions League |
| `BL1` | Bundesliga |
| `SA` | Serie A |
| `PD` | La Liga (Primera División) |
| `FL1` | Ligue 1 |
| `DED` | Eredivisie |
| `PPL` | Primeira Liga |
| `ELC` | Championship |
| `BSA` | Brazilian Série A |

## Two shapes worth knowing before you parse

**The score is not on the match** — it is nested, and split by period:

```json
{"score": {"winner": "HOME_TEAM", "duration": "REGULAR",
           "fullTime": {"home": 2, "away": 1},
           "halfTime": {"home": 1, "away": 0}}}
```

**`standings` is a LIST of tables**, not one table. Each entry has a `type` —
`TOTAL`, `HOME` or `AWAY` — and a group-stage competition adds one per group. For the
ordinary ladder, filter to `type == "TOTAL"`.

## Date windows are capped

`footballdataorg_matches` accepts `dateFrom` / `dateTo`, with a maximum span of **10
days** on the free tier. A wider window returns an error rather than truncating.

## See also

- [PremierLeague.md](PremierLeague.md), [LaLiga.md](LaLiga.md), [SerieA.md](SerieA.md) — official, keyless, deeper
- [Sportmonks.md](Sportmonks.md) — fewer competitions, more per-match detail
