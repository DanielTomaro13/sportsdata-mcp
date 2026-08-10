# iSportsAPI (`isportsapi`) — Asian markets

**5 tools · BYO key · shapes unverified**

Football and basketball from [isportsapi.com](https://www.isportsapi.com), with
Asian-handicap odds coverage the Western aggregators index thinly.

```bash
export ISPORTS_API_KEY=your_key_here
```

## It reports failures with HTTP 200

Verified live 2026-08-10:

```
HTTP 200  {"code":2,"message":"Invalid [api_key], illegal access."}
```

`code` is `0` on success and non-zero on failure. This server declares a presence-mode
error signal on `code`, so `0` passes through as data and anything else raises a real
error. **If you call this API directly, check `code` — the status line will always say
200.**

## Tools

| Tool | What it gives you |
|---|---|
| `isportsapi_football_odds_asian` | **Asian handicap, Europe odds and over/under across companies** |
| `isportsapi_football_schedule` | Fixtures and results by date |
| `isportsapi_football_competitions` | Competition ids |
| `isportsapi_football_live` | In-play, including corners and cards |
| `isportsapi_basketball_schedule` | Basketball fixtures |

## The odds payload is positional arrays

This is the thing that will surprise you. `isportsapi_football_odds_asian` does not
return objects:

```json
{"handicap": [[matchId, companyId, initialHandicap, initialHome, initialAway,
               liveHandicap, liveHome, liveAway, ...]]}
```

Fields are identified **by index**, and the column order is the vendor's own — it does
not match any other provider here. Read their column documentation before parsing, and
do not reuse a parser written for `theoddsapi` or `oddsapiio`.

Also note `matchTime` is a **UNIX timestamp**, not an ISO string.

## Reading an Asian handicap line

If you have only worked with 1X2 or moneyline markets, the AH columns need a translation.
A handicap of `-0.5` on the home side means home must win outright; `-0.25` is a split
stake (half on 0, half on -0.5), so a draw refunds half. Quarter-ball lines are why the
values here go in 0.25 steps rather than 0.5.

Each row carries **initial** and **live** values:

```
initialHandicap, initialHome, initialAway,  liveHandicap, liveHome, liveAway
```

The move from initial to live is the signal — Asian books move handicaps rather than
prices, so a line drifting from -0.5 to -0.75 is the equivalent of a price shortening.

## `matchTime` is a Unix timestamp

Not an ISO string, unlike almost everything else in this catalogue. Seconds since epoch,
UTC.

## Corners and cards come with the live score

`isportsapi_football_live` returns `homeCorner`, `awayCorner`, `homeYellow`, `homeRed`
and so on **inline with the score**, rather than in a separate statistics call. If you
are watching corner or card markets, that is one call rather than two.

## The competition id is the join key

`isportsapi_football_competitions` gives you `competitionId`, which `..._schedule`
accepts as `leagueId` — note the name changes between the two endpoints. Match ids from
the schedule are what the odds endpoint filters on.

## When to use something else

For Australian and European markets, the direct providers (`sportsbet`, `tab`,
`pointsbet`, `betfair`, `pinnacle`) and the two Western aggregators are better, and they
return objects rather than positional arrays. Come here for Asian books and AH lines.

## See also

- [Pinnacle.md](Pinnacle.md) — also carries Asian lines, keyless, object-shaped
- [TheOddsAPI.md](TheOddsAPI.md), [OddsAPIio.md](OddsAPIio.md) — Western aggregators
