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

## When to use something else

For Australian and European markets, the direct providers (`sportsbet`, `tab`,
`pointsbet`, `betfair`, `pinnacle`) and the two Western aggregators are better. Come
here for Asian books and AH lines.
