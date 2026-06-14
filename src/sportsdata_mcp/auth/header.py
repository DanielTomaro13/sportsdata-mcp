"""Static-header auth (literal value, env var, or config `secrets` block)."""

from __future__ import annotations

import os

from ..errors import AuthMissingError
from ..spec import AuthStaticHeader


class StaticHeaderAuthProvider:
    def __init__(self, spec: AuthStaticHeader, secrets: dict[str, str] | None = None) -> None:
        secrets = secrets or {}
        # Resolution order: env var > config `secrets` block (same key) > literal `value`.
        # When BOTH `env` and `value` are set, the env var overrides the literal — this
        # is the "public default key, overridable when it rotates" pattern (e.g. LaLiga's
        # public APIM subscription key). env-only still requires the var; value-only is
        # the fixed-key case (Pinnacle/FanDuel).
        value: str | None = None
        if spec.env:
            value = os.environ.get(spec.env) or secrets.get(spec.env)
        if value is None:
            value = spec.value
        if value is None:
            if spec.env:
                raise AuthMissingError(
                    f"env var {spec.env} not set (and no secrets['{spec.env}'] or literal `value` "
                    f"fallback); required for header {spec.header}"
                )
            raise AuthMissingError(f"auth.static_header for header '{spec.header}' has neither `value` nor `env`")
        # e.g. "Bearer " so the env var carries the bare token (X/Twitter).
        self._value = spec.value_prefix + value
        self._header = spec.header

    async def get(self) -> tuple[str, str]:
        return self._header, self._value

    def invalidate(self) -> None:
        pass
