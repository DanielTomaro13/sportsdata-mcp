# Fantasy Premier League (`fpl`) — official API

**16 tools · no key · shapes verified live**

The most-played fantasy game in the world — **4,085,510 registered squads** — and its API
is entirely public except for your own squad.

## The one thing that shapes this whole provider

`bootstrap-static` returns **1.37 MB** containing six unrelated datasets. Measured:

| Section | Bytes | Tokens |
|---|---:|---:|
| `elements` (581 players × 105 fields) | 1,447,462 | **~362,000** |
| `events` (gameweeks) | 29,201 | ~7,300 |
| `teams` | 8,258 | ~2,100 |
| everything else | ~7,000 | ~1,800 |

No context window holds 362,000 tokens, FPL offers no server-side field selection, and
there is no narrower route to the player list. So `fpl_players`, `fpl_teams`,
`fpl_gameweeks` and `fpl_game_rules` all hit that one URL and each return **one slice**,
via the engine's `response_pick` / `response_fields`. Nothing is invented or renamed —
only removed. `fpl_players` lands at ~58k tokens for all 581 players.

If you need a field that isn't in the 22, use **`fpl_player_detail`**, which returns one
player in full.

## Units that catch everyone

**`now_cost` is tenths of a million.** `145` means £14.5m. Same for `bank`, `value`,
`selling_price` and `purchase_price`.

**Many numbers are strings.** `form`, `points_per_game`, `selected_by_percent`, `ep_next`
and the whole expected-goals family come back as `"5.4"`, not `5.4`.

**`element_type` is the position:** 1 GK, 2 DEF, 3 MID, 4 FWD. Resolve via
`fpl_game_rules`.

**`team` is FPL's own 1–20 id**, alphabetical — *not* the Premier League's official team
id. Joining to the `premierleague` provider means matching on name.

## Seasonal 404s are normal

`fpl_dream_team`, `fpl_manager_picks` and `fpl_live_gameweek` need a gameweek that has
actually been played. Before the season starts they 404 or return `{"elements": []}`.
That's the API being correct, not drift.

## Tools

### Players

| Tool | What it gives you |
|---|---|
| `fpl_players` | Every player: price, form, ownership, xG/xA, availability (~58k tokens) |
| `fpl_player_detail` | One player in full: every gameweek, past seasons, upcoming fixture difficulty |

### Reference — all slices of the same blob

| Tool | What it gives you |
|---|---|
| `fpl_teams` | The 20 clubs with FPL's attack/defence strength ratings |
| `fpl_gameweeks` | All 38 gameweeks: **deadlines**, averages, highest score, chip usage |
| `fpl_game_rules` | Positions, chips, phases, scoring settings — the lookup tables |

### Fixtures and live scoring

| Tool | What it gives you |
|---|---|
| `fpl_fixtures` | Fixtures with difficulty ratings and per-player contributions once played |
| `fpl_live_gameweek` | Live per-player points, with `explain` breaking down *why* |
| `fpl_dream_team` | The highest-scoring XI of a completed gameweek |
| `fpl_event_status` | Whether bonus points are final — read this before trusting a score |
| `fpl_set_piece_notes` | Official penalty/corner/free-kick takers per club |

### Managers and leagues

| Tool | What it gives you |
|---|---|
| `fpl_manager` | Overall rank, points, and every league a manager is in |
| `fpl_manager_history` | Gameweek-by-gameweek history, past seasons, **chips already used** |
| `fpl_manager_picks` | The exact XI, bench order, captain and chip for a gameweek |
| `fpl_classic_league` | Classic league standings (paginated, 50/page) |
| `fpl_h2h_league` | Head-to-head standings with W/D/L |
| `fpl_my_team` | **Your own** squad — needs your session cookie |

## Reading picks correctly

`fpl_manager_picks` returns `position` 1–15 and a `multiplier`:

- **`position` 1–11** is the starting XI; **12–15** is the bench, **in order**
- **`multiplier` 2** is the captain, **3** a Triple Captain chip, **0** means benched

`automatic_subs` shows where FPL substituted a non-playing starter after the fact.

## Your own squad

```bash
export FPL_SESSION_COOKIE='pl_profile=...; sessionid=...'
```

`fpl_my_team` is the only place **`selling_price`** and **`purchase_price`** appear, and
that matters: FPL sells a risen player back at half the gain, so selling price is often
below `now_cost`. That difference decides whether a transfer is actually affordable.
It also carries `transfers.limit` (free transfers), `bank`, and chip availability.

Without the cookie you get a clean
`403 {"detail":"Authentication credentials were not provided."}` and the tool tells you
which variable to set. Every other tool here needs nothing.

**Getting the cookie is a browser job, not something to paste into a chat.** Log in at
fantasy.premierleague.com, open developer tools → Application → Cookies, and copy the
values into that environment variable yourself.

## Worked example: who should I captain?

1. `fpl_gameweeks` → the current gameweek and its **deadline**.
2. `fpl_fixtures` with that `event` → who plays whom, with difficulty 1–5.
3. `fpl_players` → form, xG, xA, ownership for the whole pool.
4. `fpl_player_detail` on the shortlist → their record against this opponent, and whether
   the fixture run after it is kind.
5. `fpl_set_piece_notes` → penalty duty, which is worth several points a season.
6. `theoddsapi` or `sportsbet` → anytime-scorer prices as an independent check on the
   model's view.

## See also

- [PremierLeague.md](PremierLeague.md) — official match data, keyless (join by team name)
- [ESPNFantasy.md](ESPNFantasy.md), [Sleeper.md](Sleeper.md) — other fantasy platforms
