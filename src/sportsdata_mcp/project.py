"""Spec-declared, REDUCTIVE response projection.

The engine is a passthrough by design, and this is the second declared exception after
`classify` — but where `classify` *adds* a derived tag, this only ever *removes*. It
cannot invent a value, rename one, or reorder anything: whatever survives is byte-for-byte
what the provider sent.

WHY IT HAS TO EXIST
-------------------
FPL's `bootstrap-static` is one 1.37 MB blob holding six unrelated datasets. Measured:

    elements        1,447,462 bytes   (~362,000 tokens)   581 players x 105 fields
    events             29,201
    teams               8,258
    everything else    ~7,000
    ------------------------------
    TOTAL           1,493,607 bytes   (~373,000 tokens)

A 200k context window cannot hold that, so the single most useful endpoint in the whole
provider is unusable without slicing. FPL offers no server-side field selection and no
narrower route to the player list — one blob is all there is. The choice was a provider
whose flagship tool blows the caller's context, or a declared projection. Hence this.

WHAT IT DOES NOT DO
-------------------
It is not a query language, and deliberately so: no filtering by value, no computed
fields, no renaming, no sorting. Those would move the answer away from what the provider
actually said, which is the line `classify` also refuses to cross. If you find yourself
wanting `where points > 100`, that belongs in the caller, not here.
"""

from __future__ import annotations


def _pick_fields(item: object, fields: list[str]) -> object:
    """Keep only `fields` on a dict; anything else passes through untouched."""
    if not isinstance(item, dict):
        return item
    # Missing keys are simply absent rather than None — a provider that drops a field
    # should look like a provider that dropped a field, not like one returning nulls.
    return {k: item[k] for k in fields if k in item}


def apply_projection(
    body: dict | list,
    *,
    pick: list[str] | None = None,
    fields: list[str] | None = None,
) -> dict | list:
    """Reduce a decoded body. Returns it unchanged when neither is declared.

    `pick` keeps named top-level keys of a dict body. `fields` keeps named keys on the
    items of any list-of-dicts that is a direct value of the result — or on the items of
    the result itself when the body is a list.
    """
    if not pick and not fields:
        return body

    if pick and isinstance(body, dict):
        # Absent keys are skipped rather than erroring: a provider dropping a section is
        # drift for the drift check to catch, not a reason to fail the call.
        body = {k: body[k] for k in pick if k in body}

    if not fields:
        return body

    if isinstance(body, list):
        return [_pick_fields(item, fields) for item in body]

    if isinstance(body, dict):
        out: dict = {}
        for key, value in body.items():
            if isinstance(value, list):
                out[key] = [_pick_fields(item, fields) for item in value]
            else:
                # Scalars and nested objects are left alone — `fields` targets rows, and
                # silently gutting a metadata object would be the surprising reading.
                out[key] = value
        return out

    return body
