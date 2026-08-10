# College Football Data (`cfbd`) — NCAA football analytics

**10 tools · BYO key · shapes unverified**

From [collegefootballdata.com](https://collegefootballdata.com). Verified live
2026-08-10 (keyless): paths exist and return a 401 whose message names the exact mistake
most people make.

## Auth: the `Bearer ` prefix is required

```
Authorization: Bearer <your key>
```

The API's own 401 says it outright — *"Did you forget to add \"Bearer \" before your
key?"* — because it is the single most common failure. This server adds the prefix for
you, so the env var holds the **bare key**:

```bash
export CFBD_API_KEY=your_key_here
```

## What it adds over `ncaa` and `espn`

Those give you college scores, polls and standings. CFBD is the **analytics layer**, and
it is the only source in this catalogue for college-football advanced metrics:

- **SP+** — the headline predictive rating, split by offence and defence
- **Elo** — by team and week
- **Advanced box scores** — success rate, explosiveness, PPA, field position
- **Historical betting lines** from multiple books, with opening *and* closing numbers
- **Recruiting** and the **transfer portal**

That betting-line history pairs with `footballdatauk` as a second backtesting dataset,
for a different sport.

## Two parameters decide whether you see anything

**`year` is required** on the game and stat endpoints. There is no "current season"
default.

**`seasonType` matters more than it looks.** It defaults to `regular`, and **bowl games
are invisible under the default**:

| Value | Covers |
|---|---|
| `regular` (default) | The regular season only |
| `postseason` | Bowls and the playoff |
| `both` | Everything (on endpoints that accept it) |

A December query that returns nothing is almost always this.

## Tools

| Tool | What it gives you |
|---|---|
| `cfbd_games` | Games for a season, with scores, venue, attendance, excitement index |
| `cfbd_teams` | FBS/FCS programmes with conference, venue, colours |
| `cfbd_rankings` | Weekly AP, Coaches and Playoff Committee polls |
| `cfbd_ratings_sp` | **SP+ ratings**, offence/defence/special teams |
| `cfbd_ratings_elo` | Elo by team and week |
| `cfbd_betting_lines` | **Historical lines** per game per book, open and close |
| `cfbd_team_season_stats` | Season totals per team |
| `cfbd_advanced_box_score` | **Advanced box** for one game |
| `cfbd_recruiting` | Recruiting classes with stars and ratings |
| `cfbd_portal` | Transfer-portal moves |

## Shapes that differ from what you would guess

**`cfbd_rankings` nests polls inside each week**, rather than returning a flat list:

```json
[{"season": 2024, "week": 10,
  "polls": [{"poll": "AP Top 25", "ranks": [{"rank": 1, "school": "Oregon", ...}]}]}]
```

**`cfbd_team_season_stats` is LONG format** — one row *per statistic per team*, not one
row per team:

```json
[{"season": 2024, "team": "Georgia", "statName": "rushingYards", "statValue": 2145}]
```

Pivot it yourself if you want a table.

**`cfbd_betting_lines` nests per book**, and carries both open and close:

```json
{"lines": [{"provider": "consensus", "spread": -7.5, "spreadOpen": -6.5,
            "overUnder": 52.5, "overUnderOpen": 51.0, "homeMoneyline": -290}]}
```

`spreadOpen` versus `spread` is the CLV comparison.

**`cfbd_advanced_box_score` takes `id` as a QUERY parameter**, not in the path — unlike
most of the API.

**Defensive ratings are better when LOWER** in SP+. A defence rated 12.0 is better than
one rated 28.0; sorting descending gives you the worst defences in college football.

## PPA, in one line

CFBD's expected-points-added metric. Positive is good for an offence; the cumulative
version tracks it across a game. It is the college analogue of EPA in the NFL.

## Worked example

"Is this line right for Saturday's game?"

1. `cfbd_games` with `year` and `week` → the game and its id.
2. `cfbd_ratings_sp` → both teams' SP+, offence and defence separately.
3. `cfbd_betting_lines` → what the books opened and where they are now.
4. `cfbd_advanced_box_score` on recent games → whether the rating matches recent form.
5. `theoddsapi_odds` with `sport: americanfootball_ncaaf` → current market.

## See also

- [NCAA.md](NCAA.md) — scores, polls and standings, keyless
- [ESPN.md](ESPN.md) — college scoreboards, keyless
- [FootballDataUK.md](FootballDataUK.md) — the same backtesting idea, for football
