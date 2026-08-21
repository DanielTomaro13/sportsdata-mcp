"""FastMCP bootstrap.

Builds the server from packaged specs + resolved config, registers the three
always-on meta-tools (`list_available_groups`, `list_tools_by_capability`,
`list_resources`), the `sportsdata://capabilities` resource, then every enabled
provider tool/resource via `registry.register_all`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal, cast

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, telemetry
from .config import Config, load_config
from .licence import resolve_licensed_groups, revalidation_loop, set_live_groups
from .prompts import register_prompts
from .registry import _READ_ONLY, Registered, register_all
from .resources.builders import register_capabilities_resource
from .spec import Dispatcher, Endpoint, Spec
from .spec_loader import expand_wildcard_groups, load_all_specs, load_capabilities

log = logging.getLogger("sportsdata_mcp.server")


# ─── Capability index (richer than spec_loader's, for the meta-tool) ────


def _args_required(tool: Endpoint | Dispatcher) -> list[str]:
    return [p.name for p in tool.params if p.required]


@dataclass
class _CapEntry:
    provider: str
    tool: str
    summary: str
    args_required: list[str] = field(default_factory=list)


def _build_capability_index(specs: list[Spec], enabled: set[str]) -> dict[str, list[_CapEntry]]:
    index: dict[str, list[_CapEntry]] = {}
    for spec in specs:
        for tool in spec.all_tools():
            if tool.group not in enabled:
                continue
            for cap_id in tool.capabilities:
                index.setdefault(cap_id, []).append(
                    _CapEntry(
                        provider=spec.provider.id,
                        tool=tool.name,
                        summary=tool.summary.strip().splitlines()[0] if tool.summary else "",
                        args_required=_args_required(tool),
                    )
                )
    return index


def _all_groups(specs: list[Spec]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for spec in specs:
        for tool in spec.all_tools():
            entry = out.setdefault(tool.group, {"provider": spec.provider.id, "tools": 0, "description": ""})
            entry["tools"] += 1
            if not entry["description"]:
                entry["description"] = (tool.summary.splitlines()[0] if tool.summary else "")[:120]
    return out


def _provider_auth(specs: list[Spec]) -> dict[str, dict]:
    """Per provider: which env-var secrets its auth needs, and whether they're
    REQUIRED (the provider won't work without them) or OPTIONAL (it works anonymously
    and a key only lifts limits — e.g. Kalshi). A client surfaces this as
    'ready / needs-key' without probing live. Env NAMES only — never values."""
    out: dict[str, dict] = {}
    for spec in specs:
        envs: set[str] = set()
        optional = False
        for auth in spec.provider.auth.values():
            kind = getattr(auth, "type", "none")
            if kind == "none":
                continue
            if kind == "kalshi_rsa":  # public data works anonymously; a key only raises limits
                optional = True
            for fname, value in auth.model_dump().items():
                if value and (fname == "env" or fname.endswith("_env")):
                    envs.add(str(value))
        out[spec.provider.id] = {
            "auth_env": sorted(envs),
            "auth_required": bool(envs) and not optional,
            "auth_optional": optional,
        }
    return out


# ─── Server build ──────────────────────────────────────────────────────


def build_server(cfg: Config | None = None, specs_dir: Path | None = None) -> tuple[FastMCP, Registered]:
    if cfg is None:
        cfg = load_config(specs_dir=specs_dir)

    specs = load_all_specs(specs_dir)
    catalogue = load_capabilities(specs_dir / "_capabilities.yaml" if specs_dir else None)
    # Wildcard: SPORTSDATA_MCP_GROUPS="*" enables every group. Used by clients that
    # deliberately want the full catalogue, e.g. an agent runtime filtering by
    # capability tags rather than by group.
    cfg.enabled_groups = expand_wildcard_groups(cfg.enabled_groups, specs)

    # ── Licence gate (commerce Phase 2) ──
    # When SPORTSDATA_LICENSE is set, the signed entitlement decides which feed groups
    # this server may serve (see licence.py). It is the *ceiling*: a configured
    # `enabled_groups` can narrow within the licence, but never exceed it. Opt-in (no
    # licence → no change) and fail-closed (licence set but unresolvable → no feeds).
    group_index = _all_groups(specs)
    provider_groups: dict[str, list[str]] = {}
    for gid, info in group_index.items():
        provider_groups.setdefault(info["provider"], []).append(gid)
    all_group_ids = set(group_index)
    licensed = resolve_licensed_groups(all_group_ids, provider_groups)
    if licensed is not None:
        cfg.enabled_groups = (
            sorted(set(cfg.enabled_groups) & set(licensed))
            if cfg.enabled_groups
            else licensed
        )
        log.info("licence gate active — serving %d group(s)", len(cfg.enabled_groups))
    # Seed the live-granted set the dispatch guard consults; a background task in the
    # lifespan refreshes it so a cancellation/downgrade takes effect mid-session.
    set_live_groups(licensed)

    # Operator off-switch (workbench global toggle): SPORTSDATA_MCP_DISABLED_PROVIDERS is a
    # comma-separated provider list to exclude entirely. Applied AFTER wildcard expansion +
    # the licence gate, so it works even when groups are "*" — a disabled provider's tools
    # simply never register. Narrows only; can never widen past the licence.
    _disabled = {p.strip() for p in os.environ.get("SPORTSDATA_MCP_DISABLED_PROVIDERS", "").split(",") if p.strip()}
    if _disabled:
        _drop = {g for prov in _disabled for g in provider_groups.get(prov, [])}
        if _drop:
            cfg.enabled_groups = [g for g in cfg.enabled_groups if g not in _drop]
            log.info("disabled providers %s → dropped %d group(s)", sorted(_disabled), len(_drop))

    enabled = set(cfg.enabled_groups)

    # The provider HTTP clients are created eagerly by register_all (below) so that
    # callers using build_server directly — e.g. tests — get a working server without
    # entering a lifespan. The lifespan exists purely to close those clients on a
    # graceful stdio shutdown; it reaches them through this holder.
    holder: dict[str, Registered] = {}

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[None]:
        revalidator: asyncio.Task | None = None
        if licensed is not None and os.environ.get("SPORTSDATA_LICENSE"):
            revalidator = asyncio.create_task(
                revalidation_loop(all_group_ids, provider_groups)
            )
        try:
            yield
        finally:
            if revalidator is not None:
                revalidator.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await revalidator
            reg = holder.get("registered")
            # Persist counters, then flush IF the operator opted in. Order matters: the
            # local record is the one the user owns, so it must survive a failed or
            # disabled flush. Neither step may raise — a shutdown that errors because of
            # telemetry would be an outstandingly bad trade.
            with contextlib.suppress(Exception):
                telemetry.save_local(telemetry.get())
            with contextlib.suppress(Exception):
                await telemetry.flush(telemetry.get(), enabled_providers=len({g.split(".")[0] for g in enabled}))
            if reg is not None:
                await reg.aclose()
                log.info("closed %d provider HTTP client(s) on shutdown", len(reg.http_clients))

    # version is reported in the MCP `initialize` handshake so a client (the agents
    # platform) can detect a too-old data plane and warn on a contract mismatch.
    # Said once here rather than repeated on every tool description: with 60 providers
    # there is heavy overlap, and the guidance a model needs about CHOOSING between them
    # is the same for all of them. Inlining it per tool cost ~12k tokens a session.
    instructions = (
        "Live sports data and cross-book betting odds across many providers.\n\n"
        "Choosing a tool: several providers often answer the same question. Every tool is "
        "tagged with provider-agnostic capability slugs (e.g. `sport.fixtures_by_date`, "
        "`stats.ladder`), and `list_tools_by_capability` lists the alternatives for one — "
        "use it when you need to compare providers or when the obvious tool returns "
        "nothing. `list_available_groups` shows what is enabled and what each provider "
        "needs.\n\n"
        "Prefer an official league feed (mlb, nhl, nba, premierleague, afl, nrl) for that "
        "league's own data, and a bookmaker or aggregator for prices. A tool whose "
        "description says its shape is unverified was documented from the vendor's docs "
        "rather than a live response — read the payload you actually receive.\n\n"
        "All tools are read-only GETs against third-party APIs. Some need a key you supply "
        "yourself; each such tool names the environment variable in its description."
    )
    mcp = FastMCP("sportsdata-mcp", version=__version__, lifespan=lifespan, instructions=instructions)

    groups = group_index
    provider_auth = _provider_auth(specs)
    cap_index = _build_capability_index(specs, enabled)

    # ── Meta-tools (always registered) ──
    @mcp.tool(annotations=_READ_ONLY)
    def list_available_groups() -> dict:
        """List every tool group across all providers, which are currently enabled,
        and each provider's auth requirements (env-var names + required/optional).

        On a fresh install (no groups enabled) this is the only functional tool, so
        the model can guide the user to enable what they want in sportsdata-mcp.yaml.
        """
        return {
            "enabled": sorted(enabled),
            "available": groups,
            "providers": provider_auth,
            "hint": "Edit sportsdata-mcp.yaml `enabled_groups` (or SPORTSDATA_MCP_GROUPS) and restart.",
        }

    @mcp.tool(annotations=_READ_ONLY)
    def list_tools_by_capability(
        capability: Annotated[
            str | None,
            Field(description="A capability slug, e.g. `sport.fixtures_by_date` or `stats.ladder`. "
                              "Omit to list every capability with the tools that expose it."),
        ] = None,
    ) -> dict:
        """Discover tools by capability — the unit of cross-provider comparison.

        Given a slug like 'sport.event_markets', returns every enabled tool exposing
        it across providers. Pass no argument for the full capability → tools map.
        """

        def _render(entries: list[_CapEntry]) -> list[dict]:
            return [
                {
                    "provider": e.provider,
                    "tool": e.tool,
                    "summary": e.summary,
                    "args_required": e.args_required,
                }
                for e in entries
            ]

        if capability is None:
            return {cap: _render(entries) for cap, entries in sorted(cap_index.items())}
        entries = cap_index.get(capability, [])
        return {
            "capability": capability,
            "tools": _render(entries),
            "hint": "Call all tools concurrently and compare the snapshots; do not assume normalised schemas.",
        }

    registered = register_all(mcp, specs, cfg)
    holder["registered"] = registered

    @mcp.tool(annotations=_READ_ONLY)
    def list_resources() -> dict:
        """List all registered MCP resources (capability map, dispatcher catalogues, reference data)."""
        return {
            "resources": ["sportsdata://capabilities", *registered.resources],
            "hint": "Read a resource to browse operations/lookups without spending a tool call.",
        }

    @mcp.tool(annotations=_READ_ONLY)
    def sportsdata_session_stats() -> dict:
        """How this server has performed for you THIS session: per-tool call counts,
        error rates, error codes, latency buckets, and how often a tool succeeded but
        returned nothing.

        Useful when a tool seems to be misbehaving — a 100% error rate with code
        AUTH_REQUIRED means a missing key, while a high `empty` count on a working tool
        usually means the upstream has no data for what was asked, not that the call is
        wrong.

        This is read from local counters. Nothing here has been sent anywhere.
        """
        snap = telemetry.get().snapshot()
        return {
            **snap,
            "telemetry_sharing": "on" if telemetry.is_enabled() else "off (local only)",
            "hint": "See docs/TELEMETRY.md for exactly what sharing would send.",
        }

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, openWorldHint=False)
    )
    def sportsdata_feedback(
        helpful: Annotated[bool, Field(description="False if the answer was wrong, empty or misleading; True if it was useful.")],
        tool: Annotated[str | None, Field(description="The tool the feedback is about, e.g. `nhl_schedule`. Omit for general feedback.")] = None,
        note: Annotated[str | None, Field(description="What went wrong, in a sentence. Free text, truncated to 500 characters, and sent VERBATIM if sharing is enabled — do not include anything private.")] = None,
    ) -> dict:
        """Report whether an answer from this server was useful.

        Call this when a tool gave a wrong, empty or misleading answer — especially if
        the response shape did not match its description, which is the failure mode the
        maintainers most need to hear about.

        Recorded locally. It is only ever transmitted if the operator has explicitly
        enabled sharing (SPORTSDATA_TELEMETRY=1 plus a configured endpoint), and `note`
        is sent verbatim, so do not put anything private in it.
        """
        telemetry.get().record_feedback(tool, helpful, note)
        shared = telemetry.is_enabled() and telemetry.endpoint() is not None
        return {
            "recorded": True,
            "will_be_shared": shared,
            "detail": (
                "Sharing is on: this will be included in the next flush."
                if shared
                else "Sharing is off — this stays on this machine. `sportsdata-mcp stats` shows it."
            ),
        }

    # ── Always-on capability catalogue resource ──
    provider_index = {cap: [(e.provider, e.tool) for e in entries] for cap, entries in cap_index.items()}
    register_capabilities_resource(mcp, catalogue, provider_index)

    # Only the prompts whose tools are actually enabled — offering "compare odds
    # across every book" to an official-stats-only install is a promise the server
    # can't keep, and the model would hunt for tools that aren't registered.
    prompt_names = register_prompts(mcp, enabled)

    log.info(
        "registered %d tool(s) across enabled groups %s; %d resource(s); %d prompt(s)",
        len(registered.tools),
        sorted(enabled),
        len(registered.resources),
        len(prompt_names),
    )
    return mcp, registered


def serve_stdio(cfg: Config | None = None, specs_dir: Path | None = None) -> None:
    mcp, _registered = build_server(cfg, specs_dir)
    mcp.run()  # stdio transport


#: HTTP-family transports FastMCP accepts. `stdio` is served by `serve_stdio`.
HTTPTransport = Literal["http", "sse", "streamable-http"]
HTTP_TRANSPORTS: tuple[str, ...] = ("http", "sse", "streamable-http")


def serve_http(
    cfg: Config | None = None,
    specs_dir: Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 3000,
    transport: str = "http",
) -> None:
    """Serve over HTTP (Streamable HTTP, or legacy SSE) instead of stdio.

    For remote clients, web apps and container hosting — stdio only works for a
    client that spawns the process itself.

    SECURITY: binds loopback by default and the caller must opt into anything wider.
    There is NO authentication on this endpoint: every enabled tool, and any
    credential in this process's environment (ESPN_FANTASY_COOKIE, DATAGOLF_KEY,
    X_BEARER_TOKEN…), is usable by anyone who can reach the port. Binding 0.0.0.0
    on a shared network hands those to that network; put it behind a reverse proxy
    that terminates TLS and authenticates first.
    """
    mcp, _registered = build_server(cfg, specs_dir)
    if host not in ("127.0.0.1", "::1", "localhost"):
        log.warning(
            "HTTP transport bound to %s:%s — this endpoint is UNAUTHENTICATED and exposes "
            "every enabled tool plus any provider credentials in this process. Put it behind "
            "an authenticating reverse proxy.",
            host,
            port,
        )
    if transport not in HTTP_TRANSPORTS:
        # `serve_http` is importable, so the CLI's own `click.Choice` is not the only
        # way in. Failing here names the valid options; passing an unknown string
        # through produced an error from deep inside FastMCP instead.
        raise ValueError(
            f"unsupported transport {transport!r} — expected one of {', '.join(HTTP_TRANSPORTS)}"
        )
    log.info("serving MCP over %s at http://%s:%s/mcp", transport, host, port)
    # The check above is what makes this narrowing sound.
    mcp.run(transport=cast(HTTPTransport, transport), host=host, port=port)
