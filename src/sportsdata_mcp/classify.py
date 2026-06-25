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

from .spec import Classify, ClassifyRule

log = logging.getLogger("sportsdata_mcp.classify")


def _rule_matcher(rules: list[ClassifyRule]) -> Callable[[object], str | None]:
    """Compile the ordered rules into source-value → tag (or None if nothing matched)."""
    compiled: list[tuple[Callable[[str], bool], str]] = []
    for r in rules:
        if r.default is not None:
            compiled.append((lambda _s: True, r.default))
            break  # a default is terminal; later rules are unreachable
        assert r.value is not None  # guaranteed by ClassifyRule validation
        if r.prefix is not None:
            pfx = r.prefix
            compiled.append((lambda s, pfx=pfx: s.startswith(pfx), r.value))
        elif r.contains is not None:
            sub = r.contains
            compiled.append((lambda s, sub=sub: sub in s, r.value))
        else:  # regex (validation guarantees one of the three is set)
            rx = re.compile(r.regex)  # type: ignore[arg-type]
            compiled.append((lambda s, rx=rx: rx.search(s) is not None, r.value))

    def classify(raw: object) -> str | None:
        s = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
        for test, tag in compiled:
            if test(s):
                return tag
        return None

    return classify


def _walk(node: object, segments: list[str], source: str, set_key: str, classify: Callable[[object], str | None]) -> None:
    """Descend `segments`; at each terminal dict, set `set_key` from classifying `source`."""
    if not segments:
        if isinstance(node, dict) and source in node:
            tag = classify(node[source])
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
                _walk(item, rest, source, set_key, classify)
    else:
        _walk(child, rest, source, set_key, classify)


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
            classify = _rule_matcher(block.rules)
            _walk(response, block.container_segments, block.source, block.set_key, classify)
        except Exception:  # pragma: no cover - defensive: never break a live response
            log.warning("classify block %r failed; returning raw payload for it", block.field, exc_info=True)
    return response
