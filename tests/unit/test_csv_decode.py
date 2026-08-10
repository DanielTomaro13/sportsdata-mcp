"""CSV response decoding.

One provider (football-data.co.uk) publishes only as CSV. The decoder turns it into
row objects so the model still receives ordinary JSON — but it has to keep the same
safety guarantees the JSON path has, which is what most of these tests are about: a
bot-challenge page or an oversized body must NOT be fed to a CSV parser, where it
would quietly become one nonsense row instead of raising.
"""

from __future__ import annotations

import httpx
import pytest

from sportsdata_mcp.config import Config
from sportsdata_mcp.errors import ToolError
from sportsdata_mcp.http_client import HTTPClient
from sportsdata_mcp.spec import AuthNone, Provider

CSV_BODY = (
    "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H\n"
    "E0,16/08/2024,Man United,Fulham,1,0,H,1.6\n"
    "E0,17/08/2024,Ipswich,Liverpool,0,2,A,6.5\n"
)


def _client(body: str, *, status: int = 200, ctype: str = "text/csv", cfg: Config | None = None):
    provider = Provider(
        id="demo", display_name="Demo",
        base_urls={"default": "https://csv.demo.test"},
        auth={"default": AuthNone()},
    )
    http = HTTPClient(provider, cfg or Config(cache_ttl_override=0))
    http._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(status, text=body, headers={"content-type": ctype})
        )
    )
    return http


async def test_rows_are_keyed_by_the_header():
    http = _client(CSV_BODY)
    rows = await http.request_json(method="GET", base="default", url="/x.csv", response_format="csv")
    assert len(rows) == 2
    assert rows[0]["HomeTeam"] == "Man United"
    assert rows[0]["FTR"] == "H"
    assert rows[1]["B365H"] == "6.5"
    await http.aclose()


async def test_a_utf8_bom_does_not_poison_the_first_column_name():
    """These files are Windows-authored. Left in, the BOM becomes part of the first
    header ("﻿Div") and every lookup of that column silently misses."""
    http = _client("﻿" + CSV_BODY)
    rows = await http.request_json(method="GET", base="default", url="/x.csv", response_format="csv")
    assert next(iter(rows[0])) == "Div"
    assert rows[0]["Div"] == "E0"
    await http.aclose()


async def test_trailing_blank_lines_are_dropped():
    """The real files end with blank lines, which DictReader turns into all-empty rows —
    they'd otherwise show up as phantom matches."""
    http = _client(CSV_BODY + "\n\n,,,,,,,\n")
    rows = await http.request_json(method="GET", base="default", url="/x.csv", response_format="csv")
    assert len(rows) == 2
    await http.aclose()


async def test_http_error_raises_instead_of_parsing_the_error_page():
    """A 404 body is not data. Without the status guard the CSV parser would happily
    turn an HTML error page into a single garbage row."""
    http = _client("<html>Not found</html>", status=404, ctype="text/html")
    with pytest.raises(ToolError) as ei:
        await http.request_json(method="GET", base="default", url="/x.csv", response_format="csv")
    assert ei.value.code == "HTTP_404"
    await http.aclose()


async def test_rate_limit_is_reported_as_such():
    http = _client("", status=429)
    with pytest.raises(ToolError) as ei:
        await http.request_json(method="GET", base="default", url="/x.csv", response_format="csv")
    assert ei.value.code == "HTTP_429"
    await http.aclose()


async def test_size_cap_applies_to_csv_too():
    """The response-size cap protects the model's context — it must not be bypassed
    just because the body is CSV."""
    big = "a,b\n" + ("1,2\n" * 5000)
    http = _client(big, cfg=Config(cache_ttl_override=0, max_bytes_override=1000))
    with pytest.raises(ToolError) as ei:
        await http.request_json(method="GET", base="default", url="/x.csv", response_format="csv")
    assert ei.value.code == "RESPONSE_TOO_LARGE"
    await http.aclose()


async def test_json_endpoints_are_unaffected():
    """The default stays JSON — CSV is opt-in per endpoint."""
    http = _client('{"ok": true}', ctype="application/json")
    out = await http.request_json(method="GET", base="default", url="/x.json")
    assert out == {"ok": True}
    await http.aclose()


def test_only_footballdatauk_declares_csv():
    """If a second provider ever needs CSV that's fine — but it should be a deliberate
    choice, not something that spread by copy-paste."""
    from sportsdata_mcp.spec_loader import load_all_specs

    csv_providers = {
        s.provider.id
        for s in load_all_specs()
        for ep in s.endpoints
        if getattr(ep, "response_format", "json") == "csv"
    }
    assert csv_providers == {"footballdatauk"}
