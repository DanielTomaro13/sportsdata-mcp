"""Static query-parameter auth (literal value, env var, or config `secrets` block).

For APIs that authenticate with a query parameter rather than a header — e.g. Data
Golf's `?key=`. The value is resolved the same way as static_header (env preferred,
then the config `secrets` block), so a personal/secret key never lives in the spec.
"""

from __future__ import annotations

import os

from ..errors import AuthMissingError
from ..spec import AuthStaticQuery


class StaticQueryAuthProvider:
    def __init__(self, spec: AuthStaticQuery, secrets: dict[str, str] | None = None) -> None:
        secrets = secrets or {}
        if spec.env:
            value = os.environ.get(spec.env)
            if value is None:
                value = secrets.get(spec.env)
            if value is None:
                raise AuthMissingError(
                    f"env var {spec.env} not set (and no secrets['{spec.env}']); required for query param {spec.param}"
                )
            self._value = value
        elif spec.value is not None:
            self._value = spec.value
        else:
            raise AuthMissingError(f"auth.static_query for param '{spec.param}' has neither `value` nor `env`")
        self._param = spec.param

    async def get(self) -> tuple[str, str]:
        return self._param, self._value

    def invalidate(self) -> None:
        pass
