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
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

import httpx
from mcp.types import ToolAnnotations
from pydantic import Field

from . import dates, telemetry
from .classify import apply_classify
from .config import Config
from .dispatchers.graphql_persisted import make_graphql_dispatcher
from .dispatchers.graphql_query import make_graphql_query_dispatcher
from .dispatchers.templated_rest import make_templated_rest_dispatcher
from .errors import ToolError
from .http_client import HTTPClient
from .licence import group_is_live
from .project import apply_projection
from .resources.builders import (
    register_graphql_catalog,
    register_reference_resource,
    register_templated_rest_catalog,
)
from .spec import Dispatcher, Endpoint, Param, Spec

log = logging.getLogger("sportsdata_mcp.registry")

# Every tool in this server is a GET against a third-party API: it never mutates
# anything, the same args return the same answer (modulo the upstream's own live
# data), and the data lives outside this system. Declaring that lets clients skip
# the per-call confirmation prompt — with 500+ tools, being asked to approve each
# read is the difference between usable and unusable.
_READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)


def _annotations_for(tool) -> ToolAnnotations:
    """Annotations derived from the HTTP method, never assumed.

    `readOnlyHint` is a PROMISE a client acts on: a tool claiming it may be called
    without asking the user. Every tool in this catalogue was a GET when the constant
    above was written, so it was applied unconditionally — and the first write tool
    (Yahoo's sanctioned lineup PUT) inherited a claim that it does not change anything,
    which is exactly backwards for the one tool where confirmation matters most.
    """
    method = getattr(tool, "method", "GET").upper()
    declared = getattr(tool, "read_only", None)
    # A GraphQL *query* is a read that travels by POST, and this catalogue exposes no
    # mutations — so the transport verb says nothing about state here.
    is_graphql_read = getattr(tool, "kind", "") in ("graphql_persisted", "graphql_query")
    if declared is True or is_graphql_read or (declared is None and method == "GET"):
        return _READ_ONLY
    return ToolAnnotations(
        readOnlyHint=False,
        # PUT is idempotent by definition (setting the same lineup twice is the same
        # lineup); POST is not (two add/drops are two transactions).
        idempotentHint=method == "PUT",
        destructiveHint=True,
        openWorldHint=True,
    )


# ─── Python type mapping ───────────────────────────────────────────────

_PY_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "string_csv": list,
    # `string_list` = a list sent as REPEATED query params (httpx repeats a list value):
    # exclude[]=markets&exclude[]=prices, ids[]=1&ids[]=2. Distinct from string_csv,
    # which comma-joins into a single param.
    "string_list": list,
    # `json` = any JSON value. Typing it `dict` forced models to wrap arrays in objects
    # (observed live: Entain 500 "cannot unmarshal object into []uuid.UUID" because a
    # correct array could not pass the tool signature).
    "json": object,
    "object": dict,
}


def _python_type(p: Param) -> type:
    return _PY_TYPES.get(p.type, str)


def _annotated_type(p: Param):
    """The parameter's type CARRYING its description, enum and constraints.

    FastMCP derives each tool's JSON schema from `__annotations__` via pydantic, so a
    bare `int` produces `{"type": "integer"}` and nothing else — every `description:` we
    write in the spec was being dropped on the floor. The model then sees a parameter
    named `tags` with no hint about what a tag looks like, and the docs we maintain most
    carefully never reach the one reader that matters.

    `Annotated[T, Field(description=...)]` is what pydantic reads, so the schema gains
    `description` (and `enum`) for free.
    """
    base = _python_type(p)
    bits: list[str] = []
    if p.description:
        bits.append(p.description.strip())
    # The enum belongs in the schema proper, but repeating it in prose helps a model that
    # only reads descriptions — and costs a handful of tokens.
    if p.enum:
        allowed = ", ".join(str(v) for v in p.enum)
        if not p.description or not any(str(v) in p.description for v in p.enum):
            bits.append(f"One of: {allowed}.")
    if p.in_ == "path" and p.required:
        bits.append("Required — part of the URL path.")
    description = " ".join(bits).strip()
    if not description and not p.enum:
        return base
    field_kwargs: dict = {}
    if description:
        field_kwargs["description"] = description
    if p.enum:
        field_kwargs["json_schema_extra"] = {"enum": list(p.enum)}
    return Annotated[base, Field(**field_kwargs)]


# ─── Request building ──────────────────────────────────────────────────


def _interpolate_path(ep: Endpoint, kwargs: dict) -> str:
    url = ep.path
    for p in ep.params:
        if p.in_ == "path":
            value = kwargs.get(p.name)
            if value is None:  # caller omitted it — fall back to the declared default
                value = p.default
            if value is None:
                raise ToolError(f"missing required path param '{p.name}'", recoverable=True)
            url = url.replace("{" + p.name + "}", str(value))
    return url


def _encode_query_value(p: Param, value: object) -> object:
    if p.type == "string_csv":
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value)
    if p.type == "string_list":
        # Pass a list straight through — httpx emits it as repeated params. A scalar
        # is wrapped so a single value still produces one repeated-style param.
        return list(value) if isinstance(value, (list, tuple)) else [value]
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
        # A `json` header carries a JSON document, not a Python repr — str() would emit
        # single-quoted pseudo-JSON the upstream rejects (ESPN's `x-fantasy-filter`).
        out[p.wire_name] = json.dumps(value, separators=(",", ":")) if p.type == "json" else str(value)
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


def _auth_line(provider) -> str:
    """One line telling the model what this tool needs before it will work.

    An agent that knows a call needs API_TENNIS_KEY can say so instead of retrying, and
    one that knows a provider is keyless will not ask the user for a key it does not
    need. Both are questions a tool description should answer without a round trip.
    """
    if provider is None:
        return ""
    from .spec import auth_env_names

    envs = sorted(auth_env_names(provider))
    if provider.requires_user_key and envs:
        return f"\nAuth: needs your own key in {' or '.join(envs)}."
    if envs:
        return f"\nAuth: works without a key; {' or '.join(envs)} unlocks more if set."
    return "\nAuth: none needed."


def _alternatives_line(tool, provider, cap_index) -> str:
    """Which OTHER tools answer the same question.

    This catalogue has 60 providers and heavy overlap — several answer "fixtures for a
    date". Without this a model picks whichever it saw first, which is often not the best
    one for that sport. The capability tags already encode the equivalence; this just
    surfaces it where the choice is actually made.
    """
    if not cap_index or provider is None:
        return ""
    peers: list[str] = []
    for cap in getattr(tool, "capabilities", []) or []:
        for other_provider, other_tool in cap_index.get(cap, []):
            if other_provider != provider.id and other_tool not in peers:
                peers.append(other_tool)
    if not peers:
        return ""
    # Naming three of sixty-eight is worse than naming none: the three are whichever
    # sorted first, so the "suggestion" is really alphabetical bias dressed up as advice.
    # Name them only when the list is short enough to BE the answer; otherwise give the
    # count and point at the tool that can actually rank them.
    if len(peers) > 3:
        # Repeating "68 other tools answer this, go compare them" on 758 tools costs
        # ~12k tokens per session to say the same thing 758 times. It belongs ONCE, in
        # the server instructions, which is where it now lives.
        return ""
    return f"\nAlso answers this: {', '.join(peers)}."


def _describe(
    tool: Endpoint | Dispatcher,
    *,
    shapes_verified: bool = True,
    provider=None,
    cap_index: dict | None = None,
) -> str:
    lines = [tool.summary.strip()]
    hint = getattr(tool, "response_hint", None)
    lines.append(f"\nReturns: {hint or '(JSON object)'}")
    if not shapes_verified:
        # Tell the MODEL, not just the reader: this shape came from the vendor's docs
        # and was never confirmed against a live response, so it should read what it
        # actually received rather than trusting the sketch above.
        lines.append(
            "\nNOTE: this shape is from the vendor's documentation and has NOT been "
            "verified against a live response (we hold no key for this provider). "
            "Treat it as approximate — inspect the actual payload before relying on "
            "a field name."
        )
    examples = getattr(tool, "examples", None) or []
    if examples:
        ex = examples[0]
        lines.append(f"\nExample: {ex.description}")
        # Descriptions are built ONCE at registration, so a concrete date rendered here
        # would freeze at server start — stale within days on a long-running HTTP
        # deployment. `<today>` cannot rot and tells the model what to compute.
        if ex.params:
            shown = dates.render_for_display(ex.params)
            lines.append(f"  {json.dumps(shown, default=str)}")
    if auth := _auth_line(provider):
        lines.append(auth)
    if alts := _alternatives_line(tool, provider, cap_index):
        lines.append(alts)
    return "\n".join(lines)


# ─── Endpoint handler factory ──────────────────────────────────────────


def make_endpoint_handler(ep: Endpoint, http: HTTPClient) -> Callable:
    sig_params = [
        inspect.Parameter(
            p.name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=(inspect.Parameter.empty if p.required else p.default),
            annotation=_annotated_type(p),
        )
        for p in ep.params
    ]
    sig = inspect.Signature(parameters=sig_params)

    async def handler(**kwargs):
        url = _interpolate_path(ep, kwargs)
        query = _build_query(ep, kwargs)
        header = _build_headers(ep, kwargs)
        body = _build_body(ep, kwargs)
        raw = None
        if ep.request_body_format == "raw":
            # The single body param carries the document verbatim (Yahoo's XML writes).
            raw = next(
                (str(v) for p_, v in ((p_, kwargs.get(p_.name)) for p_ in ep.params)
                 if p_.in_ == "body" and v is not None),
                None,
            )
            body = None
        result = await http.request_json(
            method=ep.method,
            base=ep.base,
            url=url,
            params=query,
            headers=header,
            json_body=body,
            raw_body=raw,
            content_type=ep.request_content_type,
            auth_key=ep.auth,
            response_format=ep.response_format,
        )
        # Pure passthrough unless the endpoint opted in. Order matters: `classify` adds
        # a derived tag, then `project` reduces — so an endpoint can tag rows and still
        # ship a slim payload.
        if ep.classify:
            result = apply_classify(result, ep.classify)
        return apply_projection(result, pick=ep.response_pick, fields=ep.response_fields)

    handler.__signature__ = sig  # type: ignore[attr-defined]
    # FastMCP/pydantic derive the JSON-schema from __annotations__, not __signature__,
    # so the per-param types must be mirrored here too.
    handler.__annotations__ = {p.name: _annotated_type(p) for p in ep.params} | {"return": dict}
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


def _looks_empty(result) -> bool:
    """Did this call succeed but say nothing?

    Providers signal "no data" in several shapes — a bare [], an envelope whose only
    payload key is empty, a `results: 0`. Catching the common ones is enough for a
    signal; being exhaustive would mean knowing every provider's envelope, which is the
    kind of coupling that rots.
    """
    if result is None or result == [] or result == {}:
        return True
    if isinstance(result, dict):
        for key in ("data", "response", "results", "items", "games", "events", "matches"):
            if key in result and not result[key]:
                return True
    return False


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
        # Telemetry rides on this wrapper because it is the ONE place every tool call
        # passes through. Note what is available here and deliberately not recorded:
        # `kwargs` is right there, and never touched. `telemetry.record` has no parameter
        # that could accept it.
        started = time.perf_counter()
        try:
            result = await handler(**kwargs)
        except ToolError as e:
            telemetry.get().record(
                tool_name, ok=False, seconds=time.perf_counter() - started, code=e.code
            )
            raise
        except httpx.TimeoutException as e:
            telemetry.get().record(
                tool_name, ok=False, seconds=time.perf_counter() - started, code="UPSTREAM_TIMEOUT"
            )
            raise ToolError(
                f"{tool_name}: the provider did not respond in time ({type(e).__name__}). "
                f"It may be slow or unreachable — retry shortly.",
                recoverable=True,
                code="UPSTREAM_TIMEOUT",
            ) from e
        except httpx.HTTPError as e:
            telemetry.get().record(
                tool_name, ok=False, seconds=time.perf_counter() - started, code="TRANSPORT_ERROR"
            )
            raise ToolError(
                f"{tool_name}: could not reach the provider ({type(e).__name__}: {e}). "
                f"Check network connectivity and retry.",
                recoverable=True,
                code="TRANSPORT_ERROR",
            ) from e
        # "Empty" is a QUALITY signal, not a size measurement: a tool that succeeds and
        # returns nothing, call after call, is usually broken in a way no error rate
        # shows. Only the boolean is kept.
        telemetry.get().record(
            tool_name,
            ok=True,
            seconds=time.perf_counter() - started,
            empty=_looks_empty(result),
        )
        return result

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
        # close the process-wide DoH resolver's client too (a provider may have
        # created it lazily); harmless if none did
        from .dns import close_shared_resolver

        await close_shared_resolver()


def register_all(mcp, specs: list[Spec], cfg: Config) -> Registered:
    """Register every tool/resource whose group is in cfg.enabled_groups."""
    registered = Registered()
    enabled = set(cfg.enabled_groups)

    # Which other tools answer the same question. Built from the ENABLED set only — a
    # description pointing at a tool this server did not register sends the model hunting
    # for something that does not exist, which is worse than offering no alternative.
    cap_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for spec in specs:
        for tool in spec.all_tools():
            if tool.group in enabled:
                for cap in tool.capabilities or []:
                    cap_index[cap].append((spec.provider.id, tool.name))

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
            mcp.tool(
                name=endpoint.name,
                description=_describe(
                    endpoint, shapes_verified=provider.shapes_verified,
                    provider=provider, cap_index=cap_index,
                ),
                annotations=_annotations_for(endpoint),
            )(handler)
            registered.tools.append(endpoint.name)

        for dispatcher in spec.dispatchers:
            if dispatcher.group not in enabled:
                continue
            handler = _guard(
                make_dispatcher_handler(dispatcher, spec, http), dispatcher.name, dispatcher.group
            )
            mcp.tool(
                name=dispatcher.name,
                description=_describe(
                    dispatcher, shapes_verified=provider.shapes_verified,
                    provider=provider, cap_index=cap_index,
                ),
                annotations=_annotations_for(dispatcher),
            )(handler)
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
