"""Pydantic models for provider specs and the capability catalogue."""

from __future__ import annotations

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


class AuthAFLWMCTok(BaseModel):
    type: Literal["afl_wmctok"]
    mint_url: str
    mint_headers: dict[str, str] = Field(default_factory=dict)
    header: str = "x-media-mis-token"


AuthSpec = Annotated[
    AuthNone | AuthStaticHeader | AuthAFLWMCTok,
    Field(discriminator="type"),
]


# ─── Provider ──────────────────────────────────────────────────────────


class HashRefresh(BaseModel):
    bundle_host: str
    bundle_url_pattern: str


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str
    doc_url: str | None = None
    base_urls: dict[str, str]
    default_headers: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, AuthSpec] = Field(default_factory=lambda: {"default": AuthNone()})
    hash_refresh: HashRefresh | None = None


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
        path_param_names = {seg.strip("{}") for seg in self.path.split("/") if seg.startswith("{") and seg.endswith("}")}
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
    name: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    variables: str = ""
    verified: bool = False


class TemplatedOperation(BaseModel):
    name: str
    path: str
    path_params: list[str] = Field(default_factory=list)
    query_params: list[str] = Field(default_factory=list)
    summary: str = ""


class Dispatcher(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    group: str
    capabilities: list[str] = Field(default_factory=list)
    kind: Literal["graphql_persisted", "templated_rest"]
    summary: str
    method: Literal["GET", "POST"] = "GET"
    base: str | None = None
    endpoint: str | None = None
    auth: str = "default"
    default_headers: dict[str, str] = Field(default_factory=dict)
    catalog_resource: str
    catalog_source: str | None = None
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
