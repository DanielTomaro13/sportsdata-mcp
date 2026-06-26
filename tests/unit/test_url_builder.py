"""Request-building helpers in registry: path interpolation, query encoding, body merge."""

from __future__ import annotations

from sportsdata_mcp.registry import (
    _build_body,
    _build_headers,
    _build_query,
    _interpolate_path,
    _python_type,
)
from sportsdata_mcp.spec import Endpoint, Param


def _ep(params: list[dict], *, path: str = "/v2/x", method: str = "GET") -> Endpoint:
    return Endpoint(
        name="t_tool",
        group="t.public.core",
        summary="s",
        method=method,
        path=path,
        params=[Param.model_validate(p) for p in params],
    )


def test_interpolate_path():
    ep = _ep([{"name": "matchId", "in": "path", "type": "string"}], path="/v2/matches/{matchId}")
    assert _interpolate_path(ep, {"matchId": "CD_M1"}) == "/v2/matches/CD_M1"


def test_path_param_with_suffix_is_required_and_interpolates():
    """A placeholder carrying a suffix (e.g. Kambi's `{eventId}.json`) must still be
    detected as a path param — marked required and interpolated — not missed by a
    whole-segment check."""
    ep = _ep(
        [{"name": "eventId", "in": "path", "type": "integer"}],
        path="/statistics/event/{eventId}.json",
    )
    eid = next(p for p in ep.params if p.name == "eventId")
    assert eid.required is True
    assert _interpolate_path(ep, {"eventId": 123}) == "/statistics/event/123.json"


def test_path_param_with_default_is_optional_and_falls_back():
    """A path param that declares a default is optional — the default is interpolated
    when the caller omits it (e.g. a `mode` segment defaulting to 'classic')."""
    ep = _ep(
        [{"name": "mode", "in": "path", "type": "string", "default": "classic"}],
        path="/api/{mode}/v1/settings",
    )
    mode = next(p for p in ep.params if p.name == "mode")
    assert mode.required is False  # default makes it optional
    assert _interpolate_path(ep, {}) == "/api/classic/v1/settings"  # omitted → default
    assert _interpolate_path(ep, {"mode": "draft"}) == "/api/draft/v1/settings"  # explicit wins


def test_build_query_skips_none_and_keeps_defaults():
    ep = _ep(
        [
            {"name": "page", "in": "query", "type": "integer", "default": 0},
            {"name": "q", "in": "query", "type": "string"},
        ]
    )
    assert _build_query(ep, {"page": 2, "q": None}) == {"page": 2}


def test_build_query_csv_join():
    ep = _ep([{"name": "ids", "in": "query", "type": "string_csv"}])
    assert _build_query(ep, {"ids": ["a", "b", "c"]}) == {"ids": "a,b,c"}


def test_build_query_json_accepts_arrays():
    """`json` params are ANY JSON value. Typing them dict-only forced models to wrap
    arrays in objects — reproduced live as Entain's 500 ("cannot unmarshal object
    into []uuid.UUID"). Arrays must encode as compact JSON arrays."""
    from sportsdata_mcp.registry import _PY_TYPES

    ep = _ep([{"name": "category_ids", "in": "query", "type": "json"}])
    assert _build_query(ep, {"category_ids": ["u1", "u2"]}) == {"category_ids": '["u1","u2"]'}
    assert _PY_TYPES["json"] is object  # tool signature must admit lists, not just dicts


def test_build_query_json_encode():
    ep = _ep([{"name": "filter", "in": "query", "type": "json"}])
    assert _build_query(ep, {"filter": {"k": 1}}) == {"filter": '{"k":1}'}


def test_build_headers():
    ep = _ep([{"name": "X-Trace", "in": "header", "type": "string"}])
    assert _build_headers(ep, {"X-Trace": "abc"}) == {"X-Trace": "abc"}


def test_build_body_merges_named_params():
    ep = _ep(
        [
            {"name": "a", "in": "body", "type": "string"},
            {"name": "b", "in": "body", "type": "integer"},
        ],
        method="POST",
    )
    assert _build_body(ep, {"a": "x", "b": 2}) == {"a": "x", "b": 2}


def test_build_body_single_object_is_whole_body():
    ep = _ep([{"name": "payload", "in": "body", "type": "object"}], method="POST")
    assert _build_body(ep, {"payload": {"nested": True}}) == {"nested": True}


def test_build_body_none_when_no_body_params():
    ep = _ep([{"name": "page", "in": "query", "type": "integer"}])
    assert _build_body(ep, {"page": 1}) is None


def test_python_type_mapping():
    assert _python_type(Param(name="a", **{"in": "query"}, type="integer")) is int
    assert _python_type(Param(name="a", **{"in": "query"}, type="boolean")) is bool
    assert _python_type(Param(name="a", **{"in": "query"}, type="string_csv")) is list
    assert _python_type(Param(name="a", **{"in": "body"}, type="object")) is dict


def test_build_query_api_name_maps_wire_name():
    """`api_name` carries the wire name when it isn't a valid Python identifier
    (X's `tweet.fields`); the signature param stays `tweet_fields`."""
    ep = _ep([{"name": "tweet_fields", "in": "query", "type": "string", "api_name": "tweet.fields"}])
    assert _build_query(ep, {"tweet_fields": "created_at,lang"}) == {"tweet.fields": "created_at,lang"}
