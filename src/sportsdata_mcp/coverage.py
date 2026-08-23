"""`sportsdata-mcp coverage` — what actually works from where the user is.

This is deliberately not `doctor`. Doctor is a contract check for maintainers and CI: it
probes every endpoint of every enabled group, goes red on drift, and prints a wall of
URLs. Answering "will this be any use to me?" with that output is like answering "is my
car working?" with a compression test.

The question here is the one asked in the first sixty seconds after `uvx sportsdata-mcp
serve`, and getting it wrong is expensive in a specific way. A user outside Australia
whose first question lands on Sportsbet sees an error and concludes the server is broken,
when the honest answer was "that book is licensed for Australia and you are not there".
They uninstall over a misunderstanding. Saying so plainly keeps the users this can serve
and lets the others go without a bad taste — and a nil answer, delivered early, is worth
more than a vague one.

One cheap probe per provider, run concurrently. The probe is ground truth because it ran
from the user's own machine; `provider.region` is used only to EXPLAIN a failure, never
to predict one.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from .config import Config
from .http_client import HTTPClient
from .registry import _build_headers, _build_query, _interpolate_path
from .spec import Endpoint, Spec

Echo = Callable[[str], None]

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

# One probe per provider, and this long to answer. Deliberately short: this runs while
# someone is deciding whether to keep the server, not in CI. It is enforced here rather
# than through the client's own timeout because that one is per-provider configurable and
# can be 30s — fine for a tool call, far too long for sixty-odd of them in a row.
_TIMEOUT_S = 6.0
_CONCURRENCY = 12
# Display names run to 60+ chars ("ESPN Fantasy (fantasy football / baseball / …)"), which
# tears the columns apart. Truncate for the table; the id is still unique in the detail.
_NAME_W = 38

Status = Literal["ok", "blocked", "needs_key", "down", "unprobed"]


@dataclass
class ProviderStatus:
    """One provider's verdict, plus enough context to explain it."""

    id: str
    display_name: str
    status: Status
    tools: int
    region: list[str] | None = None
    detail: str = ""


@dataclass
class CoverageReport:
    results: list[ProviderStatus] = field(default_factory=list)

    def by_status(self, status: Status) -> list[ProviderStatus]:
        return sorted((r for r in self.results if r.status == status), key=lambda r: (-r.tools, r.id))

    @property
    def counts(self) -> Counter[str]:
        return Counter(r.status for r in self.results)

    @property
    def usable_tools(self) -> int:
        return sum(r.tools for r in self.results if r.status == "ok")


def _name(display_name: str) -> str:
    return display_name if len(display_name) <= _NAME_W else display_name[: _NAME_W - 1] + "…"


def _probe_endpoint(spec: Spec) -> Endpoint | None:
    """Pick the least demanding GET to knock on the door with.

    Endpoints with a required, undefaulted param are skipped: satisfying one means
    inventing a race id or a fixture id, and a 404 from a made-up id says nothing about
    whether the provider is reachable — which is the only question being asked.
    """
    candidates = [
        e for e in spec.endpoints
        if e.method == "GET" and not any(p.required and p.default is None for p in e.params)
    ]
    if not candidates:
        return None
    # Fewest params wins: the smallest surface is least likely to fail for a reason that
    # has nothing to do with reachability.
    return min(candidates, key=lambda e: len(e.params))


async def _probe(spec: Spec, cfg: Config, sem: asyncio.Semaphore) -> ProviderStatus:
    provider = spec.provider
    result = ProviderStatus(
        id=provider.id,
        display_name=provider.display_name,
        status="down",
        tools=len(spec.all_tools()),
        region=provider.region,
    )

    # A BYO-key provider has nothing to say without the key, and probing it would just
    # report an auth refusal as though it were a fault.
    if provider.requires_user_key:
        result.status = "needs_key"
        result.detail = "bring your own key"
        return result

    ep = _probe_endpoint(spec)
    if ep is None:
        # Every tool here is a dispatcher, or every endpoint needs an id we would have to
        # invent. Reporting that as "down" would be a confident wrong answer of exactly
        # the kind this command exists to prevent — Betfair and ESPN are fine, they just
        # cannot be knocked on without a race or a fixture in hand.
        result.status = "unprobed"
        result.detail = "needs an id to call — not probed"
        return result

    async with sem:
        http = HTTPClient(provider, cfg)
        try:
            args = {p.name: p.default for p in ep.params if p.default is not None}
            r = await asyncio.wait_for(
                http.request(
                    method=ep.method,
                    base=ep.base,
                    url=_interpolate_path(ep, args),
                    params=_build_query(ep, args),
                    headers=_build_headers(ep, args),
                    json_body=None,
                    auth_key=ep.auth,
                ),
                timeout=_TIMEOUT_S,
            )
        except TimeoutError:
            # A connection that hangs rather than refusing is what an edge geo-block
            # looks like from outside the region: the request never reaches anything
            # that could explain itself. Region metadata does the explaining instead.
            result.status = "blocked" if provider.region else "down"
            result.detail = "timed out"
            return result
        except Exception as e:  # noqa: BLE001 — one bad provider must not sink the report
            result.status = "blocked" if provider.region else "down"
            result.detail = type(e).__name__
            return result
        finally:
            await http.aclose()

    if r.status_code == 451:
        # 451 Unavailable For Legal Reasons is the one unambiguous geo-block on the wire.
        result.status = "blocked"
        result.detail = "HTTP 451"
    elif r.status_code in (403, 401) and provider.region:
        result.status = "blocked"
        result.detail = f"HTTP {r.status_code}"
    elif r.status_code >= 400:
        result.detail = f"HTTP {r.status_code}"
    else:
        result.status = "ok"
    return result


async def run_coverage(cfg: Config, specs: list[Spec]) -> CoverageReport:
    # Sixty-odd request log lines would bury the report they are meant to support. -v
    # still turns them back on, because the handler level is what we raise, not the
    # logger's own configuration.
    http_log = logging.getLogger("sportsdata_mcp.http")
    prior, http_log.disabled = http_log.disabled, not http_log.isEnabledFor(logging.DEBUG)
    try:
        return await _run(cfg, specs)
    finally:
        http_log.disabled = prior


async def _run(cfg: Config, specs: list[Spec]) -> CoverageReport:
    sem = asyncio.Semaphore(_CONCURRENCY)
    report = CoverageReport()
    report.results = list(await asyncio.gather(*(_probe(s, cfg, sem) for s in specs)))
    return report


def render(report: CoverageReport, echo: Echo) -> None:
    """Print the report in the order the reader needs it: what works, then why not."""
    counts = report.counts

    echo("")
    echo(f"{_BOLD}What works from here{_RESET}")
    echo(f"{_DIM}Probed {len(report.results)} providers from this machine, just now.{_RESET}")
    echo("")

    ok = report.by_status("ok")
    if ok:
        echo(f"{_GREEN}✓ {len(ok)} providers reachable{_RESET} "
             f"{_DIM}— {report.usable_tools} tools you can use right now{_RESET}")
        for r in ok[:12]:
            echo(f"    {_GREEN}✓{_RESET} {_name(r.display_name):<{_NAME_W}}{_DIM}{r.tools:>4} tools{_RESET}")
        if len(ok) > 12:
            echo(f"    {_DIM}… and {len(ok) - 12} more{_RESET}")
        echo("")

    blocked = report.by_status("blocked")
    if blocked:
        markets = sorted({m for r in blocked for m in (r.region or [])})
        echo(f"{_YELLOW}🌍 {len(blocked)} unreachable from your location{_RESET}")
        echo(f"    {_DIM}Licensed for {', '.join(markets) or 'another market'} and blocked outside it. "
             f"Nothing is broken,{_RESET}")
        echo(f"    {_DIM}and no key fixes it.{_RESET}")
        for r in blocked:
            echo(f"    {_YELLOW}🌍{_RESET} {_name(r.display_name):<{_NAME_W}}{_DIM}{r.tools:>4} tools · {r.detail}{_RESET}")
        echo("")

    needs_key = report.by_status("needs_key")
    if needs_key:
        n = sum(r.tools for r in needs_key)
        echo(f"{_CYAN}🔑 {len(needs_key)} need your own key{_RESET} {_DIM}— {n} further tools{_RESET}")
        echo(f"    {_DIM}`sportsdata-mcp connect` walks you through adding one.{_RESET}")
        echo("")

    unprobed = report.by_status("unprobed")
    if unprobed:
        n = sum(r.tools for r in unprobed)
        echo(f"{_DIM}• {len(unprobed)} not probed{_RESET} {_DIM}— {n} tools; these need a race or "
             f"fixture id to call,{_RESET}")
        echo(f"    {_DIM}so there is nothing to knock on. Not a fault.{_RESET}")
        echo("")

    down = report.by_status("down")
    if down:
        echo(f"{_RED}✗ {len(down)} did not answer{_RESET}")
        for r in down[:8]:
            echo(f"    {_RED}✗{_RESET} {_name(r.display_name):<{_NAME_W}}{_DIM}{r.detail}{_RESET}")
        if len(down) > 8:
            echo(f"    {_DIM}… and {len(down) - 8} more{_RESET}")
        echo(f"    {_DIM}A transient upstream is normal; a persistent one is worth an issue.{_RESET}")
        echo("")

    echo(f"{_BOLD}Summary:{_RESET} {counts['ok']} working · {counts['blocked']} out of region · "
         f"{counts['needs_key']} need a key · {counts['unprobed']} not probed · "
         f"{counts['down']} not answering")

    # The bottom line, and the whole reason this command exists: nobody should be left
    # guessing whether an empty answer meant "no data" or "wrong country".
    if blocked:
        echo("")
        echo(f"{_DIM}The out-of-region providers are Australian wagering operators. If you are not "
             f"betting into{_RESET}")
        echo(f"{_DIM}Australian markets, the stats, results and prediction-market tools are the part "
             f"built for you.{_RESET}")
