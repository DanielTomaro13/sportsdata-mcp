# Lichess API Documentation

Reference for **`lichess.org/api`** — the open-source chess server's public API. Free,
well documented, no key for public reads. Probed live 2026-08-10.

Together with [Chess.com](ChessCom.md) this covers both major chess platforms, a
domain the server previously had nothing in.

## The NDJSON constraint — why only six tools

Lichess streams many of its bulk surfaces as **newline-delimited JSON**: one JSON
object per line, not a single document.

```
{"id":"abc", ...}
{"id":"def", ...}
```

This engine decodes **one JSON document per response**, so an NDJSON endpoint fails to
parse. Verified live: `/api/broadcast` errors with `Extra data: line 2 column 1`.

Only single-document endpoints are exposed. That deliberately rules out:

- **Game exports** (`/api/games/user/{u}`, `/api/games/export/_ids`) — NDJSON or PGN
- **Broadcasts / tournament results / team members** — NDJSON streams
- **Event and board streams** — long-lived streaming connections

If game-level history matters, [Chess.com's](ChessCom.md) `chesscom_monthly_games`
returns a normal JSON document and covers that need.

## Ratings: there is no single "rating"

A Lichess player has a rating **per time control and per variant**, under `perfs`:

```jsonc
"perfs": {
  "bullet":  {"rating": 1774, "games": 7483, "rd": 94,  "prog": -22},
  "blitz":   {"rating": 1806, "games": 11721, ...},
  "rapid": {...}, "classical": {...}, "correspondence": {...},
  "puzzle": {...}, "atomic": {...}, "crazyhouse": {...}
}
```

`prov: true` marks a **provisional** rating (too few games to be meaningful) — showing
it next to an established one without that caveat is misleading. `rd` is rating
deviation: high means uncertain.

## Tools

| Tool | Returns | Capability |
|---|---|---|
| `lichess_user` | One player: per-perf ratings, counts, play time, profile | `stats.player_profile`, `ref.players` |
| `lichess_users_status` | Online/playing/streaming for up to 50 users at once | — |
| `lichess_leaderboard` | Top N for one time control or variant | `sport.rankings` |
| `lichess_leaderboards_all` | Top 10 for **every** perf in one call | `sport.rankings` |
| `lichess_daily_puzzle` | Today's puzzle with solution and source game | `content.news` |
| `lichess_tournaments` | Arena tournaments, split by state | `sport.fixtures_by_date` |

`lichess_tournaments` returns **three lists** (`created`, `started`, `finished`), not
one — "upcoming" is `created`, and reading only the top-level as a list gets nothing.

## Gotchas

| Symptom | Cause |
|---|---|
| **`Extra data: line 2`** | An NDJSON endpoint. Not supported — see above. |
| **No `rating` field** | Ratings live under `perfs.<timeControl>.rating`. |
| **A suspiciously high rating** | Check `prov` — provisional ratings are unreliable. |
| **`perfs` missing a variant** | The player has never played it. |
| **HTTP 429** | Lichess is donation-funded; back off. The provider caps at 5 rps. |
| **Tournaments look empty** | You read the top level as a list; it's three keyed lists. |

## Cross-provider comparison

- `sport.rankings` → the two leaderboard tools alongside `chesscom_leaderboards`. A
  player active on both platforms will have **different ratings on each** — the pools
  and formulas differ, so Lichess ratings run higher than Chess.com's at equivalent
  strength. Never present them as interchangeable.
- `stats.player_profile` → `lichess_user` alongside `chesscom_player` and the
  real-world sports profile tools.
- Usernames do not join across platforms: `hikaru` exists on both and is the same
  person, but that's a coincidence of naming, not an id.

## Not modelled

Everything NDJSON or streaming (see above), plus all authenticated surfaces — account
management, playing games via the board API, challenges, and puzzle history all need
an OAuth token and are write-capable, which is out of scope for a read-only server.
