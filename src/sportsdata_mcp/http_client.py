"""Per-provider HTTP client. One per Provider; injects auth, refetches a stale
credential once on 401, and retries transient upstream statuses (e.g. NBA/Akamai
429/5xx) with exponential backoff when the spec opts in."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import httpx

from .auth.afl import AFLTokenProvider
from .auth.base import AuthProvider
from .auth.header import StaticHeaderAuthProvider
from .auth.none import NullAuthProvider
from .auth.kalshi import KalshiRSASigner
from .auth.oauth import OAuthRefreshProvider
from .auth.query import StaticQueryAuthProvider
from .config import Config
from .errors import ToolError
from .licence import proxy_base_for
from .spec import AuthKalshiRSA, AuthOAuthRefresh, AuthAFLWMCTok, AuthNone, AuthStaticHeader, AuthStaticQuery, Provider

log = logging.getLogger("sportsdata_mcp.http")


def _snippet(r: httpx.Response, n: int = 200) -> str:
    return r.text[:n].replace("\n", " ").strip()


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
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self.rate
        await asyncio.sleep(wait)
        async with self._lock:
            self._tokens = max(0.0, self._tokens - 1.0)


class HTTPClient:
    """Owns one httpx.AsyncClient and a per-auth-key AuthProvider map."""

    def __init__(self, provider: Provider, cfg: Config) -> None:
        self._provider = provider
        defaults = provider.defaults
        prov_cfg = cfg.providers.get(provider.id, {})
        timeout = cfg.request_timeout(provider.id, spec_default=defaults.request_timeout_seconds, default=30.0)
        self._max_bytes = cfg.max_response_bytes_for(provider.id)
        self._secrets = cfg.secrets
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=timeout, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            headers=provider.default_headers,
            follow_redirects=True,
            http2=True,  # negotiated via ALPN; falls back to HTTP/1.1. Some CDNs (Akamai) prefer h2.
        )
        self._auth_providers: dict[str, AuthProvider] = {}
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
        self._proxy_base = proxy_base_for(provider.id)
        self._licence = os.environ.get("SPORTSDATA_LICENSE")
        if self._proxy_base:
            log.info("provider %s routed through licence proxy %s", provider.id, self._proxy_base)

    def _auth_provider(self, key: str) -> AuthProvider:
        if key in self._auth_providers:
            return self._auth_providers[key]
        spec = self._provider.auth.get(key)
        if spec is None or isinstance(spec, AuthNone):
            provider: AuthProvider = NullAuthProvider()
        elif isinstance(spec, AuthStaticHeader):
            provider = StaticHeaderAuthProvider(spec, self._secrets)
        elif isinstance(spec, AuthStaticQuery):
            provider = StaticQueryAuthProvider(spec, self._secrets)
        elif isinstance(spec, AuthOAuthRefresh):
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
                if isinstance(ap, KalshiRSASigner):
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
            r = await self._client.request(method, full_url, params=merged_params, headers=attempt_headers, json=json_body)
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
            if r.status_code in self._retry_statuses and retries_used < self._max_retries:
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

    async def request_json(self, **kwargs) -> dict | list:
        """Request + defensive decode. Tool handlers call this — never a bare ``r.json()``."""
        r = await self.request(**kwargs)
        return self._decode(r)

    def _decode(self, r: httpx.Response) -> dict | list:
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
        body = r.content
        if self._max_bytes > 0 and len(body) > self._max_bytes:
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
            return r.json()
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
