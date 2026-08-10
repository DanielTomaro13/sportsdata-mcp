# Highlightly (`highlightly`) — highlight video

**7 tools · BYO key · shapes unverified**

Match highlight clips across football, basketball, American football, baseball and ice
hockey, from [highlightly.net](https://highlightly.net).

## What it adds that nothing else here does

**Video.** Every other provider in this catalogue answers "what happened" with numbers.
This one returns links to the actual clips, keyed to the match. The only comparable
surfaces here are the AFL and NRL official content feeds, and those are single-league.

```bash
export HIGHLIGHTLY_API_KEY=your_key_here
```

All five sport hosts were probed live 2026-08-10 and answer
`403 {"status":403,"error":"Missing mandatory HTTP Headers…"}` without a key.

## One key, five hosts

```
soccer.highlightly.net              baseball.highlightly.net
basketball.highlightly.net          hockey.highlightly.net
american-football.highlightly.net
```

Same pattern as `apisports`.

> **If you subscribed via RapidAPI**, your key goes in `x-rapidapi-key` against a
> `*.p.rapidapi.com` host. This spec targets the **direct** hosts with `x-api-key`; a
> RapidAPI subscription will not authenticate against them.

## Tools

| Tool | Sport |
|---|---|
| `highlightly_soccer_highlights` | Football clips |
| `highlightly_soccer_matches` | Football matches — to find the `matchId` a clip lookup needs |
| `highlightly_soccer_leagues` | Competitions covered |
| `highlightly_basketball_highlights` | Basketball clips |
| `highlightly_nfl_highlights` | American-football clips |
| `highlightly_baseball_highlights` | Baseball clips |
| `highlightly_hockey_highlights` | Ice-hockey clips |

## How to actually get a clip

Highlights are keyed to a match, so the flow is always two calls:

1. `highlightly_soccer_matches` (or the equivalent for the sport) with a `date` or
   `leagueId` → the match and its `id`.
2. `highlightly_soccer_highlights` with `matchId` → the clips for it.

Filtering highlights by `date` alone works too, but returns everything that day across
every competition, so `leagueId` is usually the filter you want.

`highlightly_soccer_leagues` gives you the `leagueId` values, and takes a `leagueName`
search — useful because competition naming here does not always match other providers'.

## Shapes worth knowing

**`url` and `embedUrl` are not interchangeable.** One is a page link for a human, the
other an iframe source for embedding. Handing a model the wrong one produces a link that
looks right and does not play where it is put.

**The score is nested under `state`**, not on the match:

```json
{"id": 123, "homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
 "state": {"description": "Finished", "score": {"current": "2 - 1", "penalties": null}}}
```

Note `score.current` is a **display string**, not two numbers.

**Pagination is `limit` + `offset`**, with `limit` capped at 40, and the totals live in a
`pagination` object on the response.

## Coverage is not uniform

Highlight availability depends on rights, which vary by competition and change. An empty
result for a real match usually means no clip is licensed for it, not that the call is
wrong — check `highlightly_soccer_leagues` to confirm the competition is covered at all
before assuming a bug.

## Limits

The free tier is small and the vendor's tiers differ; this server caps at 2 rps. Video
URLs point at third-party hosts (YouTube and similar), so their availability is outside
both this API's control and ours.

## See also

- [AFL.md](AFL.md) and [NRL.md](NRL.md) — official video for those two codes, keyless
- [ESPN.md](ESPN.md) — some video metadata, keyless
