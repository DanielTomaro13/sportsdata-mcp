# Adding a provider

This server is **spec-driven**: a provider is a single YAML file in
`src/sportsdata_mcp/specs/<provider>.yaml`. The engine reads it and registers one
MCP tool per endpoint — **no Python is needed** for the common case. Files whose name
starts with `_` (e.g. `_schema.yaml`, `_capabilities.yaml`) are not loaded as providers.

There are two playbooks below — **[adding a bookmaker](#a-adding-a-bookmaker)** and
**[adding a sports website / data API](#b-adding-a-sports-website--data-api)** — because
the two differ in auth, capability tags, response sizes, and how reliably they can be
contract-tested. They share the same workflow, which is covered first.

> The authoritative contract for the spec format is
> [`src/sportsdata_mcp/specs/_schema.yaml`](../src/sportsdata_mcp/specs/_schema.yaml)
> (it mirrors the pydantic models in `spec.py`). The capability catalogue is
> [`src/sportsdata_mcp/specs/_capabilities.yaml`](../src/sportsdata_mcp/specs/_capabilities.yaml).
> Copy an existing spec that resembles your target as a starting point.

---

## The workflow (every provider)

1. **Probe the API live first.** Open the site, watch the network tab (XHR/fetch), and
   replay the calls with `curl` until you know: the base URL(s), each endpoint's path,
   which params are required, the auth (if any), and the **exact JSON shape** that comes
   back. Never write a spec from a guess — probe it.

   ```bash
   curl -s "https://api.example.com/v1/teams?leagueId=1" | python3 -m json.tool | head
   ```

2. **Write the spec** — `src/sportsdata_mcp/specs/<provider>.yaml`. See the two
   playbooks for the shape and the field reference in `_schema.yaml`.

3. **Tag capabilities.** Every endpoint that answers a cross-provider question gets one
   or more capability slugs from `_capabilities.yaml`. Two providers sharing a slug
   become interchangeable via the `list_tools_by_capability` meta-tool. Add a new slug
   to `_capabilities.yaml` only if none fits; if it will only ever have one provider,
   mark it `single_provider: true` (otherwise `sportsdata-mcp lint` warns).

4. **Write `documentation/<Provider>.md`** — host(s), auth, the id model (how to get
   from a list to a detail call), a table of tools → paths → capabilities, and a
   "Cross-provider comparison" section. Point `provider.doc_url` at it.

5. **Add tests** — `tests/integration/test_<provider>.py` with an offline registration
   test plus a few `@pytest.mark.live` probes (xfail on `(MCPToolError, RuntimeError)`,
   skip on empty data). Copy an existing one.

6. **Add a contract row** — one entry in
   [`tests/contract/test_api_contracts.py`](../tests/contract/test_api_contracts.py) so
   the provider's documented response shape is checked on every PR (and locally). See
   [Contract rows](#contract-rows) for how to pick a stable seed.

7. **Run the gates:**

   ```bash
   ruff check .
   sportsdata-mcp lint                                            # validates the spec
   SPORTSDATA_MCP_GROUPS="<your.groups>" sportsdata-mcp doctor    # probes it live
   pytest -m "not live"                                           # offline suite (incl. the contract guard)
   pytest -m contract                                            # live shape checks
   ```

8. **Commit + push** (branch off `main` first if you're on it).

### Auth options

Set in `provider.auth.<key>` and referenced by endpoints via `auth: <key>`:

| `type` | Use when | Fields |
|---|---|---|
| `none` | Public endpoint, no key | — |
| `static_header` | A fixed key/token rides in a header (e.g. `X-API-Key`) | `header`, and `value` **or** `env` |
| `static_query` | A secret rides in a query param (e.g. Data Golf `?key=`) | `param`, and `value` **or** `env` |
| `afl_wmctok` | A token must be minted from a separate endpoint first | `mint_url`, `mint_headers`, `header` |

**Secrets never go in the spec.** Use `env: SOME_VAR` and source the value from the
environment (or a local `secrets:` config block). The committed YAML only names the env
var. A `403` is mapped to a `BLOCKED` error; a `401` triggers one auth re-fetch.

### Dispatchers (one tool over many calls)

For a big parametric family, model one dispatcher tool instead of dozens of endpoints:

- **`templated_rest`** — a family of REST paths selected by an `operation` dispatch
  param (e.g. the NBA stats endpoints). Lists its operations in a catalogue resource.
- **`graphql_persisted`** — an Apollo persisted-query gateway (operation → sha256 hash).
- **`graphql_query`** — a full-query GraphQL API (POSTs the literal query text).

See `_schema.yaml` for the dispatcher field layout and `entain`/`unibet`/`fanduel`/`nba`
for real examples.

### `defaults` block

Per-provider HTTP behaviour (all optional): `rate_limit_rps`, `request_timeout_seconds`,
`retry_statuses`, `max_retries`, `retry_backoff_seconds`. Be a good citizen — keep
`rate_limit_rps` modest (3–5) and set a generous `request_timeout_seconds` for endpoints
that return large payloads.

---

## A) Adding a bookmaker

Bookmaker APIs are the **odds layer**: competitions, events, markets, prices, in-play,
racing cards, futures, same-game/same-race multis, plus CMS/promo surfaces. They power
cross-book odds comparison.

### What to expect

- **Auth** is usually `none` (the site's own public XHR feeds) or a `static_header` API
  key baked into the page bundle (e.g. Pinnacle's `X-API-Key`, FanDuel's `_ak`). Don't
  paste a personal account token — model the *anonymous* key the website itself uses.
- **Geo / bot protection.** Most AU books (Sportsbet, TAB, BetR, PointsBet, Unibet,
  Entain, Betfair AU) block non-AU / datacenter IPs. They'll work from a local AU
  connection but **skip in CI** — that's expected and the contract test handles it.
  If even a local datacenter IP is blocked (e.g. Cloudflare), note it and move on.
- **Huge payloads.** A full `*_event_markets` response can be multiple MB. Prefer a
  focused "card" endpoint for the default path and consider a `max_response_bytes` cap.
- **Ephemeral ids.** Event/market ids change daily — fine for tools, but a problem for a
  *stable* contract seed (see below).

### Finding the API

Open the book in a browser, DevTools → Network → filter to `Fetch/XHR`, and click
around (a sport, a race meeting, an event). The JSON calls you see are the API. Note the
base host, the path template, the query params, and any required headers. Replay with
`curl` to confirm it works without cookies.

### Groups & capability tags

Bookmakers typically split into racing / sport / cross-or-content groups:

```
<book>.racing     <book>.sport(s)     <book>.cross | <book>.content
```

Common tags (from `_capabilities.yaml`):

| Surface | Capability tag |
|---|---|
| List of sports / competitions | `sport.competitions_list` |
| Competition page (events, futures) | `sport.competition_screen` |
| One event's markets + prices | `sport.event_markets` |
| Live / last prices | `sport.prices` |
| In-play / live events | `sport.in_play` |
| Same-game multi suggestions | `sport.same_game_multi` |
| Race meetings for a date | `racing.meetings_by_date` |
| A single racecard | `racing.race_card` |
| Race results / dividends | `racing.race_results` |
| Next races to jump | `racing.next_to_jump` |
| Futures / outright markets | `racing.futures` / — |
| Same-race multi | `racing.same_race_multi` |
| Promos / CMS cards | `content.promo` |

The whole point is composition: tag your `*_event_markets` and price feeds with
`sport.event_markets` / `sport.prices` so the model can line your book up against
Pinnacle, Betfair, Data Golf, etc. in one `list_tools_by_capability` call.

### Skeleton

```yaml
spec_version: 1

provider:
  id: examplebook
  display_name: "ExampleBook (examplebook.com.au)"
  doc_url: "https://github.com/DanielTomaro13/sportsdata-mcp/blob/main/documentation/ExampleBook.md"
  base_urls:
    default: https://api.examplebook.com.au
  default_headers:
    User-Agent: "Mozilla/5.0 (compatible; sportsdata-mcp/0.1)"
    Accept: "application/json"
  auth:
    default:
      type: none           # or static_header with the page bundle's anonymous key
  defaults:
    rate_limit_rps: 3
    request_timeout_seconds: 30
    retry_statuses: [429, 500, 502, 503, 504]
    max_retries: 2
    retry_backoff_seconds: 0.5

endpoints:
  - name: examplebook_sports
    group: examplebook.sport
    capabilities: [sport.competitions_list]
    summary: "Sports / competitions catalogue."
    base: default
    path: /v1/sports
    auth: default
    response_hint: "[{id, name, competitionCount}]  (top-level array)"

  - name: examplebook_event_markets
    group: examplebook.sport
    capabilities: [sport.event_markets, sport.prices]
    summary: "All markets + selections + prices for one event (large)."
    base: default
    path: /v1/events/{eventId}/markets
    auth: default
    params:
      - { name: eventId, in: path, type: integer, required: true, description: "Event id." }
    response_hint: "{event, markets:[{id, name, selections:[{name, price}]}]}"
```

> **CSV params:** if an endpoint takes a comma-separated list (e.g. `marketIds=1,2,3`),
> use `type: string_csv` — the model passes a list and the engine serialises it.

---

## B) Adding a sports website / data API

These are the **data layer**: fixtures, results, scorecards/boxscores, play-by-play,
standings, player & team stats, schedules, draft, content. Examples already in the repo:
MLB (statsapi.mlb.com), OpenF1, ESPN, NBA, NRL, AFL, Cricket Australia, Data Golf.

### What to expect

- **Auth** is usually `none` — these are public global APIs. Some want a harmless
  response-shape flag (Cricket Australia's `jsconfig=eccn:true`, carried as a default
  param) or a personal key in a query param (Data Golf → `static_query` from
  `DATAGOLF_KEY`). A few sit behind multiple base URLs (MLB's `/api/v1` vs the live
  `/api/v1.1`) — model each as a named entry in `base_urls`.
- **Stable, global, reachable.** They generally work from CI, so their contract rows
  actually run there (unlike the geo-blocked books).
- **An id model.** Almost always *list → detail*: a catalogue/schedule call returns ids
  that you feed to a detail call. Document it explicitly, e.g.
  `mlb_schedule` → `gamePk` → `mlb_boxscore`; `cricketaustralia_fixtures` → `fixtureId`
  → `cricketaustralia_scorecard` → `playerIds` → `cricketaustralia_players`.
- **Watch payload size.** High-frequency feeds (telemetry, full play-by-play) can be
  huge — require the narrowing params (e.g. OpenF1 telemetry requires `session_key` +
  `driver_number`). Expose the upstream's enrichment knobs where useful (MLB's
  `hydrate`, a `fields` filter).

### Groups & capability tags

Group by surface, e.g. `<site>.reference`, `<site>.schedule`, `<site>.game`,
`<site>.stats`, `<site>.content`. Common tags:

| Surface | Capability tag |
|---|---|
| Team / player / venue / season catalogues | `ref.teams` / `ref.players` / `ref.venues` / `ref.seasons` |
| Coaches | `ref.coaches` |
| Fixtures / schedule by date | `sport.fixtures_by_date` |
| Single game box score | `sport.match_boxscore` |
| Scoreboard / period state | `sport.match_score` |
| Full single-event detail | `sport.match_detail` |
| Play-by-play log | `stats.play_by_play` |
| Win-probability series | `stats.win_probability` |
| Per-player match / season / career / game-log | `stats.player_match` / `stats.player_season` / `stats.player_career` / `stats.player_game_log` |
| Per-team season stats | `stats.team_season` |
| Standings / ladder | `stats.ladder` |
| Season leaders | `stats.leaders_season` |
| Advanced metrics (SG, telemetry, tracking) | `stats.advanced_metrics` |
| Roster transactions | `sport.transactions` |
| Draft picks | `sport.draft` |
| Video / news content | `content.video` / `content.news` |

If your site adds a second provider to a tag that was `single_provider: true`, **remove
that flag** in `_capabilities.yaml` (e.g. MLB joining ESPN un-flagged `ref.coaches`,
`sport.transactions`, `stats.win_probability`).

### Skeleton

```yaml
spec_version: 1

provider:
  id: examplesport
  display_name: "ExampleSport (statsapi.example.com)"
  doc_url: "https://github.com/DanielTomaro13/sportsdata-mcp/blob/main/documentation/ExampleSport.md"
  base_urls:
    default: https://statsapi.example.com/api/v1
    live: https://statsapi.example.com/api/v1.1   # if a surface needs a second version/host
  default_headers:
    User-Agent: "Mozilla/5.0 (compatible; sportsdata-mcp/0.1)"
    Accept: "application/json"
  auth:
    default:
      type: none
  defaults: { rate_limit_rps: 5, request_timeout_seconds: 30, retry_statuses: [429, 500, 502, 503, 504], max_retries: 2, retry_backoff_seconds: 0.5 }

endpoints:
  - name: examplesport_schedule
    group: examplesport.schedule
    capabilities: [sport.fixtures_by_date]
    summary: "Games by date (each carries gameId + score)."
    base: default
    path: /schedule
    auth: default
    params:
      - { name: date, in: query, type: string, description: "YYYY-MM-DD." }
    response_hint: "{dates:[{date, games:[{gameId, teams, status}]}]}"

  - name: examplesport_boxscore
    group: examplesport.game
    capabilities: [sport.match_boxscore, stats.player_match]
    summary: "Full box score for one game."
    base: default
    path: /game/{gameId}/boxscore
    auth: default
    params:
      - { name: gameId, in: path, type: integer, required: true, description: "Game id (from the schedule)." }
    response_hint: "{teams:{home:{players, teamStats}, away:{...}}}"
```

---

## Contract rows

Every provider should have **at least one** row in `tests/contract/test_api_contracts.py`
so its documented response shape is regression-checked. The test:

- **FAILS** on a real break — the API responded `200` but the documented keys are gone,
  or it returned `400/404/405/410/422` (your path/params are wrong).
- **SKIPS** on anything environmental — network error, `5xx`, `401/403/429`, geo-blocks,
  a non-JSON block page, a missing API key, or an empty feed.

So a geo-blocked book simply skips in CI but still gives you **local** regression value
when you run `pytest -m contract` from a reachable connection. An offline guard
(`test_contract_table_is_well_formed`) fails loudly if a row names a tool that doesn't
exist — so a rename can't silently drop coverage.

**Pick a schedule-independent seed.** The params are hard-coded, so choose something that
won't drift:

- A catalogue/reference call with no params (`mlb_teams`, `tab_sports`, `betr_event_types`).
- A typed root, not a live id (`betfair_navigation` with `nodeIds=["EVENT_TYPE:7"]`, the
  Horse Racing root — stable; **not** today's `marketIds`).
- A fixed historical id for detail calls (e.g. a 2025 MLB `gamePk`), so the shape is
  pinned to data that won't disappear.

A row is `Contract(tool, params, top_keys, list_at, item_keys)`:

```python
# object with required top-level keys:
Contract("examplesport_schedule", {"date": "2025-09-01"}, ("dates",)),
# object whose `teams` value is a list whose items must have these keys:
Contract("mlb_teams", {"sportId": 1}, ("teams",), "teams", ("id", "name", "abbreviation")),
# top-level array (list_at="") whose items must have these keys:
Contract("tab_sports", {}, list_at="", item_keys=("name",)),
```

Verify it before committing:

```bash
pytest -m "not live" tests/contract/         # the offline guard (tool exists, row well-formed)
pytest -m contract -k examplesport           # the live shape check
```

---

## Checklist

- [ ] Probed every endpoint live; confirmed paths, required params, auth, and shapes.
- [ ] `src/sportsdata_mcp/specs/<provider>.yaml` written; secrets via `env:` only.
- [ ] Capabilities tagged from `_capabilities.yaml` (new tag added + `single_provider`
      handled if needed).
- [ ] `documentation/<Provider>.md` written; `doc_url` points at it.
- [ ] README group table row added.
- [ ] `tests/integration/test_<provider>.py` (registration + live probes).
- [ ] Contract row in `tests/contract/test_api_contracts.py` with a stable seed.
- [ ] `ruff check .`, `sportsdata-mcp lint`, `sportsdata-mcp doctor`, `pytest -m "not live"`,
      `pytest -m contract` all green.
