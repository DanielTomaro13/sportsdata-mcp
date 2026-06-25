"""Spec-declared response classifier: additive product tagging, passthrough preserved.

Covers the engine `classify` feature end to end — the rule matcher, the (possibly
nested) path walker, spec validation of malformed rules, and the wiring through
`make_endpoint_handler` (an endpoint with no `classify` block stays pure passthrough).
The motivating data shapes are Dabble's, re-probed live 2026-06-25.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from sportsdata_mcp.classify import apply_classify
from sportsdata_mcp.config import Config
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.registry import make_endpoint_handler
from sportsdata_mcp.spec import AuthNone, Classify, Endpoint, Provider
from sportsdata_mcp.spec_loader import load_spec

# The real Dabble rule set, mirrored from dabble.yaml. SGM is detected by the
# provider-agnostic capability flags, NOT a third-party engine prefix.
DABBLE_RULES = [
    {"regex": "^RacingSrm", "value": "srm"},
    {"regex": "^Racing", "value": "racing"},
    {"contains": "pickem", "value": "pickem"},
    {"field": "isSingleAllowed", "eq": True, "value": "single"},
    {"field": "isSgmAllowed", "eq": True, "value": "sgm"},
    {"default": "single"},
]


def _block(field: str, rules=DABBLE_RULES, source: str | None = "resultingType") -> Classify:
    spec = {"field": field, "rules": rules}
    if source is not None:
        spec["from"] = source
    return Classify.model_validate(spec)


# ─── rule matching (the real Dabble taxonomy over realistic market dicts) ──


@pytest.mark.parametrize(
    "market,expected",
    [
        # SGM-only legs are tagged from the flag — independent of resultingType naming.
        ({"resultingType": "sportcast_anytime_goalscorer", "isSgmAllowed": True, "isSingleAllowed": False}, "sgm"),
        # A non-sportcast SGM-only leg (would-be-mislabeled by a prefix rule) → sgm.
        ({"resultingType": "SomeOtherEngine_thing", "isSgmAllowed": True, "isSingleAllowed": False}, "sgm"),
        # If the SGM vendor changes the prefix entirely, the flag still classifies it.
        ({"resultingType": "newvendor_margin", "isSgmAllowed": True, "isSingleAllowed": False}, "sgm"),
        ({"resultingType": "odds_on_pickem_goals", "isSingleAllowed": False, "isSgmAllowed": False}, "pickem"),
        ({"resultingType": "match_score", "isSingleAllowed": True, "isSgmAllowed": False}, "single"),
        # Exotic single with no isSingleAllowed key → default single.
        ({"resultingType": "MatchExact_TotalPoints", "isSgmAllowed": False}, "single"),
        ({"resultingType": "RacingSrmTop3"}, "srm"),  # SRM rule precedes generic Racing
        ({"resultingType": "RacingFixedWin", "isSingleAllowed": True}, "racing"),  # racing wins over single flag
        ({"resultingType": "RacingDDExacta"}, "racing"),
    ],
)
def test_product_buckets(market, expected):
    resp = {"d": {"markets": [market]}}
    apply_classify(resp, [_block("d.markets[].product")])
    assert resp["d"]["markets"][0]["product"] == expected


def test_eq_matches_boolean_flag_only_when_true():
    rules = [{"field": "flag", "eq": True, "value": "yes"}]
    for val, present in [(True, True), (False, False), (None, False)]:
        item = {"flag": val} if val is not None else {}
        resp = {"d": {"markets": [item]}}
        apply_classify(resp, [_block("d.markets[].product", rules=rules)])
        assert ("product" in resp["d"]["markets"][0]) is present


def test_first_match_wins_ordering():
    # A value that satisfies two matchers must take the earlier one.
    rules = [{"prefix": "ab", "value": "first"}, {"contains": "cd", "value": "second"}]
    resp = {"d": {"markets": [{"resultingType": "abcd"}]}}
    apply_classify(resp, [_block("d.markets[].product", rules=rules)])
    assert resp["d"]["markets"][0]["product"] == "first"


def test_no_match_no_default_leaves_field_unset():
    rules = [{"prefix": "zzz", "value": "x"}]  # no default
    resp = {"d": {"markets": [{"resultingType": "match_score"}]}}
    apply_classify(resp, [_block("d.markets[].product", rules=rules)])
    assert "product" not in resp["d"]["markets"][0]


def test_missing_source_key_with_no_default_is_noop():
    rules = [{"contains": "pickem", "value": "pickem"}]  # no default
    resp = {"d": {"markets": [{"name": "no resultingType here"}]}}
    apply_classify(resp, [_block("d.markets[].product", rules=rules)])
    assert "product" not in resp["d"]["markets"][0]


def test_default_rule_tags_everything_left():
    # With a default present, an item matching nothing else still gets tagged.
    resp = {"d": {"markets": [{"name": "bare"}]}}  # no resultingType, no flags
    apply_classify(resp, [_block("d.markets[].product")])
    assert resp["d"]["markets"][0]["product"] == "single"


# ─── path walking ──────────────────────────────────────────────────────


def test_doubly_nested_list_path():
    # data[].markets[].product — the dabble_competition_fixtures shape.
    resp = {
        "data": [
            {"markets": [
                {"resultingType": "x", "isSgmAllowed": True, "isSingleAllowed": False},
                {"resultingType": "h2h", "isSingleAllowed": True},
            ]},
            {"markets": [{"resultingType": "odds_on_pickem_y", "isSingleAllowed": False}]},
        ]
    }
    apply_classify(resp, [_block("data[].markets[].product")])
    got = [[m["product"] for m in f["markets"]] for f in resp["data"]]
    assert got == [["sgm", "single"], ["pickem"]]


def test_wrong_shape_is_noop_not_error():
    # markets is a dict, not a list — walker simply doesn't descend; no crash.
    resp = {"d": {"markets": {"resultingType": "x", "isSgmAllowed": True}}}
    apply_classify(resp, [_block("d.markets[].product")])
    assert resp == {"d": {"markets": {"resultingType": "x", "isSgmAllowed": True}}}


def test_non_dict_list_response_untouched():
    assert apply_classify([1, 2, 3], [_block("d.markets[].product")]) == [1, 2, 3]
    assert apply_classify("scalar", [_block("d.markets[].product")]) == "scalar"


def test_empty_blocks_is_identity():
    obj = {"a": 1}
    assert apply_classify(obj, []) is obj


# ─── spec validation ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rule",
    [
        {"value": "x"},  # matcher missing
        {"prefix": "a", "contains": "b", "value": "x"},  # two matchers
        {"eq": True, "prefix": "a", "value": "x"},  # eq + string matcher
        {"prefix": "a"},  # matcher without value
        {"field": "f", "eq": True},  # eq matcher without value
        {"default": "x", "value": "y"},  # default must be lone
        {"default": "x", "prefix": "a"},  # default + matcher
        {"default": "x", "field": "f"},  # default must not pin a field
        {"regex": "([", "value": "x"},  # uncompilable regex
    ],
)
def test_invalid_rules_rejected(rule):
    with pytest.raises(ValidationError):
        Classify.model_validate({"field": "d.m[].product", "from": "rt", "rules": [rule]})


def test_rule_without_field_and_no_block_from_rejected():
    # A non-default rule must resolve a field — either its own or the block default.
    with pytest.raises(ValidationError):
        Classify.model_validate({"field": "d.m[].product", "rules": [{"contains": "x", "value": "y"}]})


def test_per_rule_field_without_block_from_is_valid():
    block = Classify.model_validate(
        {"field": "d.m[].product", "rules": [{"field": "flag", "eq": True, "value": "y"}, {"default": "n"}]}
    )
    assert block.source is None
    resp = {"d": {"m": [{"flag": True}, {"flag": False}]}}
    apply_classify(resp, [block])
    assert [m["product"] for m in resp["d"]["m"]] == ["y", "n"]


@pytest.mark.parametrize("field", ["product", "markets[]", "d.markets[].sub[]"])
def test_invalid_field_shape_rejected(field):
    with pytest.raises(ValidationError):
        Classify.model_validate({"field": field, "from": "rt", "rules": [{"default": "x"}]})


def test_segments_and_setkey_parsing():
    b = _block("sportFixtureDetail.markets[].product")
    assert b.container_segments == ["sportFixtureDetail", "markets[]"]
    assert b.set_key == "product"


# ─── wiring through the endpoint handler ───────────────────────────────


def _http_with_response(body: dict) -> HTTPClient:
    provider = Provider(
        id="demo",
        display_name="Demo",
        base_urls={"default": "https://api.demo.test"},
        auth={"default": AuthNone()},
    )
    http = HTTPClient(provider, Config())
    http._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)),
        headers={},
    )
    return http


@pytest.mark.asyncio
async def test_handler_applies_classify():
    body = {"sportFixtureDetail": {"markets": [
        {"resultingType": "sportcast_x", "isSgmAllowed": True, "isSingleAllowed": False},
        {"resultingType": "odds_on_pickem_y", "isSingleAllowed": False},
        {"resultingType": "match_score", "isSingleAllowed": True},
    ]}}
    ep = Endpoint(
        name="demo_details", group="demo.sport", summary="x",
        path="/details",
        classify=[_block("sportFixtureDetail.markets[].product")],
    )
    handler = make_endpoint_handler(ep, _http_with_response(body))
    out = await handler()
    assert [m["product"] for m in out["sportFixtureDetail"]["markets"]] == ["sgm", "pickem", "single"]


@pytest.mark.asyncio
async def test_handler_without_classify_is_pure_passthrough():
    body = {"sportFixtureDetail": {"markets": [{"resultingType": "x", "isSgmAllowed": True}]}}
    ep = Endpoint(name="demo_raw", group="demo.sport", summary="x", path="/raw")  # no classify
    handler = make_endpoint_handler(ep, _http_with_response(body))
    out = await handler()
    assert out == body  # untouched — no `product` injected anywhere


# ─── the shipped dabble.yaml spec ──────────────────────────────────────


def test_dabble_spec_classify_wired_on_both_endpoints():
    spec = load_spec(Path("src/sportsdata_mcp/specs/dabble.yaml"))
    by_name = {e.name: e for e in spec.endpoints}
    det = by_name["dabble_fixture_details"].classify
    fx = by_name["dabble_competition_fixtures"].classify
    assert det and det[0].field == "sportFixtureDetail.markets[].product"
    assert fx and fx[0].field == "data[].markets[].product"
    # YAML anchor → identical rule set on both.
    assert [r.model_dump() for r in det[0].rules] == [r.model_dump() for r in fx[0].rules]
    assert det[0].source == "resultingType"
