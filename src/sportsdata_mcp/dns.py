"""DNS-over-HTTPS resolution for providers whose hostnames a network poisons.

Some networks (an ISP or router) return a dead sinkhole IP for a lawful host —
observed live: every ``*.polymarket.com`` name resolving to one unreachable
Azure IP while Google/Cloudflare DNS return the real Cloudflare edge. This
module resolves such hosts through DoH endpoints addressed by their RAW IP
(``1.1.1.1``, ``8.8.8.8``), so the poisoned OS resolver is never consulted.

Only the A-record is trusted from the public resolver. The TLS handshake still
sends the real hostname as SNI and verifies the provider's certificate, so a
resolver that lied would fail the cert check rather than route traffic
anywhere — the trust model is unchanged, only the address lookup moves.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpcore
import httpx

log = logging.getLogger("sportsdata_mcp.dns")

# DoH endpoints reachable by raw IP (no DNS needed to find the resolver itself).
# Cloudflare's 1.1.1.1 and Google's 8.8.8.8 both carry their IPs in the cert SAN,
# so an HTTPS GET to the bare IP verifies cleanly.
_DOH_SERVERS = ("1.1.1.1", "8.8.8.8", "1.0.0.1")


class DohResolver:
    """Async A-record lookups via DoH, TTL-cached. Shared process-wide."""

    def __init__(self, servers: tuple[str, ...] = _DOH_SERVERS, ttl: float = 300.0) -> None:
        self._servers = servers
        self._ttl = ttl
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()
        # a plain client: the DoH servers are raw IPs, so this never recurses
        self._client = httpx.AsyncClient(timeout=5.0, verify=True)

    async def resolve(self, host: str) -> str | None:
        async with self._lock:
            hit = self._cache.get(host)
            if hit and hit[0] > time.monotonic():
                return hit[1]
        for server in self._servers:
            try:
                r = await self._client.get(
                    f"https://{server}/dns-query",
                    params={"name": host, "type": "A"},
                    headers={"Accept": "application/dns-json"},
                )
                answers = [a["data"] for a in r.json().get("Answer", []) if a.get("type") == 1]
                if answers:
                    ip = str(answers[0])
                    async with self._lock:
                        self._cache[host] = (time.monotonic() + self._ttl, ip)
                    log.debug("doh %s -> %s (via %s)", host, ip, server)
                    return ip
            except Exception as exc:  # noqa: BLE001 — this resolver is unreachable, try the next
                log.debug("doh %s via %s failed: %s", host, server, type(exc).__name__)
        log.warning("doh could not resolve %s via any of %s", host, ", ".join(self._servers))
        return None

    async def aclose(self) -> None:
        await self._client.aclose()


_SHARED: DohResolver | None = None


def shared_resolver() -> DohResolver:
    """One resolver per process — its cache and DoH client are reused."""
    global _SHARED
    if _SHARED is None:
        _SHARED = DohResolver()
    return _SHARED


async def close_shared_resolver() -> None:
    """Close and drop the process-wide resolver (its DoH httpx client)."""
    global _SHARED
    if _SHARED is not None:
        await _SHARED.aclose()
        _SHARED = None


class _DohBackend(httpcore.AnyIOBackend):
    """Swaps the connect IP for opted-in hosts; SNI/Host are untouched, so
    httpcore still starts TLS against the real hostname."""

    def __init__(self, resolver: DohResolver, hosts: frozenset[str]) -> None:
        super().__init__()
        self._resolver = resolver
        self._hosts = hosts

    async def connect_tcp(
        self, host: str, port: int, timeout: float | None = None,
        local_address: str | None = None, socket_options=None,
    ):
        target = host
        if host in self._hosts:
            ip = await self._resolver.resolve(host)
            if ip:
                target = ip
        return await super().connect_tcp(
            target, port, timeout=timeout,
            local_address=local_address, socket_options=socket_options,
        )


def doh_transport(
    hosts: frozenset[str], *, http2: bool, verify: bool = True,
    limits: httpx.Limits | None = None,
) -> httpx.AsyncHTTPTransport:
    """An httpx transport that resolves ``hosts`` via DoH. Other hosts (e.g. the
    DoH servers, redirects off-domain) fall through to the OS resolver. A custom
    transport bypasses client-level http2/verify/limits, so they are threaded
    through here to keep the provider's throttle caps in force."""
    kwargs: dict[str, Any] = {"http2": http2, "verify": verify}
    if limits is not None:
        kwargs["limits"] = limits
    transport = httpx.AsyncHTTPTransport(**kwargs)
    transport._pool._network_backend = _DohBackend(shared_resolver(), hosts)
    return transport
