"""Spec → tool/resource registration.

Walks loaded specs and registers, for every tool whose group is enabled, a
FastMCP tool with a dynamically-built signature so FastMCP can derive the
JSON-schema the MCP client sees.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from .config import Config
from .dispatchers.graphql_persisted import make_graphql_dispatcher
from .dispatchers.graphql_query import make_graphql_query_dispatcher
from .dispatchers.templated_rest import make_templated_rest_dispatcher
from .errors import ToolError
from .licence import group_is_live
from .http_client import HTTPClient
from .resources.builders import (
    register_graphql_catalog,
    register_reference_resource,
    register_templated_rest_catalog,
)
from .spec import Dispatcher, Endpoint, Param, Spec

log = logging.getLogger("sportsdata_mcp.registry")


# ─── Python type mapping ───────────────────────────────────────────────

_PY_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "string_csv": list,
    # `json` = any JSON value. Typing it `dict` forced models to wrap arrays in objects
    # (observed live: Entain 500 "cannot unmarshal object into []uuid.UUID" because a
    # correct array could not pass the tool signature).
    "json": object,
    "object": dict,
}


def _python_type(p: Param) -> type:
    return _PY_TYPES.get(p.type, str)


# ─── Request building ──────────────────────────────────────────────────


def _interpolate_path(ep: Endpoint, kwargs: dict) -> str:
    url = ep.path
    for p in ep.params:
        if p.in_ == "path":
            value = kwargs.get(p.name)
            if value is None:
                raise ToolError(f"missing required path param '{p.name}'", recoverable=True)
            url = url.replace("{" + p.name + "}", str(value))
    return url


def _encode_query_value(p: Param, value: object) -> object:
    if p.type == "string_csv":
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value)
    if p.type == "json":
        return json.dumps(value, separators=(",", ":"))
    return value


def _build_query(ep: Endpoint, kwargs: dict) -> dict:
    out: dict[str, object] = {}
    for p in ep.params:
        if p.in_ != "query":
            continue
        value = kwargs.get(p.name)
        if value is None:
            continue
        out[p.wire_name] = _encode_query_value(p, value)
    return out


def _build_headers(ep: Endpoint, kwargs: dict) -> dict:
    out: dict[str, str] = {}
    for p in ep.params:
        if p.in_ != "header":
            continue
        value = kwargs.get(p.name)
        if value is None:
            continue
        out[p.wire_name] = str(value)
    return out


def _build_body(ep: Endpoint, kwargs: dict) -> dict | list | None:
    body_params = [p for p in ep.params if p.in_ == "body"]
    if not body_params:
        return None
    # A single `object` body param is sent as the whole body; otherwise merge by name.
    if len(body_params) == 1 and body_params[0].type == "object":
        return kwargs.get(body_params[0].name)
    out: dict[str, object] = {}
    for p in body_params:
        value = kwargs.get(p.name)
        if value is not None:
            out[p.name] = value
    return out


# ─── Descriptions ──────────────────────────────────────────────────────


def _describe(tool: Endpoint | Dispatcher) -> str:
    lines = [tool.summary.strip()]
    hint = getattr(tool, "response_hint", None)
    lines.append(f"\nReturns: {hint or '(JSON object)'}")
    examples = getattr(tool, "examples", None) or []
    if examples:
        lines.append(f"\nExample: {examples[0].description}")
    return "\n".join(lines)


# ─── Endpoint handler factory ──────────────────────────────────────────


def make_endpoint_handler(ep: Endpoint, http: HTTPClient) -> Callable:
    sig_params = [
        inspect.Parameter(
            p.name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=(inspect.Parameter.empty if p.required else p.default),
            annotation=_python_type(p),
        )
        for p in ep.params
    ]
    sig = inspect.Signature(parameters=sig_params)

    async def handler(**kwargs):
        url = _interpolate_path(ep, kwargs)
        query = _build_query(ep, kwargs)
        header = _build_headers(ep, kwargs)
        body = _build_body(ep, kwargs)
        return await http.request_json(
            method=ep.method,
            base=ep.base,
            url=url,
            params=query,
            headers=header,
            json_body=body,
            auth_key=ep.auth,
        )

    handler.__signature__ = sig  # type: ignore[attr-defined]
    # FastMCP/pydantic derive the JSON-schema from __annotations__, not __signature__,
    # so the per-param types must be mirrored here too.
    handler.__annotations__ = {p.name: _python_type(p) for p in ep.params} | {"return": dict}
    handler.__name__ = ep.name
    handler.__doc__ = _describe(ep)
    return handler


def make_dispatcher_handler(disp: Dispatcher, spec: Spec, http: HTTPClient) -> Callable:
    if disp.kind == "graphql_persisted":
        return make_graphql_dispatcher(disp, spec, http)
    if disp.kind == "graphql_query":
        return make_graphql_query_dispatcher(disp, spec, http)
    if disp.kind == "templated_rest":
        return make_templated_rest_dispatcher(disp, spec, http)
    raise ValueError(f"unknown dispatcher kind: {disp.kind}")


# ─── Transport-error guard ─────────────────────────────────────────────


def _guard(handler: Callable, tool_name: str, group: str) -> Callable:
    """Catch-all for transport-level failures, wrapped around every tool handler.

    `HTTPClient._decode` already turns HTTP-status / content-type problems into
    `ToolError`s, but a request that never completes (DNS failure, refused
    connection, read timeout) raises a raw `httpx` error. Left unhandled FastMCP
    masks it as an opaque ``Error calling tool`` string; here we convert it into
    an actionable, recoverable `ToolError` so the model can retry sensibly. Our
    own `ToolError`s pass through untouched — their envelope is already correct.

    Also enforces the live licence: if the tool's `group` is no longer granted (a
    mid-session cancellation/downgrade the revalidation loop has picked up), the call
    is refused. Unlicensed installs are inert (`group_is_live` always True).
    """

    @functools.wraps(handler)
    async def wrapped(**kwargs):
        if not group_is_live(group):
            raise ToolError(
                f"{tool_name}: this feed is not included in your current licence.",
                recoverable=False,
                code="NOT_LICENSED",
            )
        try:
            return await handler(**kwargs)
        except ToolError:
            raise
        except httpx.TimeoutException as e:
            raise ToolError(
                f"{tool_name}: the provider did not respond in time ({type(e).__name__}). "
                f"It may be slow or unreachable — retry shortly.",
                recoverable=True,
                code="UPSTREAM_TIMEOUT",
            ) from e
        except httpx.HTTPError as e:
            raise ToolError(
                f"{tool_name}: could not reach the provider ({type(e).__name__}: {e}). "
                f"Check network connectivity and retry.",
                recoverable=True,
                code="TRANSPORT_ERROR",
            ) from e

    # FastMCP/pydantic derive the JSON-schema from these, so mirror them onto the wrapper.
    wrapped.__signature__ = inspect.signature(handler)  # type: ignore[attr-defined]
    wrapped.__annotations__ = dict(getattr(handler, "__annotations__", {}))
    wrapped.__name__ = tool_name
    wrapped.__doc__ = handler.__doc__
    return wrapped


# ─── Registration ──────────────────────────────────────────────────────


@dataclass
class Registered:
    tools: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    http_clients: list[HTTPClient] = field(default_factory=list)

    async def aclose(self) -> None:
        for client in self.http_clients:
            await client.aclose()


def register_all(mcp, specs: list[Spec], cfg: Config) -> Registered:
    """Register every tool/resource whose group is in cfg.enabled_groups."""
    registered = Registered()
    enabled = set(cfg.enabled_groups)

    for spec in specs:
        provider = spec.provider
        # Only build a client for a provider that has at least one enabled group.
        provider_groups = {t.group for t in spec.all_tools()}
        if not (provider_groups & enabled):
            continue

        http = HTTPClient(provider, cfg)
        registered.http_clients.append(http)

        for endpoint in spec.endpoints:
            if endpoint.group not in enabled:
                continue
            handler = _guard(make_endpoint_handler(endpoint, http), endpoint.name, endpoint.group)
            mcp.tool(name=endpoint.name, description=_describe(endpoint))(handler)
            registered.tools.append(endpoint.name)

        for dispatcher in spec.dispatchers:
            if dispatcher.group not in enabled:
                continue
            handler = _guard(
                make_dispatcher_handler(dispatcher, spec, http), dispatcher.name, dispatcher.group
            )
            mcp.tool(name=dispatcher.name, description=_describe(dispatcher))(handler)
            registered.tools.append(dispatcher.name)
            if dispatcher.kind in ("graphql_persisted", "graphql_query"):
                register_graphql_catalog(mcp, dispatcher, spec)
            else:
                register_templated_rest_catalog(mcp, dispatcher)
            registered.resources.append(dispatcher.catalog_resource)

        for ref in spec.reference_resources:
            register_reference_resource(mcp, ref, http)
            registered.resources.append(ref.uri)

    return registered
