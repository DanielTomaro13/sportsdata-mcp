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
    # Optional tier: when the env var is unset the request goes out ANONYMOUS instead
    # of raising AuthMissingError. For upstreams whose public tier needs no credential
    # but whose private tier reads the same paths with one (ESPN Fantasy: public
    # leagues are open, private leagues need the espn_s2/SWID cookie). Mirrors
    # AuthOAuthRefresh.optional.
    optional: bool = False


class AuthStaticQuery(BaseModel):
    # Like static_header but the secret rides in a query parameter (e.g. Data Golf's
    # `?key=`). The value comes from an env var (preferred) or a literal.
    type: Literal["static_query"]
    param: str
    value: str | None = None
    env: str | None = None
    # Optional tier: an unset env var sends the request WITHOUT the key rather than
    # raising AuthMissingError. Same contract as AuthStaticHeader.optional — it keeps a
    # BYO-key provider from breaking startup for everyone who hasn't configured it; the
    # upstream's own 401 is then what the caller sees, which is the honest error.
    optional: bool = False


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
    # Optional auth: when the credential envs are NOT set, requests go out
    # anonymous instead of failing — for providers whose endpoints serve both
    # tiers (TAB: public reads work keyless; personal keys use the sanctioned
    # authenticated tier). Auth-required providers keep the default (a loud
    # AuthMissingError).
    optional: bool = False


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


class AuthStaticBasic(BaseModel):
    """HTTP Basic. `password` may be a literal because some APIs use a constant for it
    (MySportsFeeds wants the fixed string "MYSPORTSFEEDS"); `password_env` wins when set.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["static_basic"]
    username_env: str
    password_env: str | None = None
    password: str | None = None
    optional: bool = False


# Every attribute across every auth type that names an environment variable. Listing
# these by hand at each call site has now gone wrong three times — `username_env` was
# missed when HTTP Basic landed, and the OAuth trio when Yahoo did — each time producing
# a check that silently passed because it was looking at the wrong field.
AUTH_ENV_ATTRS = (
    "env",
    "username_env",
    "password_env",
    "client_id_env",
    "client_secret_env",
    "refresh_token_env",
)


def auth_env_names(provider) -> set[str]:
    """Every env var this provider's auth reads, whatever the auth type."""
    return {
        name
        for auth in provider.auth.values()
        for attr in AUTH_ENV_ATTRS
        if (name := getattr(auth, attr, None))
    }


AuthSpec = Annotated[
    AuthNone | AuthStaticHeader | AuthStaticQuery | AuthStaticBasic | AuthOAuthRefresh | AuthKalshiRSA | AuthAFLWMCTok,
    Field(discriminator="type"),
]


# ─── Provider ──────────────────────────────────────────────────────────


class ErrorSignal(BaseModel):
    """A top-level field/value pair that means "this 200 is actually an error".

    Some APIs never use HTTP status codes for auth or validation failures: api-tennis
    returns 200 with {"error":"1", ...} and cricketdata returns 200 with
    {"status":"failure","reason":"Invalid API Key"}. Without this, the engine hands
    that object to the model AS DATA, and the model dutifully reports "the API says
    your key is invalid" as though it were a match result — or worse, tries to read
    fixtures out of it. This is the silent-wrongness failure class, so it is worth
    declaring per provider.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    # Omit `equals` to fire whenever the field is present and TRUTHY. api-sports needs
    # this: it reports failures in an `errors` object whose contents vary
    # ({"token": …}, {"requests": "You have reached the request limit"}), and returns
    # `errors: []` on success — so there is no fixed value to match, only emptiness.
    equals: str | None = None


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
    # Resolve this provider's hostnames via DNS-over-HTTPS (Cloudflare/Google by raw
    # IP, so no system DNS is consulted) instead of the OS resolver. Set when a
    # network poisons the provider's domain — e.g. an ISP/router returning a dead
    # sinkhole IP for a lawful host. SNI/Host stay the real hostname, so TLS still
    # verifies against the provider's certificate; only the A-record is trusted from
    # a public resolver. Off by default — the OS resolver is used for everyone else.
    resolve_via_doh: bool = False



def _default_auth() -> dict[str, AuthSpec]:
    """A provider with no `auth:` block is anonymous.

    A named function rather than a lambda so the DECLARED return type is the field's
    type: a lambda infers `dict[str, AuthNone]`, which is narrower than `dict[str,
    AuthSpec]` and made the default incompatible with the field it defaults.
    """
    return {"default": AuthNone()}


class Provider(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str
    doc_url: str | None = None
    base_urls: dict[str, str]
    default_headers: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, AuthSpec] = Field(default_factory=_default_auth)
    hash_refresh: HashRefresh | None = None
    defaults: ProviderDefaults = Field(default_factory=ProviderDefaults)
    # Commerce: this provider runs on OUR upstream credential (never shipped locally), so a
    # licensed build routes it through the entitlement proxy. `byo_key_env`, when that env
    # var is set, means the customer supplied their own key → call the upstream directly.
    proxied: bool = False
    byo_key_env: str | None = None
    # False = the `response_hint`s in this spec were derived from the VENDOR'S
    # DOCUMENTATION, not confirmed against a live response. That happens for providers
    # whose data requires a key we don't hold: the paths and auth mechanism are probed
    # (a keyless call returns a clean 401/403), but the response shapes are not.
    #
    # This is not cosmetic. Roughly a third of the shapes assumed while building this
    # catalogue turned out to be wrong when probed — nested where they looked flat,
    # grouped where they looked like a list — and those errors are the silent kind that
    # produce confident wrong answers rather than an exception. The flag is surfaced in
    # every affected tool's description so the model treats the shape as approximate
    # and reads what it actually got.
    # Top-level markers that turn an HTTP 200 into a ToolError. See ErrorSignal.
    error_signals: list[ErrorSignal] = Field(default_factory=list)
    shapes_verified: bool = True
    # True = this provider returns NOTHING USEFUL without a key the user must obtain.
    #
    # This is deliberately not inferred from `auth`, because the auth shape doesn't
    # answer the question. ESPN Fantasy reads an env var (the espn_s2 cookie) and is
    # `optional`, yet public leagues work perfectly without it — it is an upgrade, not
    # a requirement. The Odds API is also `optional` (so a missing key never breaks
    # startup) but returns 401 for everything. Only a human who has tried it knows
    # which is which, so it is stated rather than guessed.
    #
    # The `free` preset is computed from this flag, so a new BYO provider cannot
    # silently make "works with no setup" a lie.
    requires_user_key: bool = False

    # The market(s) this provider actually serves, as ISO-3166 alpha-2 codes. None means
    # "no particular market" — a global league feed, an aggregator, a model API.
    #
    # This exists to answer ONE user-facing question honestly: "why did that provider
    # fail for me?". Bookmakers are licensed per jurisdiction and block everyone else at
    # the edge, so an unreachable Sportsbet is usually CORRECT behaviour rather than an
    # outage, and telling a user in Ohio that it is "down" sends them to file an issue
    # against reality.
    #
    # It is deliberately a statement about the MARKET, not a claim about geo-blocking.
    # Whether a given host blocks a given IP is not knowable from here, so `coverage`
    # reports what the probe actually did from the user's own machine and uses this
    # field only to explain it. Inferring the market from the domain would be close but
    # wrong in both directions: `.com.au` league feeds serve the world, and some global
    # domains are region-locked anyway.
    region: list[str] | None = None


# ─── Endpoint params ───────────────────────────────────────────────────

ParamLocation = Literal["path", "query", "header", "body", "dispatch"]
ParamType = Literal["string", "integer", "number", "boolean", "string_csv", "string_list", "json", "object"]


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
    def _exactly_one_form(self) -> ClassifyRule:
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
    def _field_shape(self) -> Classify:
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
    #: True when the body is a MAP OF ROWS — keyed by id, every value a record —
    #: rather than an object with named sections. `response_fields` then applies to every
    #: value.
    #:
    #: Explicit rather than inferred, because the two shapes are indistinguishable from
    #: the outside: `{"13602": {...}, "8800": {...}}` is Sleeper's whole player table,
    #: and `{"league": {...}, "settings": {...}}` is an object with metadata. Projecting
    #: the second would silently gut it. Sleeper's player file is 14.6 MB, so without
    #: this the projection was a no-op and the tool was uncallable.
    response_map: bool = False

    #: Per-endpoint override of the provider's `shapes_verified`. None = inherit.
    #:
    #: Needed because verification is not uniform across a provider. ESPN Fantasy's 27
    #: READS were confirmed against live responses; its two WRITES were transcribed from
    #: ESPN's own JS bundle and have never returned a 200 to us. Flipping the provider
    #: flag would slap "unverified" on 27 good tools to be honest about 2, and a warning
    #: that appears everywhere stops being read anywhere.
    shapes_verified: bool | None = None
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
    # Wire format of the response body. `json` (the default) covers every provider
    # here bar one: some datasets are only published as CSV downloads
    # (football-data.co.uk's decades of results + closing odds). `csv` parses the
    # body into a list of row objects keyed by the header line, so the tool returns
    # ordinary JSON to the model.
    response_format: Literal["json", "csv", "xml"] = "json"
    # REDUCTIVE projection — see project.py. `response_pick` keeps named top-level keys
    # of a dict body; `response_fields` keeps named keys on list items. Needed because
    # FPL's bootstrap-static is a single 1.37 MB blob (~362k tokens of player rows alone)
    # with no server-side field selection, which no context window can hold.
    response_pick: list[str] = Field(default_factory=list)
    response_fields: list[str] = Field(default_factory=list)
    # Send the body VERBATIM with this content type instead of JSON-encoding it. Yahoo's
    # fantasy write endpoints accept XML only, and inventing a dict->XML serialiser in
    # the engine would mean baking one provider's document shape into shared code. A raw
    # string keeps the engine generic: the spec documents the exact template, the caller
    # fills it in, and what is sent is what was written.
    request_body_format: Literal["json", "raw"] = "json"
    request_content_type: str | None = None
    # Whether this endpoint CHANGES anything. Defaults from the method, which is right
    # almost always — but not universally: FanDuel's promotions endpoint is a POST whose
    # empty body returns everything, a read wearing a write's method. Annotating it
    # destructive would make a client confirm before a harmless lookup.
    read_only: bool | None = None

    @model_validator(mode="after")
    def _path_params_required(self) -> Endpoint:
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
    def _unique_names(self) -> Spec:
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
