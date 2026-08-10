# API-Tennis (`apitennis`) — ATP, WTA and ITF

**7 tools · BYO key · shapes unverified**

Tennis draws, results, live scores, rankings and head-to-head for the men's, women's
and ITF tours, from [api-tennis.com](https://api-tennis.com).

## Why it is here

The catalogue already has `wta` (official, but women's tour only) and prices tennis
through `tab`, `sportsbet` and `pinnacle`. None of them give you an ATP draw, a player's
surface splits, or a head-to-head record. This is the only ATP + ITF source here.

## Getting a key

1. Sign up at <https://api-tennis.com>.
2. Copy the key from your dashboard.
3. Export it:

```bash
export API_TENNIS_KEY=your_key_here
```

The server starts fine without it — every other provider keeps working, and these seven
tools return a clear error telling you which variable to set.

## Two things that will bite you

**1. This API returns HTTP 200 for failures.** A missing or wrong key gives you
`200 OK` with `{"error":"1","result":[{"param":"APIkey","msg":"The field is
mandatory"}]}`. The engine detects this (`error_signals` in the spec) and raises a real
error, so a model never sees the complaint object and mistakes it for a draw. If you
call the API yourself outside this server, check the `error` field — do not trust the
status code.

**2. Shapes below come from the vendor's documentation, not from a live probe.** We hold
no key, so `shapes_verified: false` is set and every tool description says so. Field
names are very likely right; treat exact nesting as approximate until you have run it.

## Tools

| Tool | What it gives you |
|---|---|
| `apitennis_events` | Event types (ATP Singles, WTA Doubles, ITF Men, …) — the `event_type_key` other tools filter on |
| `apitennis_tournaments` | Tournaments, optionally for one event type |
| `apitennis_fixtures` | Matches in a date range, with set-by-set scores and point-by-point once played |
| `apitennis_livescore` | Matches in progress right now, including who is serving |
| `apitennis_standings` | ATP or WTA rankings |
| `apitennis_players` | One player's profile plus per-season surface splits |
| `apitennis_h2h` | Head-to-head history between two players, plus each one's recent form |

## How the API is shaped

Everything is one path — `GET /tennis/?method=<name>` — with the method name selecting
the resource, the same trick Squiggle uses with `q=`. Each tool above pins `method`, so
you never set it yourself.

Keys chain the way you would expect:

```
apitennis_events        → event_type_key
apitennis_tournaments   → tournament_key
apitennis_fixtures      → event_key, first_player_key, second_player_key
apitennis_players / apitennis_h2h  ← player keys
```

`apitennis_standings` is the quickest way to get a player key for a well-known name: the
rankings carry `player_key` alongside `player`.

## Worked example

Who is favoured in a match, given form and history?

1. `apitennis_fixtures` with today's date → the match, plus both `player_key` values.
2. `apitennis_h2h` with those two keys → their record against each other, and each
   player's last matches.
3. `apitennis_players` on each key → surface splits, so you can weight the H2H by
   whether it was won on this surface.
4. `tab_tournament` or `pinnacle_league_matchups` → what the market thinks.

## Rate limits

Capped at 2 rps here. The vendor's tiers differ; the cap is deliberately conservative
because the free tier is small.

## See also

- [WTA.md](WTA.md) — official women's-tour data, no key needed
- [TAB.md](TAB.md), [Pinnacle.md](Pinnacle.md) — tennis prices
