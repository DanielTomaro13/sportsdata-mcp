# Entity Sport (`entitysport`) — cricket, ball-by-ball

**5 tools · BYO token · shapes unverified**

From [entitysport.com](https://www.entitysport.com). The deeper of the two cricket
providers in the BYO tier.

## How it differs from `cricketdata`

| | `cricketdata` | `entitysport` |
|---|---|---|
| Scorecards | yes | yes, with fall-of-wickets |
| **Ball-by-ball commentary** | no | **yes** |
| Live match state | basic | rich (`equation`, `live`) |
| Price | free tier, 100/day | paid |

If you are doing in-play work, the commentary endpoint is the reason to be here.

## Auth is a token, not a key

Entity Sport issues an **access token** from your key/secret pair, and the token — not
the key — goes in the request. Tokens expire, so if calls start failing after working
for a while, mint a new one.

```bash
export ENTITYSPORT_TOKEN=your_access_token
```

Minting is a separate authenticated call this server does not make; get the token from
their dashboard or their auth endpoint.

## Tools

| Tool | What it gives you |
|---|---|
| `entitysport_matches` | Live, upcoming and completed matches |
| `entitysport_match_info` | One match: squads, toss, state |
| `entitysport_match_scorecard` | Innings-by-innings batting and bowling, plus fall of wickets |
| `entitysport_match_commentary` | **Ball-by-ball** for one innings |
| `entitysport_competitions` | Competitions and tours |

## Two parsing traps

**`scores_full` vs `scores`.** The first is a display string (`"187/4 (20)"`), the
second the bare runs. Parsing the display string when you wanted the number is the usual
mistake.

**Commentary includes non-ball events.** Rows carry `event: "ball" | "overend" |
"wicket"`. Filter on `event` before counting deliveries, or your over count will drift.

## Status codes for `entitysport_matches`

`1` scheduled · `2` completed · `3` live · `4` cancelled

Pass `status=3` for "what is on right now" — the most common use of this provider.

## Walking a match

The four match tools chain in one direction, and the innings id is the link people miss:

```
entitysport_matches            → match_id
  └ entitysport_match_info     → squads, toss, current state
  └ entitysport_match_scorecard→ innings[].iid   ← the innings id
      └ entitysport_match_commentary(matchId, inningsId=iid)
```

`entitysport_match_commentary` needs **both** ids. There is no "give me the whole match's
commentary" call; you request one innings at a time.

## Fields worth knowing

**`game_state_str`** is the human summary of the situation ("Needs 45 runs in 30 balls"),
and **`equation`** on `match_info` is the structured version. For an in-play question,
those two are usually the whole answer.

**`format_str`** distinguishes `T20`, `ODI` and `Test`, which matters because the same
`status` means different things across formats — a Test at stumps is not a stalled feed.

**Fall of wickets** is `fows` on each innings, and it is how you reconstruct a collapse
that the summary score hides.

## Bowling and batting abbreviations

Same terse convention as the rest of cricket: `runs` / `balls_faced` / `fours` / `sixes`
/ `strike_rate` on a batter, `overs` / `maidens` / `runs` / `wickets` / `econ` on a
bowler. `how_out` is a display string, not a code.

## Rate and quota

Tokens are per-account and rate-limited by plan; this server caps at 2 rps. Because
commentary is one call per innings, a full Test match is a meaningful number of requests —
budget for it.

## See also

- [CricketData.md](CricketData.md) — free tier, scorecards, no commentary
- [CricketAustralia.md](CricketAustralia.md) — official, keyless, AU-only
