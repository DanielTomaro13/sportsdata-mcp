# Contributing

Contributions welcome — especially new provider specs and drift fixes.

## Setup

```bash
git clone https://github.com/DanielTomaro13/sportsdata-mcp.git
cd sportsdata-mcp
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Gates (CI runs exactly these)

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest -m "not live"   # offline suite
.venv/bin/python -m sportsdata_mcp.cli lint  # spec validation
```

Tests marked `live` hit real provider endpoints — run them only when your change
touches that provider: `pytest -m live -k <provider>`.

## Adding a provider

A provider is a YAML spec in `src/sportsdata_mcp/specs/` — no engine code needed.
Copy `_template.yaml`, probe the endpoints live, add capability tags, a doc page in
`documentation/`, and offline tests with recorded fixtures. `sportsdata-mcp doctor`
should pass for your groups. See any recent provider PR in the history for the shape.

## Ground rules

- Offline tests only in the default suite (recorded fixtures, no network).
- No secrets in code or fixtures — keys ride env vars declared in the spec's `auth`.
- Public/guest client keys baked into a provider's own website are fine to reference;
  note them as such in a comment.
- Respect the providers: sensible rate limits in specs, no auth bypasses, public
  data only.
