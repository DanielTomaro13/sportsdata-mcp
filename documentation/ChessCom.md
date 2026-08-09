# Chess.com API Documentation

Reference for **`api.chess.com/pub`** — Chess.com's "Published Data" API. Read-only,
no key, no signup, and explicitly published for third-party use. Probed live
2026-08-10.

Pairs with [Lichess](Lichess.md) to cover both major chess platforms.

## Rate limiting is behavioural, not numeric

Chess.com doesn't publish a requests-per-second number. Its guidance is:

> Serial requests are fine. **Parallel** requests get throttled.

It returns `429` when it sees **concurrency** from one caller, not when a rate is
exceeded. This provider is therefore configured `rate_limit_rps: 2` with
**`burst: 1`** — the burst of 1 is the important part, because it makes this provider
issue requests effectively serially. Widening `burst` is what breaks it, and it will
look like a random intermittent failure rather than a config mistake.

## The API is hypermedia

Every object carries an `@id`: the canonical URL to fetch it again. Lists are often
lists of **URLs** rather than embedded objects — which is why game history works in two
steps:

```
chesscom_archives(username)      → ["…/games/2014/01", …, "…/games/2026/08"]
      └─ chesscom_monthly_games(username, year, month)
```

Take the year and month off the **last** archive URL to get the most recent games.
There is no "recent games" endpoint.

## Two conventions that cause errors

**Timestamps are UNIX seconds**, not ISO strings: `joined`, `last_online`, `end_time`,
and the `date` inside rating records. Rendering them raw shows a ten-digit number.

**Month must be zero-padded.** `month="1"` 404s; `month="01"` works. Same for the year
being a four-digit string.

## Tools

| Tool | Returns | Capability |
|---|---|---|
| `chesscom_player` | Profile: name, title, country, league, followers, status | `stats.player_profile`, `ref.players` |
| `chesscom_player_stats` | Ratings + W/L/D per format, tactics, puzzle rush, FIDE | `stats.player_season`, `stats.player_career` |
| `chesscom_leaderboards` | Every leaderboard category (~290 KB) | `sport.rankings` |
| `chesscom_titled_players` | All holders of a FIDE title — **usernames only** | `ref.players` |
| `chesscom_archives` | Which months a player has games for | — |
| `chesscom_monthly_games` | One month of games with PGN, ECO, accuracies | `stats.player_game_log` |
| `chesscom_club` | Club detail: members, average rating, admins | — |

`chesscom_player_stats` **omits** a format entirely if the player has never played it —
absence means "never played", not "zero rating". And `chesscom_titled_players` returns
a flat list of username **strings**, not objects; feed one to `chesscom_player` for
detail.

## Gotchas

| Symptom | Cause |
|---|---|
| **Intermittent 429s** | Parallel requests. Keep `burst: 1` — this is behavioural throttling, not a rate cap. |
| **404 from monthly games** | `month` isn't zero-padded (`"01"`, not `"1"`), or that month has no games — check `chesscom_archives` first. |
| **Ten-digit dates** | Unix seconds, not ISO. |
| **A rating format is missing** | The player has never played it. |
| **`country` isn't a code** | It's a URL to a country object. |
| **Multi-MB response** | A prolific player's month, or the full leaderboards. Expected. |
| **HTTP 403** | Chess.com blocks requests without a recognisable User-Agent; keep the contact UA. |

## Cross-provider comparison

- `sport.rankings` → `chesscom_leaderboards` alongside Lichess's leaderboards. **Ratings
  are not comparable across platforms** — different pools and formulas mean Lichess
  ratings sit higher than Chess.com's at equivalent strength. Presenting them side by
  side without that caveat produces a wrong conclusion.
- `stats.player_profile` → `chesscom_player` alongside `lichess_user`.
- `stats.player_game_log` → `chesscom_monthly_games` alongside
  `espn`/`nhl` game logs. Chess.com is the only chess source here with usable game
  history, because Lichess streams its exports as NDJSON.

## Not modelled

- **Tournaments, team matches, daily puzzles** — available, lower value next to the
  player and leaderboard surfaces.
- **Streamers / country player lists** — very large, weak signal.
- **Anything authenticated** — the published API is public and read-only by design;
  there is no private tier to model.
