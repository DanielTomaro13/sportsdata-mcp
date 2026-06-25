"""Apply spec-declared `classify` blocks to a fetched response.

This is the one place the engine deviates from pure passthrough — and only when an
endpoint opts in with a `classify` block. The deviation is deliberately minimal:
it *adds* a derived tag onto each item of a list, computed from that same item's
own source field, and never reads, mutates, or removes an upstream value. An
endpoint with no `classify` block never reaches this module.

See `spec.Classify` for the declaration model and `dabble.yaml` for the motivating
use (tagging each market `single|sgm|pickem|racing*` so Pick'em multipliers can't
be silently blended into a fixed-odds price comparison).
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from .spec import Classify

log = logging.getLogger("sportsdata_mcp.classify")


def _as_str(v: object) -> str:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _matched(value: object, kind: str, operand: object) -> bool:
    """Evaluate one precompiled matcher against an item's field value."""
    if kind == "eq":
        return value == operand
    if kind == "prefix":
        return _as_str(value).startswith(operand)  # type: ignore[arg-type]
    if kind == "contains":
        return operand in _as_str(value)  # type: ignore[operator]
    # "regex" — operand is a compiled pattern
    return operand.search(_as_str(value)) is not None  # type: ignore[union-attr]


def _rule_matcher(block: Classify) -> Callable[[dict], str | None]:
    """Compile a block's ordered rules into item-dict → tag (or None if nothing matched).

    Each rule reads its own `field` (falling back to the block's `from`); a string
    matcher coerces the read value to str, while `eq` compares the raw value (so a
    boolean capability flag matches `eq: true`). A `default` rule is terminal.
    """
    # Each entry is (field, kind, operand, tag); a default rule has field/kind None.
    compiled: list[tuple[str | None, str | None, object, str]] = []
    for r in block.rules:
        if r.default is not None:
            compiled.append((None, None, None, r.default))
            break  # a default is terminal; later rules are unreachable
        assert r.value is not None  # guaranteed by ClassifyRule validation
        fld = r.field or block.source
        assert fld is not None  # guaranteed by Classify validation
        if r.eq is not None:
            kind, operand = "eq", r.eq
        elif r.prefix is not None:
            kind, operand = "prefix", r.prefix
        elif r.contains is not None:
            kind, operand = "contains", r.contains
        else:  # regex (validation guarantees exactly one matcher is set)
            kind, operand = "regex", re.compile(r.regex)  # type: ignore[arg-type]
        compiled.append((fld, kind, operand, r.value))

    def classify(item: dict) -> str | None:
        for fld, kind, operand, tag in compiled:
            if fld is None:  # default rule
                return tag
            if _matched(item.get(fld), kind, operand):  # type: ignore[arg-type]
                return tag
        return None

    return classify


def _walk(node: object, segments: list[str], set_key: str, classify: Callable[[dict], str | None]) -> None:
    """Descend `segments`; at each terminal dict, set `set_key` from classifying the item."""
    if not segments:
        if isinstance(node, dict):
            tag = classify(node)
            if tag is not None:
                node[set_key] = tag
        return
    seg, rest = segments[0], segments[1:]
    is_list = seg.endswith("[]")
    key = seg[:-2] if is_list else seg
    if not isinstance(node, dict):
        return
    child = node.get(key)
    if is_list:
        if isinstance(child, list):
            for item in child:
                _walk(item, rest, set_key, classify)
    else:
        _walk(child, rest, set_key, classify)


def apply_classify(response: object, blocks: list[Classify]) -> object:
    """Apply every classify block to `response` in place (best-effort) and return it.

    Best-effort by design: a classifier must never turn a good response into an error.
    A path that doesn't resolve (wrong key, unexpected shape upstream) is simply a
    no-op for that block; a genuinely broken block is logged and skipped so the raw
    payload still reaches the caller.
    """
    if not blocks or not isinstance(response, (dict, list)):
        return response
    for block in blocks:
        try:
            classify = _rule_matcher(block)
            _walk(response, block.container_segments, block.set_key, classify)
        except Exception:  # pragma: no cover - defensive: never break a live response
            log.warning("classify block %r failed; returning raw payload for it", block.field, exc_info=True)
    return response
