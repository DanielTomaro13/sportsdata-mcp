"""Static-header auth (literal value, env var, or config `secrets` block)."""

from __future__ import annotations

import os

from ..errors import AuthMissingError
from ..spec import AuthStaticHeader


class StaticHeaderAuthProvider:
    def __init__(self, spec: AuthStaticHeader, secrets: dict[str, str] | None = None) -> None:
        secrets = secrets or {}
        if spec.env:
            # Prefer a real env var (production); fall back to the config `secrets`
            # block keyed by the same name (local use), per the documented precedence.
            value = os.environ.get(spec.env)
            if value is None:
                value = secrets.get(spec.env)
            if value is None:
                raise AuthMissingError(
                    f"env var {spec.env} not set (and no secrets['{spec.env}']); required for header {spec.header}"
                )
            self._value = value
        elif spec.value is not None:
            self._value = spec.value
        else:
            raise AuthMissingError(f"auth.static_header for header '{spec.header}' has neither `value` nor `env`")
        # e.g. "Bearer " so the env var carries the bare token (X/Twitter).
        self._value = spec.value_prefix + self._value
        self._header = spec.header

    async def get(self) -> tuple[str, str]:
        return self._header, self._value

    def invalidate(self) -> None:
        pass
