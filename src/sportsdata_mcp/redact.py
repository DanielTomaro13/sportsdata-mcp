"""Keep credentials out of the logs.

Seven providers in this catalogue authenticate with a **query parameter** — Data Golf's
`?key=`, The Odds API's `?apiKey=`, CricketData's `?apikey=`, Sportmonks' `?api_token=`,
iSportsAPI's `?api_key=`, Entity Sport's `?token=`, Odds-API.io's `?apiKey=`. That means
the secret is part of the URL, and anything that logs a URL logs the secret.

Our own logging never did — it prints the base URL and passes params separately. But
`httpx` logs the fully-composed URL at INFO, and `hpack` logs the `:path` header at
DEBUG, so::

    sportsdata-mcp -v doctor

printed::

    INFO httpx: HTTP Request: GET https://api.the-odds-api.com/v4/sports?apiKey=SECRETKEY12345

Verbose mode is exactly what someone turns on when a provider is misbehaving, and
exactly the output they paste into a bug report. A leak there is not theoretical.

This installs a filter on the root logger that replaces every known secret value with
`***REDACTED***` wherever it appears — message, args or URL — so the fix does not depend
on which library did the logging or on remembering to silence a new one.

The values come from the env vars the specs themselves declare, so a provider added
later is covered without touching this file.
"""

from __future__ import annotations

import logging
import os

# Below this length a "secret" is more likely to be a placeholder ("test", "x") whose
# redaction would mangle unrelated log lines than a real credential.
_MIN_SECRET_LEN = 8

_PLACEHOLDER = "***REDACTED***"


def secret_values(specs=None, extra: dict[str, str] | None = None) -> set[str]:
    """Every credential value currently visible to this process.

    Read from the environment using the variable names the specs declare, so nothing has
    to be listed here by hand.
    """
    if specs is None:
        from .spec_loader import load_all_specs

        specs = load_all_specs()

    names: set[str] = set()
    for spec in specs:
        for auth in spec.provider.auth.values():
            for attr in ("env", "username_env", "password_env", "client_id_env", "client_secret_env"):
                if (name := getattr(auth, attr, None)):
                    names.add(name)

    values = {v for name in names if (v := os.environ.get(name))}
    values |= set((extra or {}).values())
    # A licence key is not provider auth but is just as bad in a pasted log.
    for name in ("SPORTSDATA_LICENSE", "SPORTSDATA_TELEMETRY_ENDPOINT"):
        if v := os.environ.get(name):
            values.add(v)
    return {v for v in values if len(v) >= _MIN_SECRET_LEN}


class RedactingFilter(logging.Filter):
    """Replaces known secret values anywhere in a record.

    Implemented as a filter rather than a formatter so it applies to every handler,
    including ones a host application installed before us.
    """

    def __init__(self, values: set[str]) -> None:
        super().__init__()
        # Longest first: if one secret contains another, redacting the short one first
        # would leave a recognisable fragment of the long one behind.
        self._values = sorted(values, key=len, reverse=True)

    def _scrub(self, text: str) -> str:
        for value in self._values:
            if value in text:
                text = text.replace(value, _PLACEHOLDER)
        return text

    def _scrub_arg(self, arg):
        """Scrub any argument whose STRING FORM carries a secret, not just `str` ones.

        httpx logs the URL as an `httpx.URL` object, so a str-only check silently missed
        the exact leak this class exists to stop. Converting to str is safe here because
        an argument only reaches this branch when it already contains a long credential —
        no `%d` int will.
        """
        if isinstance(arg, str):
            return self._scrub(arg)
        try:
            text = str(arg)
        except Exception:  # noqa: BLE001 - a broken __str__ must not break logging
            return arg
        return self._scrub(text) if any(v in text for v in self._values) else arg

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._values:
            return True
        if isinstance(record.msg, str) and any(v in record.msg for v in self._values):
            record.msg = self._scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub_arg(v) for k, v in record.args.items()}
            else:
                record.args = tuple(self._scrub_arg(a) for a in record.args)
        return True


def install(extra_secrets: dict[str, str] | None = None) -> RedactingFilter | None:
    """Attach the filter to the root logger's handlers. Safe to call more than once."""
    values = secret_values(extra=extra_secrets)
    if not values:
        return None
    filt = RedactingFilter(values)
    root = logging.getLogger()
    for handler in root.handlers:
        # Don't stack duplicates if a caller re-installs after adding a handler.
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(filt)
    return filt
