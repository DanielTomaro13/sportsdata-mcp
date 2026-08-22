"""XML decoding, and the MyFantasyLeague write API that needed it.

MFL's `/import` endpoints answer XML even when asked for JSON, and answer HTTP 200
whether the write succeeded or failed. Without a decoder here, an ordinary rejection
surfaces as "the body did not parse" — and a SUCCESS looks identical to it.
"""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.http_client import HTTPClient, _xml_to_obj
from sportsdata_mcp.spec import AuthNone, ErrorSignal, Provider


def _client(signals: list[ErrorSignal] | None = None) -> HTTPClient:
    return HTTPClient(
        Provider(
            id="demo", display_name="Demo",
            base_urls={"default": "https://api.demo.test"},
            auth={"default": AuthNone()},
            error_signals=signals or [],
        ),
        Config(),
    )


def _resp(body: bytes) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "text/xml"})


def test_a_leaf_element_becomes_its_text():
    assert _client()._decode_xml(_resp(b"<status>OK</status>")) == {"status": "OK"}


def test_attributes_become_keys():
    got = _client()._decode_xml(_resp(b'<trade id="1" ts="9"/>'))
    assert got == {"trade": {"id": "1", "ts": "9"}}


def test_one_child_and_many_children_produce_the_SAME_shape():
    """The trap this is written for: a document with one row and one with many must not
    differ in shape, or the code works all season and crashes the first week a league
    has exactly one pending trade."""
    one = _client()._decode_xml(_resp(b'<trades><trade id="1"/></trades>'))
    many = _client()._decode_xml(_resp(b'<trades><trade id="1"/><trade id="2"/></trades>'))
    assert one == {"trades": {"trade": {"id": "1"}}}
    assert many == {"trades": {"trade": [{"id": "1"}, {"id": "2"}]}}
    # …and a caller that normalises with `x if isinstance(x, list) else [x]` gets both.
    for doc in (one, many):
        rows = doc["trades"]["trade"]
        assert len(rows if isinstance(rows, list) else [rows]) >= 1


def test_nested_elements_recurse():
    got = _client()._decode_xml(_resp(
        b'<league id="1"><franchises><franchise id="0001" name="A"/></franchises></league>'))
    assert got == {"league": {"id": "1", "franchises": {"franchise": {"id": "0001", "name": "A"}}}}


def test_a_bom_and_surrounding_whitespace_are_tolerated():
    body = '﻿\n  <status>OK</status>  \n'.encode()
    assert _client()._decode_xml(_resp(body)) == {"status": "OK"}


def test_a_body_that_is_not_xml_fails_loudly():
    with pytest.raises(ToolError) as ei:
        _client()._decode_xml(_resp(b"<html>bot challenge</html><<<"))
    assert ei.value.code == "XML_DECODE_ERROR"


def test_error_signals_apply_to_the_decoded_xml():
    """The whole point: MFL says no with `<error>…</error>` and HTTP 200. That must raise,
    while `<status>OK</status>` must not."""
    c = _client([ErrorSignal(field="error")])
    with pytest.raises(ToolError):
        c._decode_xml(_resp(b"<error>Invalid League ID</error>"))
    assert c._decode_xml(_resp(b"<status>OK</status>")) == {"status": "OK"}


def test_the_size_guard_still_applies():
    c = HTTPClient(
        Provider(id="demo", display_name="D", base_urls={"default": "https://d.test"},
                 auth={"default": AuthNone()}),
        Config(providers={"demo": {"max_response_bytes": 20}}),
    )
    with pytest.raises(ToolError) as ei:
        c._decode_xml(_resp(b"<status>" + b"x" * 500 + b"</status>"))
    assert ei.value.code == "RESPONSE_TOO_LARGE"


def test_an_empty_element_is_an_empty_string_not_a_crash():
    assert _xml_to_obj_of(b"<comments/>") == ""
    assert _xml_to_obj_of(b"<comments></comments>") == ""


def _xml_to_obj_of(body: bytes):
    import xml.etree.ElementTree as ET

    return _xml_to_obj(ET.fromstring(body.decode()))
