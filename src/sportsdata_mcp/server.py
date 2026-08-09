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

from fastmcp import FastMCP

from . import __version__
from .config import Config, load_config
from .licence import resolve_licensed_groups, revalidation_loop, set_live_groups
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
            if reg is not None:
                await reg.aclose()
                log.info("closed %d provider HTTP client(s) on shutdown", len(reg.http_clients))

    # version is reported in the MCP `initialize` handshake so a client (the agents
    # platform) can detect a too-old data plane and warn on a contract mismatch.
    mcp = FastMCP("sportsdata-mcp", version=__version__, lifespan=lifespan)

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
    def list_tools_by_capability(capability: str | None = None) -> dict:
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

    # ── Always-on capability catalogue resource ──
    provider_index = {cap: [(e.provider, e.tool) for e in entries] for cap, entries in cap_index.items()}
    register_capabilities_resource(mcp, catalogue, provider_index)

    log.info(
        "registered %d tool(s) across enabled groups %s; %d resource(s)",
        len(registered.tools),
        sorted(enabled),
        len(registered.resources),
    )
    return mcp, registered


def serve_stdio(cfg: Config | None = None, specs_dir: Path | None = None) -> None:
    mcp, _registered = build_server(cfg, specs_dir)
    mcp.run()  # stdio transport
