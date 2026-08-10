# Telemetry

**Nothing is transmitted unless you turn it on. There is no default that sends.**

This document exists so you don't have to take that on faith — every claim below is
either checkable with a command or enforced by a test.

## The short version

| | |
|---|---|
| Recorded locally, always | Tool call counts, error rates, latency buckets |
| Transmitted | Only if `SPORTSDATA_TELEMETRY=1` **and** an endpoint is set |
| Never recorded, anywhere | Tool arguments, response bodies, API keys, paths, hostnames, IPs |

```bash
sportsdata-mcp telemetry --show-payload
```

That prints the exact JSON a transmission would contain. If the claims here and that
output ever disagree, the output is the truth — file an issue.

## Why there is any of this at all

Two questions get lumped together as "analytics", and they need completely different
answers:

**"Is anyone using this?"** — answered by `scripts/metrics.py`, from PyPI download stats
and GitHub traffic. That runs on the maintainer's machine, reads public data about the
package, and touches no user at all. It is the right tool for that question and it needs
no permission from anybody.

**"Does it actually work for them?"** — that one cannot be answered from outside. A tool
that 404s for every user, a provider whose upstream started returning empty arrays, a
spec whose required parameter is subtly wrong: none of it shows up in a download count.
It shows up as an error rate, and only where the tools actually run.

This catalogue has 736 tools across 60 providers, many of them undocumented endpoints
that can change without notice. The realistic alternative to an error rate is waiting for
someone to be annoyed enough to open an issue.

## Turning it on takes two deliberate acts

```bash
export SPORTSDATA_TELEMETRY=1                              # consent
export SPORTSDATA_TELEMETRY_ENDPOINT=https://your/collector # destination
```

Neither has a transmitting default. Set only the first and everything stays local — a
typo in the endpoint variable cannot cause a silent send somewhere unexpected, because
there is nowhere for it to fall back to.

**Consent is readable only from the environment, never from a config file.** That is
deliberate: a config file can be committed to a repo, pasted into a gist, or baked into a
Docker image someone else built. None of those is the person at the keyboard agreeing.

Ambiguous values fail closed — `1`, `true`, `yes`, `on` enable it; anything else,
including `maybe`, does not.

## What is sent, exactly

```json
{
  "schema": 1,
  "install_id": "a9f3…",            // random UUID, stored locally, derived from nothing
  "session_id": "52e6a169221c",
  "sent_at": "2026-08-10T05:14:10+00:00",
  "server_version": "0.23.1",
  "python": "3.13",
  "os": "Darwin",
  "providers_enabled": 41,
  "uptime_seconds": 1820,
  "calls": 37,
  "errors": 2,
  "tools": {
    "nhl_schedule":   {"calls": 12, "errors": 0, "empty": 0,
                       "latency": {"<250ms": 9, "<1s": 3}, "codes": {}},
    "apitennis_events": {"calls": 2, "errors": 2, "empty": 0,
                       "latency": {"<1s": 2}, "codes": {"AUTH_REQUIRED": 2}}
  },
  "feedback": []
}
```

That is the whole schema. Note what has no field to live in: no arguments, no results, no
URL, no query string, no hostname, no path, no key.

## What is never collected, and why each one matters

**Tool arguments.** This is the important one, and it is not hypothetical caution. The
arguments in this catalogue are frequently identifying: an ESPN Fantasy `leagueId`
identifies a specific league and everyone in it, a Sleeper `username_or_id` *is* a
username, and a search string is whatever the person typed. Recording tool names without
arguments is exactly the line between "which tools get used" and "what are they asking
about", and the second is none of our business.

The guarantee is structural rather than a filter. `Telemetry.record()` has no parameter
capable of accepting arguments or a response:

```python
def record(self, tool: str, *, ok: bool, seconds: float,
           code: str | None = None, empty: bool = False) -> None:
```

A filter can be bypassed by the next person to touch the call site. A signature cannot,
and a test asserts that signature exactly — adding `args` to it fails the build.

**Response bodies.** Never, not even sizes. The only thing derived from a response is a
boolean: was it empty. A tool that succeeds and returns nothing, call after call, is
usually broken in a way no error rate reveals — that is the entire reason the flag
exists.

**Keys, tokens, environment values.** Only a count of how many providers are enabled.

**Paths, hostnames, usernames, IP addresses.** The payload has no field for any of them.
The install id is a random UUID with nothing derived from the machine — not the hostname,
not a MAC address, not a hash of anything. Its only job is distinguishing "one install,
forty sessions" from "forty installs". Delete `~/.sportsdata-mcp/install-id` and you are
a new install, with no way to link the two.

**Latency is bucketed**, not exact: `<250ms`, `<1s`, `<3s`, `<10s`, `>=10s`. An exact
millisecond figure is a weak fingerprint of a network path; a bucket is enough to notice
a provider getting slow.

## The one field that carries free text

`sportsdata_feedback(helpful, tool, note)` lets a user or model report that an answer was
wrong or useless. `note` is free text, so it can contain anything the sender puts in it.

- It is **never transmitted** unless sharing is on.
- It is truncated to 500 characters.
- When sharing is on, it is sent **verbatim**.

The tool's own description says so, and its return value tells the caller whether that
particular note will be shared. Don't put anything private in it.

## What you get out of it, whether or not you share

```bash
sportsdata-mcp stats
```

Your own history: per-tool call counts, error rates, error codes and empty-result counts,
worst first. This reads local files and works identically with sharing off. The same data
is available to a model mid-session via the `sportsdata_session_stats` tool, which is
often the fastest way to diagnose "this tool keeps failing" — a 100% error rate with
`AUTH_REQUIRED` means a missing key, while a high `empty` count with no errors usually
means the upstream has no data for what was asked.

Local files live in `~/.sportsdata-mcp/` (override with `SPORTSDATA_STATE_DIR`):

```
~/.sportsdata-mcp/install-id    random UUID
~/.sportsdata-mcp/stats.json    last 50 sessions
```

`install-id` is only created the first time something actually needs it — enabling
sharing, or running `sportsdata-mcp telemetry`. If you never look at telemetry, the file
never exists.

Delete either at any time. Neither is uploaded, whatever the settings.

## Running a collector

There is no hosted endpoint. `SPORTSDATA_TELEMETRY_ENDPOINT` is a URL you choose, and the
payload is a plain JSON POST — any HTTP handler that appends to a file will do:

```python
import json

from fastapi import FastAPI, Request

app = FastAPI()


@app.post("/t")
async def collect(request: Request):
    payload = await request.json()
    with open("telemetry.jsonl", "a") as f:
        f.write(json.dumps(payload) + "\n")
    return {"ok": True}
```

Self-hosting is the point: the data is a diagnostic signal, not a product, and it should
live wherever the person generating it agreed to send it.

## Guarantees enforced by tests

`tests/unit/test_telemetry.py` pins all of this:

- sharing is off by default; ambiguous consent values fail closed
- an unset endpoint means no send **even when enabled**
- a disabled flush sends nothing **even with an endpoint set**
- a flush never raises — enabling this must not be able to break a session
- `record()` has exactly the parameters listed above, and none of the banned ones
- the payload contains no identifying substrings
- latency is bucketed, feedback notes are truncated, `empty` is only a boolean
- a read-only home degrades to an ephemeral id instead of crashing
