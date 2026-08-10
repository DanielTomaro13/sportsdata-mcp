"""Relative-date tokens for spec examples.

An example like::

    params: {eventDate: "2026-07-02"}

is wrong the moment it is written, and gets more wrong every day. Two things break:

  1. **The nightly drift check.** Sportsbet returns HTTP 400 for a racing date five weeks
     in the past, so the probe fails and the job goes red for a provider that is
     perfectly healthy. A drift check that cries wolf is worse than none, because people
     start ignoring it — and then miss the real breakage.
  2. **The model.** Tool descriptions carry the example, so a stale literal actively
     teaches the model to ask for a date in the past.

So examples write a token instead::

    params: {eventDate: "{{today}}"}
    params: {fromDate: "{{today}}T10:00:00", toDate: "{{today+1}}T10:00:59"}
    params: {date: "{{today-1}}-am"}

`{{today}}`, `{{today+N}}` and `{{today-N}}` render to an ISO date (YYYY-MM-DD) wherever
they appear inside a string, so any surrounding time format still works.

Deliberately NOT a general template language. Dates are the only thing in this catalogue
that rots on a clock; ids and season strings do not, and inventing substitutions for them
would just move the staleness somewhere harder to see.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

_TOKEN = re.compile(r"\{\{today([+-]\d+)?\}\}")


def _today() -> date:
    """UTC, matching how providers date their windows. A local-midnight "today" would
    make an Australian probe ask for tomorrow's card for several hours each day."""
    return datetime.now(tz=UTC).date()


def render(value):
    """Replace date tokens anywhere inside a string; pass everything else through.

    Recurses into lists and dicts so `string_csv` params and nested example bodies get
    the same treatment.
    """
    if isinstance(value, str):
        if "{{today" not in value:
            return value

        def _sub(m: re.Match) -> str:
            offset = int(m.group(1)) if m.group(1) else 0
            return (_today() + timedelta(days=offset)).isoformat()

        return _TOKEN.sub(_sub, value)
    if isinstance(value, list):
        return [render(v) for v in value]
    if isinstance(value, dict):
        return {k: render(v) for k, v in value.items()}
    return value


def render_params(params: dict | None) -> dict:
    return render(dict(params or {}))


def has_token(value: object) -> bool:
    return "{{today" in str(value)
