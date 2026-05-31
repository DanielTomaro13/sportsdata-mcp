# sportsdata-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes sports-data APIs
(bookmakers, league/governing-body feeds, aggregators) as tools, configurable so
you only load the tool groups you need. A capability-tag system makes tools from
different providers interchangeable wherever they answer the same question — so
the model can compare odds across bookies or stats across data sources with one
discovery call.

Three providers ship today — **AFL** (`api.afl.com.au`), **Sportsbet**, and
**Entain / Ladbrokes** — exposing **101 provider tools** across 14 groups, plus
3 always-on meta-tools. New providers are added by dropping a YAML spec into
`src/sportsdata_mcp/specs/`; the engine needs no code changes.

> Design notes and roadmap live in [`PLAN.md`](./PLAN.md).

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

See [`examples/`](./examples) for Claude Desktop / Claude Code config snippets
and a worked cross-bookie odds-comparison prompt.

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
    max_response_bytes: 512000  # responses over this → RESPONSE_TOO_LARGE

secrets: {}                     # for authenticated providers; prefer env vars in prod
```

`SPORTSDATA_MCP_GROUPS` (comma-separated) overrides `enabled_groups`. Meta-tools
are always registered regardless of what is enabled, so a fresh install can still
guide the model to turn groups on.

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
