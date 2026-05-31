"""Spec → MCP resource registrations.

Three categories:
  1. Capability catalogue   — sportsdata://capabilities (always registered)
  2. Dispatcher catalogues  — one per dispatcher (operation lists, no hashes)
  3. Reference data         — small static lookup tables, lazily populated + cached
"""

from __future__ import annotations

import json

from ..http_client import HTTPClient
from ..spec import CapabilityCatalogue, Dispatcher, ReferenceResource, Spec


def register_graphql_catalog(mcp, disp: Dispatcher, spec: Spec) -> None:
    ops = [
        {"name": op.name, "variables": op.variables, "verified": op.verified}
        for op in (spec.graphql.operations if spec.graphql else [])
    ]
    payload = json.dumps(
        {
            "provider": spec.provider.id,
            "dispatcher": disp.name,
            "operations": ops,
            "note": (
                f"Call {disp.name}(operation=<name>, variables={{...}}) to invoke. "
                f"Hashes are managed server-side."
            ),
        },
        indent=2,
    )

    @mcp.resource(disp.catalog_resource, mime_type="application/json")
    async def _catalog() -> str:
        return payload


def register_templated_rest_catalog(mcp, disp: Dispatcher) -> None:
    payload = json.dumps(
        {
            "dispatcher": disp.name,
            "operations": [op.model_dump() for op in disp.operations],
        },
        indent=2,
    )

    @mcp.resource(disp.catalog_resource, mime_type="application/json")
    async def _catalog() -> str:
        return payload


def register_capabilities_resource(
    mcp,
    catalogue: CapabilityCatalogue,
    provider_index: dict[str, list[tuple[str, str]]],
) -> None:
    """Always-on resource: the capability catalogue + which enabled providers expose each."""
    out = []
    for cap in catalogue.capabilities:
        providers = provider_index.get(cap.id, [])
        out.append(
            {
                "id": cap.id,
                "description": cap.description,
                "providers": [{"provider": p, "tool": t} for p, t in providers],
                "comparable": len({p for p, _ in providers}) >= 2,
            }
        )
    payload = json.dumps({"capabilities": out}, indent=2)

    @mcp.resource("sportsdata://capabilities", mime_type="application/json")
    async def _capabilities() -> str:
        return payload


def register_reference_resource(mcp, ref: ReferenceResource, http: HTTPClient) -> None:
    """Lazily-populated static lookup table. First read does one guarded GET;
    the result is cached in-process for the life of the server."""
    cache: dict[str, object] = {}

    @mcp.resource(ref.uri, mime_type=ref.mime_type)
    async def _ref() -> str:
        if "data" not in cache:
            cache["data"] = await http.request_json(
                method="GET", base=ref.base, url=ref.path, auth_key=ref.auth
            )
        return json.dumps(cache["data"], indent=2)
