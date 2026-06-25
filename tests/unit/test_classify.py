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

# The real Dabble rule set, mirrored from dabble.yaml, used by several tests.
DABBLE_RULES = [
    {"prefix": "sportcast_", "value": "sgm"},
    {"contains": "pickem", "value": "pickem"},
    {"regex": "^RacingSrm", "value": "srm"},
    {"regex": "^Racing", "value": "racing"},
    {"default": "single"},
]


def _block(field: str, rules=DABBLE_RULES, source: str = "resultingType") -> Classify:
    return Classify.model_validate({"field": field, "from": source, "rules": rules})


# ─── rule matching ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "result_type,expected",
    [
        ("sportcast_anytime_goalscorer", "sgm"),
        ("odds_on_pickem_goals", "pickem"),
        ("match_score", "single"),
        ("BothHalvesResult", "single"),
        ("RacingSrmTop3", "srm"),  # SRM rule precedes the generic Racing rule
        ("RacingFixedWin", "racing"),
        ("RacingDDExacta", "racing"),
    ],
)
def test_product_buckets(result_type, expected):
    resp = {"d": {"markets": [{"resultingType": result_type}]}}
    apply_classify(resp, [_block("d.markets[].product")])
    assert resp["d"]["markets"][0]["product"] == expected


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


def test_missing_source_key_is_noop():
    resp = {"d": {"markets": [{"name": "no resultingType here"}]}}
    apply_classify(resp, [_block("d.markets[].product")])
    assert "product" not in resp["d"]["markets"][0]


# ─── path walking ──────────────────────────────────────────────────────


def test_doubly_nested_list_path():
    # data[].markets[].product — the dabble_competition_fixtures shape.
    resp = {
        "data": [
            {"markets": [{"resultingType": "sportcast_x"}, {"resultingType": "h2h"}]},
            {"markets": [{"resultingType": "odds_on_pickem_y"}]},
        ]
    }
    apply_classify(resp, [_block("data[].markets[].product")])
    got = [[m["product"] for m in f["markets"]] for f in resp["data"]]
    assert got == [["sgm", "single"], ["pickem"]]


def test_wrong_shape_is_noop_not_error():
    # markets is a dict, not a list — walker simply doesn't descend; no crash.
    resp = {"d": {"markets": {"resultingType": "sportcast_x"}}}
    apply_classify(resp, [_block("d.markets[].product")])
    assert resp == {"d": {"markets": {"resultingType": "sportcast_x"}}}


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
        {"prefix": "a"},  # matcher without value
        {"default": "x", "value": "y"},  # default must be lone
        {"default": "x", "prefix": "a"},  # default + matcher
        {"regex": "([", "value": "x"},  # uncompilable regex
    ],
)
def test_invalid_rules_rejected(rule):
    with pytest.raises(ValidationError):
        Classify.model_validate({"field": "d.m[].product", "from": "rt", "rules": [rule]})


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
        {"resultingType": "sportcast_x"},
        {"resultingType": "odds_on_pickem_y"},
        {"resultingType": "match_score"},
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
    body = {"sportFixtureDetail": {"markets": [{"resultingType": "sportcast_x"}]}}
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
