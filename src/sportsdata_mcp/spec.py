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
    # Prepended to the resolved value — e.g. "Bearer " so the env var holds the
    # bare token (X/Twitter), not the header syntax.
    value_prefix: str = ""


class AuthStaticQuery(BaseModel):
    # Like static_header but the secret rides in a query parameter (e.g. Data Golf's
    # `?key=`). The value comes from an env var (preferred) or a literal.
    type: Literal["static_query"]
    param: str
    value: str | None = None
    env: str | None = None


class AuthOAuthRefresh(BaseModel):
    # Short-lived OAuth access tokens, self-minted. All secrets come from env vars
    # (preferred) or the config `secrets` block — never literals in the spec (the
    # DataGolf rule). The token endpoint MUST be form-encoded (verified live on TAB:
    # JSON bodies are rejected).
    #
    # Grants (TAB verified live with all three):
    #   client_credentials (default) — fully self-managing: client_id+secret mint
    #     ~3h access tokens on demand; nothing to harvest, nothing expires for good.
    #   refresh_token — needs refresh_token_env; optional password fallback.
    #   password — username/password envs mint a token pair directly.
    type: Literal["oauth_refresh"]
    token_url: str
    client_id_env: str
    client_secret_env: str
    grant: Literal["client_credentials", "refresh_token", "password"] = "client_credentials"
    refresh_token_env: str | None = None
    username_env: str | None = None
    password_env: str | None = None
    header: str = "Authorization"
    value_prefix: str = "Bearer "
    # Refresh this many seconds BEFORE `expires_in` elapses (clock-skew margin).
    expiry_margin_seconds: int = 60


class AuthKalshiRSA(BaseModel):
    # Kalshi's authenticated tier: every request carries an RSA-PSS signature over
    # timestamp+method+path (KALSHI-ACCESS-KEY / -SIGNATURE / -TIMESTAMP headers).
    # OPTIONAL BY DESIGN: Kalshi market data is public — a key only raises rate
    # limits — so when the env vars are unset the provider runs anonymously
    # instead of failing. Secrets are env-only (the DataGolf rule); the private
    # key is supplied as PEM text (private_key_env) or a file path
    # (private_key_path_env), whichever is set.
    type: Literal["kalshi_rsa"]
    key_id_env: str
    private_key_env: str | None = None
    private_key_path_env: str | None = None


class AuthAFLWMCTok(BaseModel):
    type: Literal["afl_wmctok"]
    mint_url: str
    mint_headers: dict[str, str] = Field(default_factory=dict)
    header: str = "x-media-mis-token"


AuthSpec = Annotated[
    AuthNone | AuthStaticHeader | AuthStaticQuery | AuthOAuthRefresh | AuthKalshiRSA | AuthAFLWMCTok,
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
    # Discard cookies the upstream sets instead of replaying them on later requests.
    # Akamai bot-manager (e.g. TAB) sets bm_* cookies on the first response and 403s
    # any client that echoes them back without the matching JS-sensor telemetry.
    strip_cookies: bool = False
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
    # Commerce: this provider runs on OUR upstream credential (never shipped locally), so a
    # licensed build routes it through the entitlement proxy. `byo_key_env`, when that env
    # var is set, means the customer supplied their own key → call the upstream directly.
    proxied: bool = False
    byo_key_env: str | None = None


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
    # Wire name when it differs from `name` — `name` must be a valid Python
    # identifier (it becomes the tool's signature param), but some APIs use names
    # that aren't (X's `tweet.fields`). Query/header building sends `api_name`.
    api_name: str | None = None

    @property
    def wire_name(self) -> str:
        return self.api_name or self.name


class Example(BaseModel):
    description: str
    params: dict[str, object]


# ─── Response classifier ───────────────────────────────────────────────
# A spec-declared, ADDITIVE post-fetch annotation: it reads one source key on
# each item of a (possibly nested) list in the response and writes a derived tag
# onto a new key on that same item. It never alters an upstream value and is a
# no-op for any endpoint that doesn't declare a `classify` block — the engine's
# passthrough contract holds for everyone else. Motivating case: tagging each
# Dabble market with its product (single/sgm/pickem/racing) so a consumer can't
# silently blend Pick'em multipliers into a fixed-odds price comparison.


class ClassifyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Each rule reads one item key (`field`, or the block's `from` default) and
    # applies exactly one matcher — string (prefix | contains | regex) or scalar
    # (`eq`, e.g. a boolean capability flag) — paired with `value`. A lone
    # `default` is the fallback when no earlier rule matched. Rules are tried in
    # declaration order; first match wins. Prefer provider-agnostic signals
    # (capability flags) over third-party-derived names so a vendor swap upstream
    # doesn't silently break classification.
    field: str | None = None
    prefix: str | None = None
    contains: str | None = None
    regex: str | None = None
    eq: object | None = None
    value: str | None = None
    default: str | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> "ClassifyRule":
        matchers = [m for m in (self.prefix, self.contains, self.regex) if m is not None]
        n_match = len(matchers) + (1 if self.eq is not None else 0)
        if self.default is not None:
            if n_match or self.value is not None or self.field is not None:
                raise ValueError("classify rule with `default` must not also set a matcher, `value`, or `field`")
        else:
            if n_match != 1:
                raise ValueError("classify rule needs exactly one of prefix/contains/regex/eq (or `default`)")
            if self.value is None:
                raise ValueError("classify rule with a matcher must set `value`")
        if self.regex is not None:
            try:
                re.compile(self.regex)
            except re.error as e:
                raise ValueError(f"invalid classify regex {self.regex!r}: {e}") from e
        return self


class Classify(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # Where to write the tag, as a path of dotted segments ending in the new key.
    # A segment suffixed with `[]` is a list to iterate. Examples:
    #   "sportFixtureDetail.markets[].product"  → detail dict → markets list → set `product`
    #   "data[].markets[].product"              → fixtures list → each markets list → set `product`
    field: str = Field(pattern=r"^(\w+\[\]\.|\w+\.)*\w+$")
    # Default item key a rule reads when it doesn't set its own `field` (e.g.
    # "resultingType"). Optional — a block may instead give every rule its own field.
    source: str | None = Field(default=None, alias="from")
    rules: list[ClassifyRule] = Field(min_length=1)

    @property
    def container_segments(self) -> list[str]:
        return self.field.split(".")[:-1]

    @property
    def set_key(self) -> str:
        return self.field.split(".")[-1]

    @model_validator(mode="after")
    def _field_shape(self) -> "Classify":
        if "[]" in self.set_key:
            raise ValueError(f"classify field {self.field!r} must end in a plain key, not a `[]` segment")
        if not self.container_segments:
            raise ValueError(f"classify field {self.field!r} must traverse at least one container segment")
        for r in self.rules:
            if r.default is None and r.field is None and self.source is None:
                raise ValueError(
                    f"classify field {self.field!r}: a rule has no `field` and the block sets no `from` default"
                )
        return self


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
    # Optional, additive post-fetch tags (see Classify). Absent ⇒ pure passthrough.
    classify: list[Classify] = Field(default_factory=list)

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
            # A path param is required UNLESS it declares a default — then it's optional
            # and the default is interpolated when the caller omits it (e.g. a `mode`
            # segment defaulting to "classic"). The default must be non-None to count.
            if p.in_ == "path" and p.name in path_param_names:
                p.required = p.default is None
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
