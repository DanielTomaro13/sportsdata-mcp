# CricketData / CricAPI (`cricketdata`) — international cricket

**8 tools · BYO key · shapes unverified**

Test, ODI, T20I and franchise cricket — IPL, BBL, PSL, The Hundred and the rest — from
[cricketdata.org](https://cricketdata.org) (the API host is `api.cricapi.com`).

## Why it is here

`cricketaustralia` is official and excellent, and it is Australia-only. Everything
outside CA's remit — an India tour of England, an IPL match, a PSL final — is invisible
to this catalogue without a source like this one. The AU books price all of it.

## Getting a key

1. Sign up at <https://cricketdata.org>.
2. Copy the API key from your dashboard.
3. Export it:

```bash
export CRICKETDATA_API_KEY=your_key_here
```

The free tier is **100 requests per day**. Every response carries your usage in
`info.hitsToday` / `info.hitsLimit` — worth watching, because it is easy to burn through
a day's quota exploring. The provider is rate-limited to 1 rps here for the same reason.

## Two things that will bite you

**1. This API returns HTTP 200 for failures.** An invalid or missing key gives you
`200 OK` with `{"status":"failure","reason":"Invalid API Key"}`. The engine catches that
(`error_signals` in the spec) and raises a real error rather than handing the failure
object to a model as though it were a scorecard.

**2. Shapes come from the vendor's documentation, not a live probe** —
`shapes_verified: false`, and every tool description carries the caveat.

## Tools

| Tool | What it gives you |
|---|---|
| `cricketdata_current_matches` | Live and imminent matches with running scores |
| `cricketdata_matches` | All matches, paginated — recent and upcoming |
| `cricketdata_match_info` | One match: toss, venue, teams, result |
| `cricketdata_scorecard` | Full scorecard — batting and bowling figures per innings |
| `cricketdata_series` | Series and tours, with match counts per format |
| `cricketdata_series_info` | One series with its full match list |
| `cricketdata_players` | Search the player catalogue by name |
| `cricketdata_player_info` | One player's profile and career statistics |

## Response conventions

**Everything is enveloped**: `{apikey, data, status, info}`. The payload is under `data`.

**Cricket abbreviations are terse**, and the API does not expand them:

| Field | Means | Where |
|---|---|---|
| `r` | runs | batting rows, score summary |
| `b` | balls faced | batting rows |
| `sr` | strike rate | batting rows |
| `4s` / `6s` | boundaries | batting rows |
| `o` | overs bowled | bowling rows, score summary |
| `m` | maidens | bowling rows |
| `w` | wickets | bowling rows, score summary |
| `eco` | economy rate | bowling rows |

So a score entry `{r: 187, w: 4, o: 20, inning: "India Innings"}` reads as 4/187 off 20
overs.

**`cricketdata_player_info` returns career stats in LONG format** — one row per
(function, format, statistic):

```
{fn: "batting", matchtype: "odi", stat: "avg", value: "58.1"}
```

Not a nested object. Filter on `fn` and `matchtype` to get the numbers you want.

## Worked example

How has a batter gone in this format lately?

1. `cricketdata_players` with `search` → the player id.
2. `cricketdata_player_info` → career averages, filtered to `matchtype: "t20i"`.
3. `cricketdata_current_matches` → the match they are in now.
4. `cricketdata_scorecard` on that match id → the innings in progress.

## Quota discipline

With 100 requests a day, prefer:

- `cricketdata_current_matches` over `cricketdata_matches` when you only care about now
- `cricketdata_series_info` (one call, full match list) over paging `cricketdata_matches`
- letting the response cache serve repeats — identical calls within the TTL cost nothing

## See also

- [CricketAustralia.md](CricketAustralia.md) — official, deeper, AU-only, no key
