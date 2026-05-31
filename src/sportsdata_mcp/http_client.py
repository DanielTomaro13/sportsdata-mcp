"""Per-provider HTTP client. One per Provider; injects auth, retries once on 401."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from .auth.afl import AFLTokenProvider
from .auth.base import AuthProvider
from .auth.header import StaticHeaderAuthProvider
from .auth.none import NullAuthProvider
from .config import Config
from .errors import ToolError
from .spec import AuthAFLWMCTok, AuthNone, AuthStaticHeader, Provider

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
        timeout = cfg.request_timeout(provider.id, default=30.0)
        self._max_bytes = cfg.max_response_bytes_for(provider.id)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=timeout, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
            headers=provider.default_headers,
            follow_redirects=True,
        )
        self._auth_providers: dict[str, AuthProvider] = {}
        self._bucket = _TokenBucket(
            rate=cfg.rate_limit_rps_for(provider.id),
            burst=int(cfg.providers.get(provider.id, {}).get("burst", 10)),
        )

    def _auth_provider(self, key: str) -> AuthProvider:
        if key in self._auth_providers:
            return self._auth_providers[key]
        spec = self._provider.auth.get(key)
        if spec is None or isinstance(spec, AuthNone):
            provider: AuthProvider = NullAuthProvider()
        elif isinstance(spec, AuthStaticHeader):
            provider = StaticHeaderAuthProvider(spec)
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
        await self._bucket.acquire()
        full_url = self._provider.base_urls[base].rstrip("/") + url
        merged_headers = dict(headers or {})
        auth_spec = self._provider.auth.get(auth_key)
        needs_auth = auth_spec is not None and not isinstance(auth_spec, AuthNone)

        if needs_auth:
            ap = self._auth_provider(auth_key)
            name, value = await ap.get()
            merged_headers[name] = value

        for attempt in (0, 1):
            log.info("→ %s %s (provider=%s, auth=%s)", method, full_url, self._provider.id, auth_key)
            r = await self._client.request(method, full_url, params=params, headers=merged_headers, json=json_body)
            if r.status_code == 401 and needs_auth and attempt == 0:
                log.warning("auth invalidated on 401 (provider=%s, auth=%s); refetching", self._provider.id, auth_key)
                ap = self._auth_provider(auth_key)
                ap.invalidate()
                name, value = await ap.get()
                merged_headers[name] = value
                continue
            return r
        return r  # unreachable

    async def mint_auth(self, auth_key: str) -> tuple[str, str]:
        """Force-acquire the auth header for ``auth_key`` (used by ``doctor``)."""
        return await self._auth_provider(auth_key).get()

    async def request_json(self, **kwargs) -> dict | list:
        """Request + defensive decode. Tool handlers call this — never a bare ``r.json()``."""
        r = await self.request(**kwargs)
        return self._decode(r)

    def _decode(self, r: httpx.Response) -> dict | list:
        # 1. Size guard — refuse to dump megabytes into the model's context.
        body = r.content
        if len(body) > self._max_bytes:
            log.warning(
                "oversize response (provider=%s, %d bytes > limit %d)", self._provider.id, len(body), self._max_bytes
            )
            raise ToolError(
                f"Response from {self._provider.id} was {len(body):,} bytes "
                f"(limit {self._max_bytes:,}). Narrow the query (date range, pageSize, filters) and retry.",
                recoverable=True,
                code="RESPONSE_TOO_LARGE",
            )

        # 2. Status guard — surface bot-blocks / rate-limits / server errors as clean ToolErrors.
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

        # 3. Content-type / decode guard — Akamai/Cloudflare challenges return HTML, not JSON.
        ctype = r.headers.get("content-type", "")
        if "json" not in ctype:
            log.error("non-JSON response (provider=%s, content-type=%s)", self._provider.id, ctype or "unknown")
            raise ToolError(
                f"{self._provider.id} returned non-JSON ({ctype or 'unknown'}; HTTP {r.status_code}). "
                f"Often a bot-challenge page. Body starts: {_snippet(r)}",
                recoverable=False,
                code="NON_JSON_RESPONSE",
            )
        try:
            return r.json()
        except json.JSONDecodeError as e:
            log.error("JSON decode failed (provider=%s): %s", self._provider.id, _snippet(r, 120))
            raise ToolError(
                f"{self._provider.id} sent a JSON content-type but the body did not parse. "
                f"Body starts: {_snippet(r)}",
                recoverable=False,
                code="JSON_DECODE_ERROR",
            ) from e

    async def aclose(self) -> None:
        await self._client.aclose()
