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


def render_for_display(value):
    """Like `render`, but for text that is built ONCE and read for a long time.

    Tool descriptions are assembled at registration, so a concrete date baked into one
    is frozen at server start — fine for a desktop client that restarts often, wrong for
    an HTTP deployment running for weeks. That is the same rot the tokens exist to kill,
    with a longer fuse.

    So a description shows `<today>` / `<today+1>` instead of a date. It cannot go stale,
    and it tells the model what to compute rather than handing it a value to copy.
    """
    if isinstance(value, str):
        return _TOKEN.sub(lambda m: f"<today{m.group(1) or ''}>", value)
    if isinstance(value, list):
        return [render_for_display(v) for v in value]
    if isinstance(value, dict):
        return {k: render_for_display(v) for k, v in value.items()}
    return value


def has_token(value: object) -> bool:
    return "{{today" in str(value)
