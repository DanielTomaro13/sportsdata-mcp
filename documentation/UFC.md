# UFC (`ufc`) — official ufc.com JSON:API

**9 tools · no key · shapes verified live**

Events, fight cards, fighters, rankings and the **full FightMetric statistics table** —
the same dataset ufcstats.com publishes, from the official source.

## Why not ufcstats.com

It's the obvious place to look, and it's a dead end. `ufcstats.com` serves a **JavaScript
proof-of-work bot challenge** — "Checking your browser…" plus a SHA-256 loop — with
`<meta name="robots" content="noindex">` and **zero data rows** in the HTML. Reading it
programmatically would mean solving that challenge in a JS runtime, which is building
bot-detection evasion. This project doesn't do that.

ufc.com turns out to be the better source regardless:

| | ufcstats.com | **ufc.com** |
|---|---|---|
| Access | JS proof-of-work, `noindex` | `robots.txt` permits these paths |
| Format | HTML only | `application/vnd.api+json` |
| Fight statistics | yes | **yes — same FightMetric data, same ids** |

## Rate limiting, and why it's slow on purpose

`ufc.com/robots.txt` asks for `crawl-delay: 15`. That directive targets crawlers walking
a site rather than a client making occasional API calls, but this provider is capped at
**0.5 requests/second** out of respect for it. Please don't raise it — a provider that
gets this server blocked helps nobody.

It's also a **CMS feature, not a product API**. Drupal's JSON:API module is exposed at
`/jsonapi`; UFC don't document it as a product, so it could change or close without
notice. That's normal for this catalogue, and the nightly drift check is what will
notice.

## JSON:API conventions — read this before parsing anything

This provider behaves unlike every other one here.

**1. The payload is nested.** Every response is `{data: [...], links: {...}}`, and the
fields live in `data[].attributes`, never at the top level.

**2. Related records are not inlined.** `include=athlete_stat` adds them to a **separate
top-level `included` array**, which you match back via
`data[].relationships.<name>.data.id`. This is the single biggest gotcha:

> **Without `include`, a fighter has no statistics at all.**

**3. Filters are bracketed** — `filter[title]=UFC 330`, or `filter[title][value]=X` plus
`filter[title][operator]=CONTAINS` for a partial match.

**4. Sorting takes a field name**, `-` prefixed to descend.

## The filter trap (verified, and it bites silently)

Filtering works on `node/*` resources (events, fights, athletes) and **does not work** on
the custom stat entities. `filter[fightmetric_id]` on `athlete_stat` returns **0 rows
rather than an error** — even for an id present on page 1.

That's the dangerous kind of failure: a model asks for a fighter's stats, gets an empty
list, and reports "no statistics available" for a fighter who has plenty. So those
parameters aren't exposed on the tools at all.

- **One fighter's stats** → `ufc_athlete` (resolves them through `include`; works)
- **Leaderboards across everyone** → `ufc_athlete_stats` (sorting works perfectly)

## Tools

| Tool | What it gives you |
|---|---|
| `ufc_events` | Events past and upcoming: card times per segment, venue, location |
| `ufc_event_card` | One event **with its full fight card** attached |
| `ufc_fights` | Individual bouts — both corners and the winner — back to UFC 1 |
| `ufc_search_athletes` | Find a fighter by partial name — **start here** |
| `ufc_athlete` | One fighter: bio, physicals, **plus full stats and ranking** |
| `ufc_athlete_stats` | The FightMetric table, sortable — all-time leaderboards |
| `ufc_rankings` | Divisional rankings with previous position and interim flags |
| `ufc_round_records` | Single-round record book |
| `ufc_jsonapi_index` | All 291 exposed resource types, for finding surfaces not wrapped here |

## The statistics, in full

`athlete_stat` carries 48 fields per fighter. What's actually in there:

**Striking volume and accuracy**
`sig_strikes_landed` · `sig_strikes_attempted` · `sig_strikes_accuracy`

**Strikes by position** — where the damage happens
`stand_str_land`/`_att` · `clinch_str_land`/`_att` · `ground_str_land`/`_att`

**Strikes by target**
`head_str_land`/`_att` · `body_str_land`/`_att` · `leg_str_land`/`_att`

**Grappling**
`takedowns_landed` · `takedowns_attempted` · `takedown_acuracy` · `takedown_defense` ·
`takedown_average` · `submission_average`

**Pace and defence**
`sig_str_land_min` · `sig_str_abs_min` · `sig_str_def` · `knockdown_average` ·
`avg_fight_time`

**Career**
`career_fights` · `career_wins` · `career_losses` · `career_draws` ·
`career_no_contest` · `win_ko` · `win_sub` · `win_dec` · `first_rd_fin` · `title_def` ·
`win_streak` · `former_champion` · `total_bonuses` · `total_performance_night` ·
`total_fight_night`

### Four things that will catch you

**`takedown_acuracy` is misspelled upstream** — one `c`. Spell it correctly and you get
nothing.

**Percentages and per-minute rates are strings**, not numbers: `"57.14"`, `"4.82"`.

**`avg_fight_time` is in seconds** — 626 means 10:26.

**The `*_average` fields are per 15 minutes**, the standard MMA convention, not per
fight.

## Worked example: is this fighter's striking as good as it looks?

1. `ufc_search_athletes` with a surname → the fighter's `fightmetric_id`.
2. `ufc_athlete` with the exact title → stats and ranking in one call.
3. Read `sig_str_land_min` against `sig_str_abs_min` — volume means little if they're
   absorbing as much as they land.
4. `stand_str_land` vs `ground_str_land` — a high total built on ground-and-pound is a
   different fighter from a high total built standing.
5. `ufc_athlete_stats` with `sort=-sig_strikes_landed` → where they sit all-time.
6. `apisports_mma_fights` or a bookmaker provider → what the market thinks of the next
   one.

## Identifiers

Three run through this API and they are not interchangeable:

- **`id`** — a JSON:API uuid, used for `include` resolution
- **`fightmetric_id`** — the FightMetric key; **joins athletes to stats, rankings and
  round records**, and is the same id space ufcstats.com uses
- **`drupal_internal__nid`** — the CMS node id, useful mainly for `path.alias`

Rankings and round records identify fighters by `fightmetric_id` **only** — no names — so
resolving one back to a person means a lookup via `ufc_search_athletes`.

## See also

- `apisports_mma_fights` — MMA beyond the UFC, BYO key
- `pinnacle`, `sportsbet`, `tab` — UFC prices
