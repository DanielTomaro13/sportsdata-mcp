# sportsdata-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes sports-data APIs
(bookmakers, league/governing-body feeds, aggregators) as tools, configurable so
you only load the tool groups you need. A capability-tag system makes tools from
different providers interchangeable wherever they answer the same question — so
the model can compare odds across bookies or stats across data sources with one
discovery call.

The catalogue spans bookmakers, league/governing-body feeds, and stats
aggregators, and it keeps growing. New providers are added by dropping a YAML
spec into `src/sportsdata_mcp/specs/` — the engine needs no code changes — so
the exact provider and tool counts move over time. Run `sportsdata-mcp
list-groups` for the live inventory, and three meta-tools (group discovery,
capability lookup, resource listing) are always on regardless of what you
enable.

## Install

```bash
uvx sportsdata-mcp serve        # run without installing
# or
pip install sportsdata-mcp
```

## Quickstart

```bash
sportsdata-mcp version          # print version info
sportsdata-mcp list-groups      # see every available tool group
sportsdata-mcp lint             # validate the packaged specs
sportsdata-mcp doctor           # probe enabled groups for reachability + auth
sportsdata-mcp serve            # start the MCP stdio server (default command)
```

Enable tool groups with a config file or the `SPORTSDATA_MCP_GROUPS` env var:

```bash
SPORTSDATA_MCP_GROUPS="afl.public.core,sportsbet.racing,entain.graphql" sportsdata-mcp serve
```

See [`examples/`](./examples) for Claude Desktop / Claude Code config snippets,
a worked cross-bookie [odds-comparison prompt](./examples/comparator-prompt.md),
and an [NBA shot-chart + box-score walkthrough](./examples/nba-prompt.md) that
shows the `nba_stats_call` dispatcher pattern end to end.

## Configuration

Config is resolved in this order (first hit wins):

1. `--config <path>` flag
2. `$SPORTSDATA_MCP_CONFIG`
3. `./sportsdata-mcp.yaml`
4. `~/.config/sportsdata-mcp/config.yaml`
5. built-in defaults

```yaml
# sportsdata-mcp.yaml
enabled_groups:
  - afl.public.core
  - sportsbet.racing
  - entain.graphql

providers:                      # all optional; sensible defaults apply
  sportsbet:
    request_timeout_seconds: 30
    rate_limit_rps: 10          # sustained requests/sec (token bucket)
    max_response_bytes: 0       # 0 = no cap (default); set a positive byte count to guard context

secrets: {}                     # for authenticated providers; prefer env vars in prod
```

A provider whose auth reads `env: SOME_VAR` is satisfied by the real environment
variable first, then by a `secrets: { SOME_VAR: "..." }` entry of the same name
(a local-dev convenience — keep real secrets in the environment in production).

### Environment variables

| Variable | Effect |
| --- | --- |
| `SPORTSDATA_MCP_GROUPS` | Comma-separated group list; overrides `enabled_groups`. |
| `SPORTSDATA_MCP_CONFIG` | Path to a config file (see resolution order above). |
| `SPORTSDATA_MCP_MAX_BYTES` | Global response-size cap in bytes for every provider that doesn't set its own `max_response_bytes`. `0` (the default) means no cap. |

Meta-tools (`list_available_groups`, `list_tools_by_capability`, `list_resources`)
are always registered regardless of what is enabled, so a fresh install can still
guide the model to turn groups on.

**On the response-size cap.** There is **no cap by default** — every tool returns
whatever the upstream API sends. If you want to guard the model's context window you
can opt in to a cap: precedence is `providers.<id>.max_response_bytes` >
`SPORTSDATA_MCP_MAX_BYTES` > the default (`0`, unlimited). Be aware that very large
payloads (e.g. Sportsbet's full `*_event_markets` firehose, ~2 MB) won't fit in
Claude's ~200 K-token context regardless — for those, prefer a narrower tool such as
`sportsbet_sports_card` with `includeTopMarkets: true`.

## Tool groups

Run `sportsdata-mcp list-groups` for live counts and descriptions.

### AFL — `api.afl.com.au`

| Group | Tools | Notes |
|---|---:|---|
| `afl.public.core` | 22 | Competitions, seasons, rounds, fixtures, ladders, match stats |
| `afl.public.broadcasting` | 9 | Broadcast regions, guides, providers |
| `afl.public.content` | 8 | News/articles, videos, photos |
| `afl.premium.cfs` | 1 | CFS premium ops — needs the anonymous `x-media-mis-token` |
| `afl.premium.statspro` | 1 | StatsPro ops — needs the `x-media-mis-token` |
| `afl.premium.keyserver` | 1 | HLS video URL signing |

### Sportsbet — `sportsbet.com.au`

| Group | Tools | Notes |
|---|---:|---|
| `sportsbet.racing` | 15 | Race meetings, racecards, results, futures, SRMs |
| `sportsbet.sports` | 14 | Sport events, markets, prices, SGMs |
| `sportsbet.cross` | 12 | Live status, commentary, ladders, promos, video |
| `sportsbet.results` | 2 | Resulted events by date |
| `sportsbet.graphql` | 1 | Persisted GraphQL gateway (`apigw/sportsbook/graph`) |

### Entain / Ladbrokes — `ladbrokes.com.au`

| Group | Tools | Notes |
|---|---:|---|
| `entain.rest` | 13 | Navigation quick-links and REST surfaces |
| `entain.graphql` | 1 | 127 persisted GraphQL ops (`gql/router`) |
| `entain.cdn` | 1 | Contentful CMS entries (promotions, major-event nav) |

### PointsBet — `pointsbet.com.au`

| Group | Tools | Notes |
|---|---:|---|
| `pointsbet.sports` | 10 | Sports catalogue, competition/event feeds, full event markets, in-play, search |
| `pointsbet.racing` | 11 | Meetings, racecards, results, futures, SRMs, tips, form |
| `pointsbet.content` | 3 | Promotions, promo-code splash, + `pointsbet_content_call` over the static CMS/nav assets |

### TAB — `tab.com.au`

| Group | Tools | Notes |
|---|---:|---|
| `tab.racing` | 8 | Dates, meetings, racecards (fixed + parimutuel), form, next-to-go, jackpots, futures |
| `tab.sports` | 9 | Sports/competitions tree, full match markets + SGM, focused match markets, next-to-go, results, multi-builder |
| `tab.discovery` | 4 | Featured/live recommendations + `tab_cms_call` over the CMS content feeds |

### Unibet — `unibet.com.au`

| Group | Tools | Notes |
|---|---:|---|
| `unibet.racing` | 1 | `unibet_racing_call` — persisted-GraphQL: meetings, race cards, form, futures, specials |
| `unibet.sport` | 3 | `unibet_kambi_call` over the Kambi offering API (groups, events, bet offers, in-play, bet-builder) + live stats + odds ladder |

### BetR — `betr.com.au` (BlueBet platform)

| Group | Tools | Notes |
|---|---:|---|
| `betr.racing` | 8 | Next-to-jump, today's/grouped racecards, race card, form, fluctuations, movers |
| `betr.sport` | 7 | Event types, competition categories, event markets, match detail, popular SGMs |
| `betr.content` | 4 | Promotions + featured racing + popular market links |

### Pinnacle — `pinnacle.com` (sharp odds)

| Group | Tools | Notes |
|---|---:|---|
| `pinnacle.sports` | 9 | Sports/leagues, highlighted + live matchups, carousel, matchup detail, straight markets (American-odds prices) |
| `pinnacle.reference` | 4 | Enums, market-label dictionary, teaser definitions, API status |

### FanDuel — `fanduel.com` (US)

| Group | Tools | Notes |
|---|---:|---|
| `fanduel.racing` | 4 | `fanduel_racing_call` (full-query GraphQL: featured/today races + odds, single-race card, tracks, pools, talent picks) + messages/quick-links/promotions |
| `fanduel.sportsbook` | 2 | `fanduel_sb_call` (REST: event pages + markets, in-play, promos, configs via the `_ak` key) + live scores |

### NRL — `mc.championdata.com`

| Group | Tools | Notes |
|---|---:|---|
| `nrl.public.core` | 4 | Champion Data match centre: competitions, fixture, per-match player stats, app settings |

Plus the `nrl://stats/definitions` resource (dictionary of every NRL stat code).

### NBA — `cdn.nba.com` + `stats.nba.com`

| Group | Tools | Notes |
|---|---:|---|
| `nba.public.cdn` | 5 | Open CDN JSON: today's scoreboard, full schedule, live box score + play-by-play, odds |
| `nba.stats` | 2 | `nba_daily_lineups` + `nba_stats_call`, the dispatcher over the 137-endpoint `/stats/` API |

`nba_stats_call` fronts the whole stats.nba.com `/stats/` analytics surface (player/team
dashboards, box scores v2+v3, shot charts, play-by-play, leaders, standings, draft, hustle,
tracking, …). Browse every operation, its required params and its defaults in the
`nba://stats/operations` resource.

### ESPN — `espn.com` JSON feeds

| Group | Tools | Notes |
|---|---:|---|
| `espn.scores` | 5 | Site API convenience endpoints: scoreboard, teams, standings, game summary, news |
| `espn.site` | 1 | `espn_site_call` — team detail, rosters, schedules, injuries, depth charts, transactions, history, athlete news, groups, rankings (10 ops) |
| `espn.core` | 1 | `espn_core_call` — the canonical `$ref`-linked model: events/competitions, odds, win-probability, plays, venues, drafts, coaches, calendar, transactions (37 ops) |
| `espn.web` | 1 | `espn_web_call` — site-wide search + `common/v3` athlete views (7 ops) |
| `espn.cdn` | 1 | `espn_cdn_call` — the CDN live core feed: scoreboard/game/boxscore/playbyplay (4 ops) |

All ESPN tools are parametric over `sport` + `league` slugs (e.g. `football`/`nfl`,
`basketball`/`nba`, `soccer`/`eng.1`), so the five groups cover **every** league ESPN
carries. Browse each dispatcher's operations in its `espn://{site,core,web,cdn}/operations`
resource.

## Cross-provider comparison

Every tool is tagged with provider-agnostic **capability** slugs (e.g.
`sport.event_markets`, `racing.race_card`). Tools sharing a slug answer the same
question and are directly comparable across providers. The discovery flow:

1. `list_tools_by_capability("sport.event_markets")` → every enabled tool exposing it
2. Call each provider's tool concurrently with the resolved event ids
3. Compare the raw snapshots (schemas are **not** normalised — the model reconciles them)

See [`examples/comparator-prompt.md`](./examples/comparator-prompt.md) for a full
"compare Storm v Cowboys odds across bookies" walkthrough.

## Per-provider notes

- **Sportsbet** — anonymous public APIs; no secrets needed. REST events are keyed
  by integer `eventId`; a persisted-GraphQL gateway is exposed via
  `sportsbet_graphql_call` (browse `sportsbet://graphql/operations`).
- **Entain / Ladbrokes** — a persisted-GraphQL gateway; the model supplies an
  operation name + variables (discover them in `entain://graphql/operations`).
  Hashes can drift when the front-end bundle ships; refresh them with
  `sportsdata-mcp refresh-hashes entain`.
- **AFL** — `afl.public.*` is anonymous. `afl.premium.*` mints an anonymous
  `x-media-mis-token` automatically; some premium endpoints still return 401 for
  anonymous callers.
- **NRL** — the anonymous Champion Data match-centre CDN (`mc.championdata.com`),
  the same static JSON the official nrl.com match centre reads. No secrets, no
  cache-buster params needed. Resolve a `competitionId` from `nrl_competitions`
  (e.g. 12999 = 2026 NRL Premiership), a `matchId` from `nrl_fixture`, then pull
  per-player match stats from `nrl_match`; decode stat codes via
  `nrl://stats/definitions`.
- **NBA** — two surfaces, no secrets. `cdn.nba.com` is wide open (it even serves
  JSON as `text/plain`, which the client accepts). `stats.nba.com` sits behind
  Akamai, which black-holes any request missing a full browser header bundle — the
  spec ships that bundle in `provider.default_headers`, so it just works. Akamai also
  rate-limits hard, so the spec's `defaults` block throttles NBA to ~1 req/2.5 s,
  sets a 45 s timeout, and retries transient `429/5xx` with exponential backoff (all
  overridable via `providers.nba.*`). The `/stats/` family is one dispatcher
  (`nba_stats_call`): pick an `operation` (the path segment, e.g.
  `leaguedashplayerstats`) and pass `query_params` — each operation already carries
  NBA's full default param set, so you override only what matters. Most responses are
  column-oriented (`resultSets:[{name, headers, rowSet}]}`); v3 box scores are nested.
- **ESPN** — four public hosts, **no auth, no API key**: `site.api.espn.com` (scores,
  teams, standings, news, summaries), `sports.core.api.espn.com` (the canonical
  `$ref`-linked model — odds, win-probability, plays, venues, drafts, coaches),
  `site.web.api.espn.com` (search + athlete views) and `cdn.espn.com` (the live core
  feed, needs `?xhr=1`). Nearly every URL is `.../sports/{sport}/{league}/{resource}`,
  so the tools take `sport` + `league` as parameters and cover every ESPN league
  parametrically — NFL, NBA, MLB, NHL, college, soccer (`eng.1`, `esp.1`, …), golf,
  racing, tennis, MMA and more. Discovery: `espn_scoreboard(sport, league)` → an `event`
  id → `espn_game_summary` or the deep `espn_core_call(event_*)` ops. The spec throttles
  to ~5 req/s and retries transient `429/5xx` (overridable via `providers.espn.*`). Note
  the core API path uses `leagues/{league}` (plural); core list responses are lazy
  `{count, items:[{$ref}]}` envelopes — follow the refs for detail.
- **PointsBet** — anonymous public APIs, no secrets. `api.au.pointsbet.com` serves
  the sportsbook (sports + racing); `pointsbet.com.au` serves static CMS/nav assets
  via the `pointsbet_content_call` dispatcher. Sports discovery:
  `pointsbet_sport_competitions(sportKey)` → a competition key → `pointsbet_event(eventKey)`
  for the full market book. Racing: `pointsbet_racing_meetings(startDate, endDate)` →
  a `raceId` → `pointsbet_racing_race`. Many feeds return a top-level JSON array.
- **TAB (Tabcorp)** — anonymous public data, no secrets. `api.beta.tab.com.au`
  sits behind Akamai (the spec ships a browser header bundle + ~2.5 rps throttle,
  like NBA); `cmsapi.tab.com.au` serves CMS feeds via `tab_cms_call`. Every
  endpoint needs a `jurisdiction` (defaults to `NSW`). The API is HATEOAS and
  **name-based** — paths embed sport/competition/match/venue names with spaces
  (`…/AFL Football/competitions/AFL/matches/Adelaide v Geelong`), which the HTTP
  layer percent-encodes; pass raw names. Racing: `tab_racing_meetings(date)` →
  `raceType`+`venueMnemonic` → `tab_racing_race`. Sports:
  `tab_sport` → `tab_competition` → `tab_match` for the full market book.
- **Unibet** — anonymous AU data, no secrets, two surfaces. **Racing** is
  persisted-GraphQL (`unibet_racing_call`, the `graphql_persisted` dispatcher) at
  `rsa.unibet.com.au` — race ids are `eventKey`s like
  `202606040200.T.AUS.hawkesbury.1`; the endpoint enforces Apollo CSRF so a
  `Content-Type: application/json` header is sent. **Sport** is the **Kambi**
  offering API (`unibet_kambi_call` over `*.kambicdn.com`, market AU): group tree,
  events, bet offers, in-play, bet-builder. Browse ops in
  `unibet://{racing,sport}/operations`.
- **BetR** — anonymous AU data, no secrets. BetR runs on the **BlueBet** platform,
  so the API is `web20-api.bluebet.com.au` — a flat REST surface covering racing
  (next-to-jump, grouped racecards, race cards, form, fluctuations) and sport
  (event types → categories → markets, SGMs). The `betr.com.au` Next.js
  `_next/data/{buildHash}` blobs are skipped (fragile per-deploy hash; the API
  serves the same data).
- **Pinnacle** — anonymous, no key. The Arcadia "guest" API
  (`guest.api.arcadia.pinnacle.com`) — the open feed the web sportsbook reads.
  Sports only (sharp-odds book, no racing); prices are American odds. Flow:
  `pinnacle_sports` → `pinnacle_sport_matchups(sportId)` → `pinnacle_matchup_markets(matchupId)`.
  The full per-league matchup lists need an auth token (401 as guest), so the
  guest feed is exposed via the highlighted/live/carousel + single-matchup views.
- **FanDuel (US)** — anonymous US data, no secrets, two surfaces under one provider.
  **Racing** is the first **full-query GraphQL** provider: `fanduel_racing_call`
  POSTs the literal query text (the `graphql_query` dispatcher kind, sibling to the
  persisted-hash `graphql_persisted`), with boilerplate variables
  (`brand`/`product`/`device`/profile) baked as per-op `default_variables` — most
  calls need none, override only what varies (`{results: 12}`, `{trackCode, raceNumber}`).
  **Sportsbook** is REST (`fanduel_sb_call`) keyed by the static public `_ak` web key,
  region NJ. The two halves need different `Origin` headers, so the sportsbook
  dispatcher overrides `Origin` + `x-sportsbook-region` over the racing-origin
  provider default. Browse ops in `fanduel://{racing,sportsbook}/operations`.
  (US data — composes with other US sources via capability tags.)

## CLI reference

| Command | Purpose |
|---|---|
| `serve` | Start the MCP stdio server (default when no subcommand) |
| `list-groups` | Print every group with tool count + description |
| `lint` | Validate specs against the schema + capability catalogue (nonzero on failure) |
| `doctor` | Per-provider reachability + auth + REST-contract probe (nonzero on failure) |
| `refresh-hashes <provider>` | Refresh persisted-query hashes from the live front-end bundle (`--dry-run` to preview) |
| `version` | Print version info |

`-v` / `--verbose` enables DEBUG logging (and un-silences `httpx`/`httpcore`).

## Contributing

Adding a provider is a spec-only change in the common case:

1. Write `src/sportsdata_mcp/specs/<provider>.yaml` (copy an existing spec).
2. Tag each tool with capability slugs from `specs/_capabilities.yaml`; add a new
   slug there if none fits (two providers sharing a slug makes them comparable).
3. `sportsdata-mcp lint` — must pass.
4. `sportsdata-mcp doctor` (with the new groups enabled) — probes it live.
5. `pytest -m "not live"` — offline suite; drop the marker filter to run live tests.

```bash
pip install -e ".[dev]"
pytest -m "not live"
ruff check .
```

## License

MIT
