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

## Two details

**`url` and `embedUrl` are not interchangeable** — one is a page link, the other an
iframe source.

**The score is nested under `state`**, not on the match object:
`match.state.score.current`.
