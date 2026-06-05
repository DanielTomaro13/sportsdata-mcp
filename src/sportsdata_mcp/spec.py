"""Pydantic models for provider specs and the capability catalogue."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─── Auth ──────────────────────────────────────────────────────────────


class AuthNone(BaseModel):
    type: Literal["none"] = "none"


class AuthStaticHeader(BaseModel):
    type: Literal["static_header"]
    header: str
    value: str | None = None
    env: str | None = None


class AuthStaticQuery(BaseModel):
    # Like static_header but the secret rides in a query parameter (e.g. Data Golf's
    # `?key=`). The value comes from an env var (preferred) or a literal.
    type: Literal["static_query"]
    param: str
    value: str | None = None
    env: str | None = None


class AuthAFLWMCTok(BaseModel):
    type: Literal["afl_wmctok"]
    mint_url: str
    mint_headers: dict[str, str] = Field(default_factory=dict)
    header: str = "x-media-mis-token"


AuthSpec = Annotated[
    AuthNone | AuthStaticHeader | AuthStaticQuery | AuthAFLWMCTok,
    Field(discriminator="type"),
]


# ─── Provider ──────────────────────────────────────────────────────────


class HashRefresh(BaseModel):
    bundle_host: str
    bundle_url_pattern: str


class ProviderDefaults(BaseModel):
    """Spec-declared request-tuning defaults for a provider.

    These let a provider ship sane throttle/timeout/retry settings without the
    operator having to configure them. Precedence at request time:
    ``providers.<id>.<key>`` (user config) > this block > engine defaults.
    A ``None`` here means "no spec opinion — fall through to the engine default".
    """

    model_config = ConfigDict(extra="forbid")

    rate_limit_rps: float | None = None
    request_timeout_seconds: float | None = None
    burst: int | None = None
    # Transient statuses to retry (in addition to the always-on single 401 auth-refetch).
    # Empty list (the default) preserves the historical "no status retries" behaviour.
    retry_statuses: list[int] = Field(default_factory=list)
    max_retries: int = 0
    retry_backoff_seconds: float = 0.5


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str
    doc_url: str | None = None
    base_urls: dict[str, str]
    default_headers: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, AuthSpec] = Field(default_factory=lambda: {"default": AuthNone()})
    hash_refresh: HashRefresh | None = None
    defaults: ProviderDefaults = Field(default_factory=ProviderDefaults)


# ─── Endpoint params ───────────────────────────────────────────────────

ParamLocation = Literal["path", "query", "header", "body", "dispatch"]
ParamType = Literal["string", "integer", "number", "boolean", "string_csv", "json", "object"]


class Param(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    in_: ParamLocation = Field(alias="in")
    type: ParamType
    required: bool = False
    default: object | None = None
    description: str = ""
    enum: list[object] | None = None


class Example(BaseModel):
    description: str
    params: dict[str, object]


# ─── Endpoint ──────────────────────────────────────────────────────────


class Endpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    group: str
    capabilities: list[str] = Field(default_factory=list)
    summary: str
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"] = "GET"
    base: str = "default"
    path: str
    auth: str = "default"
    params: list[Param] = Field(default_factory=list)
    response_hint: str | None = None
    examples: list[Example] = Field(default_factory=list)

    @model_validator(mode="after")
    def _path_params_required(self) -> "Endpoint":
        # Match {name} anywhere in the path — including placeholders carrying a suffix
        # like `{eventId}.json` (Kambi), which a whole-segment check would miss.
        path_param_names = set(re.findall(r"\{(\w+)\}", self.path))
        declared = {p.name for p in self.params if p.in_ == "path"}
        missing = path_param_names - declared
        if missing:
            raise ValueError(f"endpoint '{self.name}' has path params {missing} not declared in params[]")
        for p in self.params:
            if p.in_ == "path" and p.name in path_param_names:
                p.required = True
        return self


# ─── Dispatchers ──────────────────────────────────────────────────────


class GraphQLOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    # Persisted-query providers (graphql_persisted) carry a sha256 hash; full-query
    # providers (graphql_query) carry the literal query text instead. Exactly one is
    # used per dispatcher kind.
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    query: str | None = None
    variables: str = ""
    # Boilerplate variables merged *under* caller-supplied ones (graphql_query only).
    # Lets a full-query op carry constants like {brand: FDR, product: TVG5} so the
    # model only sends what actually varies.
    default_variables: dict[str, object] = Field(default_factory=dict)
    verified: bool = False


class TemplatedOperation(BaseModel):
    # extra="forbid" turns a spec typo (e.g. `query_defualts:`) into a lint failure
    # instead of a silently-dropped key that yields wrong defaults at runtime.
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    path_params: list[str] = Field(default_factory=list)
    query_params: list[str] = Field(default_factory=list)
    # Default query values merged under any caller-supplied query_params. Many
    # stats.nba.com endpoints 400 unless the full (mostly-empty) param set is sent,
    # so the spec carries those defaults and the caller overrides only what matters.
    query_defaults: dict[str, str] = Field(default_factory=dict)
    summary: str = ""


class Dispatcher(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    group: str
    capabilities: list[str] = Field(default_factory=list)
    kind: Literal["graphql_persisted", "graphql_query", "templated_rest"]
    summary: str
    method: Literal["GET", "POST"] = "GET"
    base: str | None = None
    endpoint: str | None = None
    auth: str = "default"
    default_headers: dict[str, str] = Field(default_factory=dict)
    catalog_resource: str
    # `params` documents the dispatcher's own inputs (operation, variables/path_params/
    # query_params as `in: dispatch`); server._args_required surfaces the required ones
    # in the capability index so the model knows what a dispatcher call needs.
    params: list[Param] = Field(default_factory=list)
    operations: list[TemplatedOperation] = Field(default_factory=list)


class GraphQLBlock(BaseModel):
    operations: list[GraphQLOperation] = Field(default_factory=list)


# ─── Reference resources (small static lookup tables) ──────────────────


class ReferenceResource(BaseModel):
    """A static lookup table exposed as an MCP resource, fetched lazily on first read.

    Backed by a normal endpoint call (no params) so it reuses the HTTP client + auth.
    """

    model_config = ConfigDict(extra="forbid")

    uri: str  # e.g. "afl://teams/idmap"
    summary: str
    base: str = "default"  # key into Provider.base_urls
    path: str  # e.g. "/afl/v2/teams/idmap"
    auth: str = "default"
    mime_type: str = "application/json"


# ─── Capability catalogue ─────────────────────────────────────────────


class Capability(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    description: str
    single_provider: bool = False


class CapabilityCatalogue(BaseModel):
    capabilities: list[Capability]

    def by_id(self) -> dict[str, Capability]:
        return {c.id: c for c in self.capabilities}


# ─── Top-level spec ───────────────────────────────────────────────────


class Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Bumped if the spec schema makes a breaking change; the loader warns
    # (does not fail) when it encounters an unknown future version.
    spec_version: int = 1
    provider: Provider
    endpoints: list[Endpoint] = Field(default_factory=list)
    dispatchers: list[Dispatcher] = Field(default_factory=list)
    graphql: GraphQLBlock | None = None
    reference_resources: list[ReferenceResource] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> "Spec":
        names: set[str] = set()
        for e in self.endpoints:
            if e.name in names:
                raise ValueError(f"duplicate tool name '{e.name}' in provider '{self.provider.id}'")
            names.add(e.name)
        for d in self.dispatchers:
            if d.name in names:
                raise ValueError(f"duplicate tool name '{d.name}' in provider '{self.provider.id}'")
            names.add(d.name)
        return self

    def all_tools(self) -> list[Endpoint | Dispatcher]:
        return [*self.endpoints, *self.dispatchers]
