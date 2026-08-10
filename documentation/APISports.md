# API-Sports (`apisports`) — ten sports on one key

**20 tools · BYO key · shapes unverified**

Football, basketball, baseball, ice hockey, American football, rugby, Formula 1,
handball, volleyball and MMA from [api-sports.io](https://api-sports.io).

## One vendor, many product names

You will see this API sold as **API-FOOTBALL**, **API-BASKETBALL**, **API-NBA**,
**API-RUGBY** and so on. They are the same product on the same key. Each sport lives on
its own hostname:

```
v3.football.api-sports.io      v1.american-football.api-sports.io
v1.basketball.api-sports.io    v1.rugby.api-sports.io
v1.baseball.api-sports.io      v1.formula-1.api-sports.io
v1.hockey.api-sports.io        v1.handball.api-sports.io
v1.volleyball.api-sports.io    v1.mma.api-sports.io
```

That is why this is one provider with ten base URLs rather than ten providers.

## Getting a key

1. Register at <https://dashboard.api-football.com/register> (the same account covers
   every sport).
2. Export it:

```bash
export API_SPORTS_KEY=your_key_here
```

Free tier: **100 requests per day**, and `season` is restricted to a few older seasons.
The provider is rate-limited to 1 rps here because a daily cap punishes bursts.

> If you subscribed through **RapidAPI** instead, your key goes in `x-rapidapi-key`
> against `*.p.rapidapi.com` hosts. That is a different deployment, and this spec
> targets the direct one.

## The thing that will bite you: failures arrive inside a 200

Every response has the same envelope:

```json
{"get": "...", "parameters": {}, "errors": [], "results": 0, "response": []}
```

`errors` is `[]` on success and an **object** on failure — including the failure you
will actually hit:

```json
{"errors": {"requests": "You have reached the request limit for the day"},
 "results": 0, "response": []}
```

…returned with **HTTP 200**. Left alone, a model asking for today's fixtures receives an
empty list and reports "there are no matches today". Quota exhaustion looks exactly like
a quiet Tuesday.

This server detects it: the spec declares a presence-mode `error_signals` entry on
`errors`, so a populated `errors` object raises instead of decoding to an empty result.
**If you call this API outside this server, check `errors` before you trust
`response`.**

`apisports_status` costs no quota and tells you where you stand — call it first whenever
something comes back empty.

## Tools

### Football (the deepest surface)

| Tool | What it gives you |
|---|---|
| `apisports_football_leagues` | Leagues worldwide, each with a `coverage` block saying which other tools will work for it |
| `apisports_football_fixtures` | Fixtures and results by date, league or team |
| `apisports_football_standings` | League tables |
| `apisports_football_teams` | Clubs and their venues |
| `apisports_football_players` | Player season statistics |
| `apisports_football_fixture_statistics` | Team match statistics, including xG where covered |
| `apisports_football_h2h` | Every past meeting between two clubs |
| `apisports_football_odds` | Pre-match odds from many books |
| `apisports_football_predictions` | The vendor's own model prediction, with the comparison data behind it |

### The other sports

| Tool | Sport |
|---|---|
| `apisports_basketball_games`, `apisports_basketball_standings` | Basketball (NBA, EuroLeague, NBL, …) |
| `apisports_baseball_games` | Baseball (MLB, NPB, KBO) |
| `apisports_hockey_games` | Ice hockey (NHL, KHL, SHL) |
| `apisports_nfl_games` | American football (NFL, NCAA) |
| `apisports_rugby_games` | Rugby — the catalogue's only rugby-union coverage |
| `apisports_formula1_races` | Formula 1 |
| `apisports_mma_fights` | MMA (UFC and others) |
| `apisports_handball_games` | Handball (EHF Champions League, Bundesliga, LNH) |
| `apisports_volleyball_games` | Volleyball (SuperLega, PlusLiga, CEV) |

Plus `apisports_status` for quota.

## Inconsistencies between the sport hosts

The hosts share a vendor, not a schema. Three differences matter:

**Volleyball `scores` are SETS WON, not points** — the per-set point totals live in
`periods`. Reading `scores` as points is the mistake that endpoint invites.

| | Football | Basketball | American football |
|---|---|---|---|
| `season` format | integer `2023` | **span string** `"2023-2024"` | integer `2023` |
| identity nesting | flat on the object | flat on the object | **wrapped under `game`** |
| score field | `goals` + `score` | `scores` with quarters | `scores` with quarters |

Check the response hint on the specific tool rather than generalising from football.

## `coverage` is worth reading

Each season in `apisports_football_leagues` carries a `coverage` object:

```json
{"fixtures": {"events": true, "lineups": true, "statistics_fixtures": false},
 "standings": true, "players": true, "odds": false, "predictions": true}
```

That is the honest answer to "why is this endpoint empty for my league" — often the
answer is that the league is not covered for that surface, not that the call is wrong.

## When to use something else

- **NBA** → `nba` (keyless, official, play-by-play)
- **MLB** → `mlb` (keyless, official, far deeper)
- **NHL** → `nhl` (keyless, official)
- **NRL** → `nrl` (keyless, official) rather than the rugby host
- **F1** → `jolpicaf1` (history to 1950) and `openf1` (live telemetry), both keyless
- **AU odds** → `sportsbet`, `tab`, `pointsbet`, `betfair` — direct and live

The reason to use API-Sports is **breadth on one key**, and rugby union, which nothing
else here covers.
