"""Per-provider HTTP client. One per Provider; injects auth, refetches a stale
credential once on 401, and retries transient upstream statuses (e.g. NBA/Akamai
429/5xx) with exponential backoff when the spec opts in."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import time

import httpx

from .auth.afl import AFLTokenProvider
from .auth.base import AuthProvider
from .auth.basic import StaticBasicAuthProvider
from .auth.header import StaticHeaderAuthProvider
from .auth.kalshi import KalshiRSASigner
from .auth.none import NullAuthProvider
from .auth.oauth import OAuthRefreshProvider
from .auth.query import StaticQueryAuthProvider
from .config import Config
from .errors import ToolError
from .licence import proxy_base_for
from .spec import (
    AuthAFLWMCTok,
    AuthKalshiRSA,
    AuthNone,
    AuthOAuthRefresh,
    AuthStaticBasic,
    AuthStaticHeader,
    AuthStaticQuery,
    Provider,
)

log = logging.getLogger("sportsdata_mcp.http")

# Bound on cached GETs per provider. Responses here run to megabytes (ESPN Fantasy
# `allon` is ~4.5 MB), so this caps memory rather than hit rate.
_CACHE_MAX_ENTRIES = 256


def _snippet(r: httpx.Response, n: int = 200) -> str:
    return r.text[:n].replace("\n", " ").strip()


def _xml_to_obj(el) -> object:
    """One XML element as dict / str, mirroring MFL's own JSON rendering.

    Attributes and children share a namespace, children win on a clash (they carry more).
    Repeated child tags collapse to a list, so a document with one row and one with many
    do not produce different SHAPES — the difference that turns "handle both" into a
    crash the first time a league has exactly one pending trade.
    """
    obj: dict[str, object] = dict(el.attrib)
    for child in el:
        value = _xml_to_obj(child)
        if child.tag in obj:
            existing = obj[child.tag]
            if isinstance(existing, list):
                existing.append(value)
            else:
                obj[child.tag] = [existing, value]
        else:
            obj[child.tag] = value
    if obj:
        return obj
    return (el.text or "").strip()


class _TokenBucket:
    """Simple token-bucket rate limiter. Default 10 RPS, burst 10."""

    def __init__(self, rate: float = 10.0, burst: int = 10) -> None:
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._updated
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._updated = now
            # debit BEFORE sleeping, allowing a negative balance: releasing
            # the lock undebited let N concurrent waiters each compute the
            # same near-zero wait and fire together after one refill — a
            # thundering herd at exactly the upstreams the limiter protects
            self._tokens -= 1.0
            if self._tokens >= 0.0:
                return
            wait = -self._tokens / self.rate
        await asyncio.sleep(wait)


class HTTPClient:
    """Owns one httpx.AsyncClient and a per-auth-key AuthProvider map."""

    def __init__(self, provider: Provider, cfg: Config) -> None:
        self._provider = provider
        defaults = provider.defaults
        prov_cfg = cfg.providers.get(provider.id, {})
        timeout = cfg.request_timeout(provider.id, spec_default=defaults.request_timeout_seconds, default=30.0)
        self._max_bytes = cfg.max_response_bytes_for(provider.id)
        self._secrets = cfg.secrets
        # DoH transport for providers whose hostnames a network poisons (spec
        # opt-in). The override set is THIS provider's own base-url hosts, so no
        # other traffic is affected.
        transport = None
        if defaults.resolve_via_doh:
            from urllib.parse import urlparse

            from .dns import doh_transport

            hosts = frozenset(
                h for h in (urlparse(u).hostname for u in provider.base_urls.values()) if h
            )
            if hosts:
                transport = doh_transport(
                    hosts, http2=True,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
                )
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(connect=5.0, read=timeout, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            headers=provider.default_headers,
            follow_redirects=True,
            http2=True,  # negotiated via ALPN; falls back to HTTP/1.1. Some CDNs (Akamai) prefer h2.
        )
        self._auth_providers: dict[str, AuthProvider] = {}
        # Short-lived GET cache: key -> (expires_at_monotonic, decoded_body). Insertion
        # ordered, so popping the first item evicts the oldest when the bound is hit.
        self._cache: dict[str, tuple[float, dict | list]] = {}
        self._cache_ttl = cfg.cache_ttl_for(provider.id)
        burst = prov_cfg.get("burst")
        if burst is None:
            burst = defaults.burst if defaults.burst is not None else 10
        self._bucket = _TokenBucket(
            rate=cfg.rate_limit_rps_for(provider.id, spec_default=defaults.rate_limit_rps),
            burst=int(burst),
        )
        # Transient-status retry policy (user config overrides the spec defaults).
        statuses = prov_cfg.get("retry_statuses")
        self._retry_statuses = set(statuses if statuses is not None else defaults.retry_statuses)
        self._max_retries = int(prov_cfg.get("max_retries", defaults.max_retries))
        self._retry_backoff = float(prov_cfg.get("retry_backoff_seconds", defaults.retry_backoff_seconds))
        self._strip_cookies = bool(prov_cfg.get("strip_cookies", defaults.strip_cookies))
        # Licensed proxy mode (commerce): route a credentialed provider (e.g. DataGolf)
        # through the entitlement service, which attaches our upstream key server-side.
        self._proxy_base = proxy_base_for(
            provider.id, proxied=provider.proxied, byo_key_env=provider.byo_key_env
        )
        self._licence = os.environ.get("SPORTSDATA_LICENSE")
        if self._proxy_base:
            log.info("provider %s routed through licence proxy %s", provider.id, self._proxy_base)

    @property
    def max_response_bytes(self) -> int:
        """The configured context cap; <= 0 means uncapped. Read by the registry, which
        enforces it on projected payloads."""
        return self._max_bytes

    def _auth_provider(self, key: str) -> AuthProvider:
        if key in self._auth_providers:
            return self._auth_providers[key]
        spec = self._provider.auth.get(key)
        if spec is None or isinstance(spec, AuthNone):
            provider: AuthProvider = NullAuthProvider()
        elif isinstance(spec, AuthStaticHeader):
            if spec.optional and not (
                (spec.env and (os.environ.get(spec.env) or (self._secrets or {}).get(spec.env))) or spec.value
            ):
                # optional tier with no credential configured → anonymous
                provider = NullAuthProvider()
            else:
                provider = StaticHeaderAuthProvider(spec, self._secrets)
        elif isinstance(spec, AuthStaticQuery):
            if spec.optional and not (
                (spec.env and (os.environ.get(spec.env) or (self._secrets or {}).get(spec.env))) or spec.value
            ):
                # optional tier with no key configured → send unauthenticated and let
                # the upstream's 401 be the message the caller sees
                provider = NullAuthProvider()
            else:
                provider = StaticQueryAuthProvider(spec, self._secrets)
        elif isinstance(spec, AuthStaticBasic):
            if spec.optional and not (
                os.environ.get(spec.username_env) or (self._secrets or {}).get(spec.username_env)
            ):
                provider = NullAuthProvider()
            else:
                provider = StaticBasicAuthProvider(spec, self._secrets)
        elif isinstance(spec, AuthOAuthRefresh):
            if spec.optional and not (
                os.environ.get(spec.client_id_env) or (self._secrets or {}).get(spec.client_id_env)
            ):
                # optional tier with no credentials configured → anonymous
                provider = NullAuthProvider()
            else:
                provider = OAuthRefreshProvider(spec, self._client, self._secrets)
        elif isinstance(spec, AuthKalshiRSA):
            provider = KalshiRSASigner(spec, self._secrets)
        elif isinstance(spec, AuthAFLWMCTok):
            provider = AFLTokenProvider(spec, self._client)
        else:
            raise RuntimeError(f"unsupported auth spec: {spec}")
        self._auth_providers[key] = provider
        return provider

    async def request(
        self,
        *,
        method: str,
        base: str,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        json_body: dict | list | None = None,
        raw_body: str | None = None,
        content_type: str | None = None,
        auth_key: str = "default",
    ) -> httpx.Response:
        merged_headers = dict(headers or {})
        auth_query: dict[str, str] = {}
        signer: KalshiRSASigner | None = None

        if self._proxy_base:
            # Licensed proxy mode: the entitlement service attaches the real upstream
            # credential server-side, so we just authenticate with the licence key and
            # skip the (absent) upstream auth. `base` collapses — proxied providers have
            # a single upstream.
            full_url = self._proxy_base.rstrip("/") + url
            if self._licence:
                merged_headers["Authorization"] = f"Bearer {self._licence}"
            needs_auth = False
        else:
            full_url = self._provider.base_urls[base].rstrip("/") + url
            auth_spec = self._provider.auth.get(auth_key)
            needs_auth = auth_spec is not None and not isinstance(auth_spec, AuthNone)
            if needs_auth:
                ap = self._auth_provider(auth_key)
                # An OPTIONAL auth spec with no credentials resolves to the null
                # provider (whose get() raises by contract) — the request must go
                # out anonymous, exactly as the anonymous public tier expects
                # (lived: every keyless TAB call raised RuntimeError otherwise).
                if isinstance(ap, NullAuthProvider):
                    needs_auth = False
                elif isinstance(ap, KalshiRSASigner):
                    # Per-request signer (timestamp in the signature) — headers are
                    # computed fresh on every attempt inside the loop below. Inactive
                    # (no credentials) signs nothing: the request stays anonymous.
                    signer = ap
                else:
                    name, value = await ap.get()
                    # static_query rides in the query string (e.g. Data Golf ?key=);
                    # everything else is a header.
                    if isinstance(auth_spec, AuthStaticQuery):
                        auth_query[name] = value
                    else:
                        merged_headers[name] = value

        merged_params = {**(params or {}), **auth_query} if auth_query else params

        auth_refetched = False
        retries_used = 0
        while True:
            # Spend a token on every attempt — retries (esp. NBA/Akamai 429s) must
            # stay under the rate limit too, not just the first request.
            await self._bucket.acquire()
            if self._strip_cookies:
                self._client.cookies.clear()
            attempt_headers = merged_headers
            if signer is not None:
                attempt_headers = {**merged_headers, **signer.sign_request(method, httpx.URL(full_url).path)}
            log.info("→ %s %s (provider=%s, auth=%s)", method, full_url, self._provider.id, auth_key)
            if raw_body is not None:
                # Verbatim — no re-encoding, so what the spec documented is what is sent.
                send_headers = dict(attempt_headers)
                send_headers.setdefault("Content-Type", content_type or "application/xml")
                r = await self._client.request(
                    method, full_url, params=merged_params, headers=send_headers, content=raw_body.encode()
                )
            else:
                r = await self._client.request(
                    method, full_url, params=merged_params, headers=attempt_headers, json=json_body
                )
            # A stale credential surfaces as 401 — refetch once and retry immediately.
            # (Signers re-sign every attempt, so a 401 retry just gets a fresh signature.)
            if r.status_code == 401 and needs_auth and signer is None and not auth_refetched:
                auth_refetched = True
                log.warning("auth invalidated on 401 (provider=%s, auth=%s); refetching", self._provider.id, auth_key)
                ap = self._auth_provider(auth_key)
                ap.invalidate()
                name, value = await ap.get()
                # Re-inject where the scheme carries it: query param for static_query,
                # header for everything else.
                if isinstance(auth_spec, AuthStaticQuery):
                    merged_params = {**(merged_params or {}), name: value}
                else:
                    merged_headers[name] = value
                continue
            # Transient upstream errors (e.g. NBA/Akamai 429/5xx) — exponential backoff.
            if (
                r.status_code in self._retry_statuses
                and retries_used < self._max_retries
                and self._may_retry(method, r.status_code)
            ):
                retries_used += 1
                wait = self._retry_backoff * (2 ** (retries_used - 1))
                log.warning(
                    "HTTP %d (provider=%s); retry %d/%d after %.1fs",
                    r.status_code, self._provider.id, retries_used, self._max_retries, wait,
                )
                await asyncio.sleep(wait)
                continue
            return r

    async def mint_auth(self, auth_key: str) -> tuple[str, str]:
        """Force-acquire the auth header for ``auth_key`` (used by ``doctor``)."""
        return await self._auth_provider(auth_key).get()

    def _cache_key(self, kwargs: dict) -> str | None:
        """Cache key for a GET, or None when the call must not be cached.

        Only GETs with no body are cacheable — anything else may have side effects
        upstream. The key includes the auth key because the public and private tiers
        of the same URL can return different documents (ESPN Fantasy: a private league
        is 401 anonymous, data with the cookie), and serving one for the other would
        be a cross-tier leak rather than merely a stale read.
        """
        if (
            str(kwargs.get("method", "GET")).upper() != "GET"
            or kwargs.get("json_body") is not None
            or kwargs.get("raw_body") is not None
        ):
            return None
        return json.dumps(
            [
                kwargs.get("base"),
                kwargs.get("url"),
                kwargs.get("params"),
                kwargs.get("headers"),
                kwargs.get("auth_key"),
            ],
            sort_keys=True,
            default=str,
        )

    async def request_json(self, **kwargs) -> dict | list:
        """Request + defensive decode. Tool handlers call this — never a bare ``r.json()``.

        ``response_format='csv'`` switches the decoder for the handful of datasets that
        are only published as CSV downloads; the model still receives ordinary JSON.
        """
        response_format = kwargs.pop("response_format", "json")
        # Endpoints that project are size-checked on the PROJECTED result instead
        # (registry.py) — see the guard in `_decode`.
        projected = bool(kwargs.pop("projected", False))
        key = self._cache_key(kwargs) if self._cache_ttl > 0 else None
        if key is not None:
            hit = self._cache.get(key)
            if hit is not None and hit[0] > time.monotonic():
                log.debug("cache hit (provider=%s) %s", self._provider.id, kwargs.get("url"))
                return hit[1]
        r = await self.request(**kwargs)
        # Declared up front: mypy otherwise infers the variable's type from the FIRST
        # branch (csv's list[dict]) and then rejects the others.
        body: dict | list
        if response_format == "csv":
            body = self._decode_csv(r)
        elif response_format == "xml":
            body = self._decode_xml(r)
        else:
            body = self._decode(r, skip_size_check=projected)
        if key is not None:
            # Evict expired entries before inserting, and bound the map so a long-running
            # server driven over many distinct params can't grow without limit.
            now = time.monotonic()
            if len(self._cache) >= _CACHE_MAX_ENTRIES:
                for k, (exp, _v) in list(self._cache.items()):
                    if exp <= now:
                        del self._cache[k]
                if len(self._cache) >= _CACHE_MAX_ENTRIES:
                    self._cache.pop(next(iter(self._cache)), None)  # oldest insert
            self._cache[key] = (now + self._cache_ttl, body)
        return body

    def _decode_csv(self, r: httpx.Response) -> list[dict]:
        """Parse a CSV body into a list of row objects keyed by the header line.

        Only used by endpoints declaring ``response_format: csv``. The status and size
        guards in ``_decode`` still apply first — a bot-challenge page or an oversized
        body must not be handed to the CSV parser and silently become one nonsense row.
        """
        self._guard_status_and_size(r)
        text = r.text
        # These files are Windows-authored and often start with a UTF-8 BOM, which would
        # otherwise become part of the FIRST COLUMN NAME ("﻿Div") and quietly break
        # every lookup of that column.
        if text.startswith("﻿"):
            text = text.lstrip("﻿")
        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except csv.Error as e:
            log.error("CSV parse failed (provider=%s): %s", self._provider.id, _snippet(r, 120))
            raise ToolError(
                f"{self._provider.id} returned a body that did not parse as CSV. "
                f"Body starts: {_snippet(r)}",
                recoverable=False,
                code="CSV_DECODE_ERROR",
            ) from e
        # Trailing blank lines produce rows whose every value is None/''.
        return [row for row in rows if any((v or "").strip() for v in row.values())]

    def _decode_xml(self, r: httpx.Response) -> dict | list:
        """Parse an XML body into plain JSON-shaped data.

        Only used by endpoints declaring ``response_format: xml``. MyFantasyLeague's
        write API is the reason this exists: its `/import` endpoints answer in XML even
        when asked for JSON, and they answer HTTP 200 whether the write succeeded or
        failed — so without a decoder here, a perfectly ordinary rejection would surface
        as "the body did not parse" and a SUCCESS would look identical to it.

        Attributes become keys; a leaf element becomes its text. That is the same shape
        MFL's own JSON mode produces for the equivalent document, so a spec's
        `error_signals` and `response_hint` read the same either way.
        """
        self._guard_status_and_size(r)
        import xml.etree.ElementTree as ET

        text = r.text.lstrip("\ufeff").strip()
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            log.error("XML parse failed (provider=%s): %s", self._provider.id, _snippet(r, 120))
            raise ToolError(
                f"{self._provider.id} returned a body that did not parse as XML. "
                f"Body starts: {_snippet(r)}",
                recoverable=False,
                code="XML_DECODE_ERROR",
            ) from e
        body = {root.tag: _xml_to_obj(root)}
        self._raise_on_error_signal(body)
        return body

    @staticmethod
    def _may_retry(method: str, status: int) -> bool:
        """Is it SAFE to send this request again?

        The retry policy was written when every tool was a GET, and retried purely on
        status. That is wrong the moment a write exists: a 5xx is AMBIGUOUS — the server
        may have applied the change and then failed to tell us — so replaying a POST can
        apply it twice. Measured before this guard: one tool call sent a transfer THREE
        times, which in FPL terms is three transfers, extra points hits, and players the
        owner did not choose.

        * Idempotent methods (GET/HEAD/PUT/DELETE) are safe to replay by definition.
        * POST/PATCH may be replayed ONLY on 429, which means the request was rejected
          before processing — never on a 5xx, where "did it happen?" is unanswerable.
        """
        if method.upper() in {"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}:
            return True
        return status == 429

    @staticmethod
    def _is_error_marker(value: object) -> bool:
        """Does this presence-mode field value mean "error"?

        Truthiness alone is not enough. iSportsAPI signals success with `code: 0`, and
        JSON APIs flip between `0` and `"0"` without warning — but Python calls the
        STRING "0" truthy, so a provider that started quoting its status code would have
        every SUCCESSFUL call raised as an error. That fails loudly rather than lying,
        which is the safer direction, but it is still wrong and baffling to debug.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if stripped in ("", "0", "0.0", "false", "False", "null", "none", "None"):
                return False
        return bool(value)

    def _raise_on_error_signal(self, body: object) -> None:
        """Turn a 200-with-an-error-body into a real error.

        Providers that never use status codes for failures (api-tennis, cricketdata)
        declare `error_signals`. Without this the model receives the error object as
        data and reports it as though it were a result.
        """
        signals = self._provider.error_signals
        if not signals or not isinstance(body, dict):
            return
        for sig in signals:
            if sig.field not in body:
                continue
            value = body[sig.field]
            if sig.equals is not None:
                if str(value) != sig.equals:
                    continue
            elif not self._is_error_marker(value):
                # presence-mode: `errors: []` / `""` / null / 0 is the SUCCESS case
                continue
            detail = (
                body.get("reason")
                or body.get("message")
                or (json.dumps(value)[:160] if sig.equals is None else json.dumps(body)[:160])
            )
            missing = self._unset_key_envs()
            hint = (
                f" Set {' or '.join(sorted(missing))} in your environment and restart."
                if missing else ""
            )
            log.warning("error-in-200 (provider=%s): %s", self._provider.id, detail)
            raise ToolError(
                f"{self._provider.id} returned HTTP 200 with an error body: {detail}.{hint}",
                recoverable=False,
                code="AUTH_REQUIRED" if missing else "UPSTREAM_ERROR",
            )

    def _unset_key_envs(self) -> set[str]:
        """Env vars this provider's auth reads that are NOT set.

        Used to turn a bare 401/403 into an actionable message. Only reports vars that
        are genuinely absent — a provider whose key IS configured and still 401s has a
        different problem (revoked key, wrong tier), and shouldn't be told to set what
        it already has.
        """
        from .spec import auth_env_names

        return {
            name
            for name in auth_env_names(self._provider)
            if not (os.environ.get(name) or (self._secrets or {}).get(name))
        }

    def _guard_status_and_size(self, r: httpx.Response) -> None:
        """Status + size checks shared by the JSON and CSV decoders."""
        if r.status_code == 429:
            log.warning("rate-limited (provider=%s, HTTP 429)", self._provider.id)
            raise ToolError(
                f"{self._provider.id} rate-limited the request (HTTP 429). Wait and retry; "
                f"the per-provider rate limiter normally prevents this.",
                recoverable=True,
                code="HTTP_429",
            )
        if r.status_code >= 400:
            log_at = log.error if r.status_code >= 500 else log.warning
            log_at("HTTP %d (provider=%s): %s", r.status_code, self._provider.id, _snippet(r, 120))
            raise ToolError(
                f"{self._provider.id} returned HTTP {r.status_code}. Body starts: {_snippet(r)}",
                recoverable=r.status_code >= 500,
                code=f"HTTP_{r.status_code}",
            )
        if self._max_bytes > 0 and len(r.content) > self._max_bytes:
            raise ToolError(
                f"{self._provider.id} response is {len(r.content):,} bytes, over the configured cap "
                f"(limit {self._max_bytes:,}). Narrow the query (date range, pageSize, filters) and retry.",
                recoverable=True,
                code="RESPONSE_TOO_LARGE",
            )

    def _decode(self, r: httpx.Response, *, skip_size_check: bool = False) -> dict | list:
        # 1. Status guard — surface bot-blocks / rate-limits / server errors as clean
        #    ToolErrors first, so an HTTP error reports its status (HTTP_503 etc.) rather
        #    than masquerading as RESPONSE_TOO_LARGE when the error body happens to be big.
        if r.status_code == 429:
            log.warning("rate-limited (provider=%s, HTTP 429)", self._provider.id)
            raise ToolError(
                f"{self._provider.id} rate-limited the request (HTTP 429). Wait and retry; "
                f"the per-provider rate limiter normally prevents this.",
                recoverable=True,
                code="RATE_LIMITED",
            )
        if r.status_code in (401, 403):
            # A BYO-key provider with no key configured is the OVERWHELMINGLY likely
            # cause here, and it has a specific fix. Saying "likely bot detection" to
            # someone who simply hasn't set PANDASCORE_TOKEN sends them hunting for a
            # geo-block that doesn't exist.
            missing = self._unset_key_envs()
            if missing:
                names = " or ".join(sorted(missing))
                log.warning("auth required (provider=%s, HTTP %d)", self._provider.id, r.status_code)
                raise ToolError(
                    f"{self._provider.id} needs an API key: set {names} in your environment "
                    f"and restart. (HTTP {r.status_code}.) Upstream said: {_snippet(r, 160)}",
                    recoverable=False,
                    code="AUTH_REQUIRED",
                )
            if r.status_code == 403:
                log.warning("blocked (provider=%s, HTTP 403): %s", self._provider.id, _snippet(r, 120))
                raise ToolError(
                    f"{self._provider.id} blocked the request (HTTP 403) — likely bot detection or geo-block. "
                    f"Body starts: {_snippet(r)}",
                    recoverable=False,
                    code="BLOCKED",
                )
        if r.status_code >= 400:
            log_at = log.error if r.status_code >= 500 else log.warning
            log_at("HTTP %d (provider=%s): %s", r.status_code, self._provider.id, _snippet(r, 120))
            raise ToolError(
                f"{self._provider.id} returned HTTP {r.status_code}. Body starts: {_snippet(r)}",
                recoverable=r.status_code >= 500,
                code=f"HTTP_{r.status_code}",
            )

        # 2. Size guard — for a 2xx body, refuse to dump megabytes into the model's
        #    context. A non-positive cap (max_response_bytes <= 0) disables it entirely.
        #
        #    SKIPPED when the endpoint projects (`response_pick`/`response_fields`). The
        #    cap protects the CONTEXT, and a projected endpoint's raw body never reaches
        #    it — FPL's bootstrap-static is 1.4MB and `fpl_gameweeks` ships ~40KB of it.
        #    Checking the raw body there measures a payload nobody will ever see, and it
        #    made four FPL tools unusable from any agent (the agents platform sets a
        #    150KB cap by default). The projected result is checked instead, in
        #    `registry.py`, against this same limit.
        body = r.content
        if self._max_bytes > 0 and not skip_size_check and len(body) > self._max_bytes:
            log.warning(
                "oversize response (provider=%s, %d bytes > limit %d)", self._provider.id, len(body), self._max_bytes
            )
            raise ToolError(
                f"Response from {self._provider.id} was {len(body):,} bytes "
                f"(limit {self._max_bytes:,}). Narrow the query (date range, pageSize, filters) and retry.",
                recoverable=True,
                code="RESPONSE_TOO_LARGE",
            )

        # 3. Decode guard — try JSON regardless of content-type. Some APIs (e.g. NBA's CDN)
        #    serve perfectly good JSON labelled `text/plain`, so the content-type is only
        #    consulted on a parse *failure*: a non-JSON type then points to an HTML
        #    bot-challenge page (Akamai/Cloudflare), a JSON type to a malformed body.
        try:
            body = r.json()
            self._raise_on_error_signal(body)
            return body
        except (json.JSONDecodeError, ValueError) as e:
            ctype = r.headers.get("content-type", "")
            if "json" not in ctype:
                log.error("non-JSON response (provider=%s, content-type=%s)", self._provider.id, ctype or "unknown")
                raise ToolError(
                    f"{self._provider.id} returned non-JSON ({ctype or 'unknown'}; HTTP {r.status_code}). "
                    f"Often a bot-challenge page. Body starts: {_snippet(r)}",
                    recoverable=False,
                    code="NON_JSON_RESPONSE",
                ) from e
            log.error("JSON decode failed (provider=%s): %s", self._provider.id, _snippet(r, 120))
            raise ToolError(
                f"{self._provider.id} sent a JSON content-type but the body did not parse. "
                f"Body starts: {_snippet(r)}",
                recoverable=False,
                code="JSON_DECODE_ERROR",
            ) from e

    async def aclose(self) -> None:
        await self._client.aclose()
