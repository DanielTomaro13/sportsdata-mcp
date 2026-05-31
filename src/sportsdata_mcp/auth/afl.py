"""AFL anonymous WMCTok token provider."""

from __future__ import annotations

import asyncio

import httpx

from ..spec import AuthAFLWMCTok


class AFLTokenProvider:
    """Mints anonymous `x-media-mis-token` from `/cfs/afl/WMCTok` and caches it in memory."""

    def __init__(self, spec: AuthAFLWMCTok, http: httpx.AsyncClient) -> None:
        self._spec = spec
        self._http = http
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> tuple[str, str]:
        if self._token:
            return self._spec.header, self._token
        async with self._lock:
            if self._token:
                return self._spec.header, self._token
            r = await self._http.post(self._spec.mint_url, headers=self._spec.mint_headers)
            r.raise_for_status()
            payload = r.json()
            # AWS API GW envelope wraps the body in {"body": "<json>"} sometimes;
            # the token also sometimes appears as `token` or `mediaAuthToken`.
            token = (
                payload.get("token")
                or payload.get("mediaAuthToken")
                or payload.get("data", {}).get("token")
            )
            if not token:
                raise RuntimeError(f"WMCTok response did not contain a token: keys={list(payload.keys())}")
            self._token = token
            return self._spec.header, self._token

    def invalidate(self) -> None:
        self._token = None
