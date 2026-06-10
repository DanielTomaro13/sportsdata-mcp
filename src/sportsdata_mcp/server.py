"""FastMCP bootstrap.

Builds the server from packaged specs + resolved config, registers the three
always-on meta-tools (`list_available_groups`, `list_tools_by_capability`,
`list_resources`), the `sportsdata://capabilities` resource, then every enabled
provider tool/resource via `registry.register_all`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastmcp import FastMCP

from .config import Config, load_config
from .registry import Registered, register_all
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
    enabled = set(cfg.enabled_groups)

    # The provider HTTP clients are created eagerly by register_all (below) so that
    # callers using build_server directly — e.g. tests — get a working server without
    # entering a lifespan. The lifespan exists purely to close those clients on a
    # graceful stdio shutdown; it reaches them through this holder.
    holder: dict[str, Registered] = {}

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[None]:
        try:
            yield
        finally:
            reg = holder.get("registered")
            if reg is not None:
                await reg.aclose()
                log.info("closed %d provider HTTP client(s) on shutdown", len(reg.http_clients))

    mcp = FastMCP("sportsdata-mcp", lifespan=lifespan)

    groups = _all_groups(specs)
    cap_index = _build_capability_index(specs, enabled)

    # ── Meta-tools (always registered) ──
    @mcp.tool
    def list_available_groups() -> dict:
        """List every tool group across all providers and which are currently enabled.

        On a fresh install (no groups enabled) this is the only functional tool, so
        the model can guide the user to enable what they want in sportsdata-mcp.yaml.
        """
        return {
            "enabled": sorted(enabled),
            "available": groups,
            "hint": "Edit sportsdata-mcp.yaml `enabled_groups` (or SPORTSDATA_MCP_GROUPS) and restart.",
        }

    @mcp.tool
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

    @mcp.tool
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
