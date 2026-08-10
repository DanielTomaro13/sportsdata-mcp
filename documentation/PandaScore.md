# PandaScore (`pandascore`) — esports across 13 titles

**8 tools · BYO key · shapes unverified**

League of Legends, CS2, Dota 2, Valorant, Overwatch, Rainbow Six, Rocket League,
StarCraft II, Call of Duty, FIFA, Hearthstone, KoG and PUBG — from
[pandascore.co](https://pandascore.co).

## Why it is worth the signup

`opendota` is excellent and covers **Dota 2 only**, with no odds. PandaScore is the broad
esports source: matches, tournaments, standings **and betting markets** across 13 titles,
on a genuinely usable free tier (1,000 requests/hour).

The AU books price esports, so a PandaScore match lines up against a `sportsbet` or
`pinnacle` market exactly the way a football fixture does — and `pandascore_match_odds`
is the part `opendota` cannot give you at all.

```bash
export PANDASCORE_TOKEN=your_token_here
```

Auth is `Authorization: Bearer <token>`. Verified live 2026-08-10 (keyless): paths exist
and return `403 {"error":"Token is missing"}`.

## The videogame slug is the root of everything

Most paths take a title slug, and **a wrong slug is a 404**, not an empty list:

| Title | Slug | Note |
|---|---|---|
| Counter-Strike 2 | `csgo` | **still `csgo`** in the API, not `cs2` |
| League of Legends | `lol` | |
| Dota 2 | `dota2` | |
| Valorant | `valorant` | |
| Overwatch | `ow` | |
| Rainbow Six Siege | `r6siege` | |
| Rocket League | `rl` | |
| StarCraft II | `starcraft-2` | |
| Call of Duty | `cod-mw` | |
| FIFA | `fifa` | |
| Hearthstone | `hearthstone` | |
| King of Glory | `kog` | |
| PUBG | `pubg` | |

`csgo` is the one that catches everyone. Call **`pandascore_videogames`** for the live
list rather than trusting this table — it is the authoritative answer and costs one
request.

## Tools

| Tool | What it gives you |
|---|---|
| `pandascore_videogames` | The titles covered, with slugs — **call this first** |
| `pandascore_matches` | Matches across every title or one; upcoming, running or past |
| `pandascore_match_odds` | **Betting markets and prices** for one match |
| `pandascore_tournaments` | Tournaments — upcoming, running or past |
| `pandascore_leagues` | Leagues (the recurring competitions tournaments belong to) |
| `pandascore_series` | Seasonal editions of a league, e.g. "LEC Summer 2025" |
| `pandascore_teams` | Teams with current rosters |
| `pandascore_players` | Players with role, nationality and current team |

## The competition hierarchy

Esports nests one level deeper than traditional sport, and mixing the levels up is the
usual source of empty results:

```
league        "LEC"                    the recurring competition
  └ series    "LEC Summer 2025"        one seasonal edition
      └ tournament  "Playoffs"         a stage within it
          └ match   "G2 vs FNC"        the thing that gets priced
```

A "tournament" is a **stage**, not the whole event. If you ask for tournaments and get
something that looks too granular, that is why.

## Pagination puts the totals in headers

```
page=2&per_page=100          (per_page maxes at 100)
```

The body is a **bare array** — the counts are in response headers (`X-Total`, `X-Page`),
which this server does not surface. In practice: if you get exactly `per_page` items,
assume there are more and ask for the next page.

## Filtering

The API uses bracketed query syntax for filters and ranges, e.g. `filter[status]`,
`range[begin_at]`, `sort=-begin_at`. The tools expose the common ones directly; for
anything exotic, check PandaScore's own docs — the parameter names pass through.

## Worked example: is this esports price any good?

1. `pandascore_videogames` → confirm the slug (`csgo`, not `cs2`).
2. `pandascore_matches` with that slug and `status=upcoming` → the match and its id.
3. `pandascore_match_odds` → PandaScore's aggregated markets.
4. `sportsbet_event_markets` or `pinnacle_matchup_markets` → the AU price.
5. `pandascore_teams` / `pandascore_players` → roster changes, which move esports lines
   far more than injuries move traditional ones.

## See also

- [OpenDota.md](OpenDota.md) — Dota 2 only, keyless, much deeper on match detail
- [Pinnacle.md](Pinnacle.md) — prices esports, keyless
