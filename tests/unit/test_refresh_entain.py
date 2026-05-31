"""Entain hash-refresh: bundle discovery, hash extraction, diff, in-place rewrite."""

from __future__ import annotations

import textwrap
from pathlib import Path

import httpx
import pytest

from sportsdata_mcp.refresh.entain_hashes import (
    RefreshError,
    apply_changes,
    diff_operations,
    discover_bundle_url,
    extract_operations,
    fetch_latest_hashes,
    run_refresh,
)
from sportsdata_mcp.spec import GraphQLBlock, GraphQLOperation, HashRefresh, Provider, Spec

HOST = "https://www.ladbrokes.com.au"
PATTERN = "/assets/vendor-graphql-ops-web-*.js"

OLD = "a" * 64
NEW = "b" * 64
SAME = "c" * 64


def _spec(*ops: tuple[str, str]) -> Spec:
    return Spec(
        provider=Provider(
            id="entain",
            display_name="Entain",
            base_urls={"default": HOST},
            hash_refresh=HashRefresh(bundle_host=HOST, bundle_url_pattern=PATTERN),
        ),
        graphql=GraphQLBlock(operations=[GraphQLOperation(name=n, sha256=h) for n, h in ops]),
    )


# ─── bundle URL discovery ──────────────────────────────────────────────


def test_discover_bundle_url_resolves_relative():
    html = '<script src="/assets/vendor-graphql-ops-web-D59Og4AP.js" defer></script>'
    url = discover_bundle_url(html, PATTERN, HOST)
    assert url == f"{HOST}/assets/vendor-graphql-ops-web-D59Og4AP.js"


def test_discover_bundle_url_none_when_absent():
    assert discover_bundle_url("<html>nothing here</html>", PATTERN, HOST) is None


# ─── hash extraction (tolerant of key order + manifest map form) ───────


def test_extract_operations_handles_backtick_tuple_form():
    # The real Entain bundle stores [`Name`,`hash`] tuples with backtick strings.
    js = f"x=[[`HomeScreen`,`{SAME}`],[`HomeSportsScreen`,`{NEW}`]]"
    out = extract_operations(js)
    assert out == {"HomeScreen": SAME, "HomeSportsScreen": NEW}


def test_extract_operations_handles_name_then_hash():
    js = f'x={{name:"HomeSportsScreen",doc:1,hash:"{NEW}"}},y={{}}'
    assert extract_operations(js) == {"HomeSportsScreen": NEW}


def test_extract_operations_handles_hash_then_name():
    js = f"a({{hash:'{NEW}',name:'RacingRace'}})"
    assert extract_operations(js)["RacingRace"] == NEW


def test_extract_operations_handles_map_form():
    js = f'{{"SportingCategories":"{NEW}","RacingVideoChannels":"{SAME}"}}'
    out = extract_operations(js)
    assert out["SportingCategories"] == NEW
    assert out["RacingVideoChannels"] == SAME


# ─── diff ──────────────────────────────────────────────────────────────


def test_diff_partitions_changed_unchanged_missing():
    spec = _spec(("HomeSportsScreen", OLD), ("RacingRace", SAME), ("Retired", OLD))
    latest = {"HomeSportsScreen": NEW, "RacingRace": SAME}
    changed, unchanged, missing = diff_operations(spec, latest)
    assert [c.name for c in changed] == ["HomeSportsScreen"]
    assert changed[0].old == OLD and changed[0].new == NEW
    assert unchanged == ["RacingRace"]
    assert missing == ["Retired"]


# ─── in-place rewrite preserves formatting, touches only changed lines ──

_SPEC_TEXT = textwrap.dedent(
    f"""
    spec_version: 1
    provider:
      id: entain
      display_name: "Entain"
      base_urls:
        default: {HOST}
    graphql:
      operations:
        - {{ name: HomeSportsScreen, sha256: "{OLD}", variables: "x: Int" }}
        - {{ name: RacingRace, sha256: "{SAME}", variables: "raceId: ID!" }}
    """
).strip()


def test_apply_changes_rewrites_only_changed_hash(tmp_path: Path):
    p = tmp_path / "entain.yaml"
    p.write_text(_SPEC_TEXT + "\n")
    from sportsdata_mcp.refresh.entain_hashes import HashChange

    n = apply_changes(p, [HashChange("HomeSportsScreen", OLD, NEW)])
    assert n == 1
    text = p.read_text()
    assert f'sha256: "{NEW}"' in text  # changed
    assert f'sha256: "{SAME}"' in text  # untouched
    assert OLD not in text
    # Surrounding formatting (variables, the other line) is untouched.
    assert 'variables: "x: Int"' in text
    assert "- { name: RacingRace" in text


def test_apply_changes_noop_when_empty(tmp_path: Path):
    p = tmp_path / "entain.yaml"
    p.write_text(_SPEC_TEXT + "\n")
    assert apply_changes(p, []) == 0
    assert p.read_text() == _SPEC_TEXT + "\n"


# ─── fetch via a mocked transport ──────────────────────────────────────


def _mock_client(routes: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes[str(request.url)]

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_latest_hashes_end_to_end():
    bundle_url = f"{HOST}/assets/vendor-graphql-ops-web-ABC123.js"
    landing = httpx.Response(200, html='<script src="/assets/vendor-graphql-ops-web-ABC123.js"></script>')
    bundle = httpx.Response(200, text=f'{{name:"HomeSportsScreen",hash:"{NEW}"}}')
    client = _mock_client({HOST: landing, bundle_url: bundle})
    url, size, ops = fetch_latest_hashes(HOST, PATTERN, client=client)
    assert url == bundle_url
    assert size > 0
    assert ops == {"HomeSportsScreen": NEW}


def test_fetch_latest_hashes_raises_when_bundle_missing():
    landing = httpx.Response(200, html="<html>no bundle</html>")
    client = _mock_client({HOST: landing})
    with pytest.raises(RefreshError, match="no bundle"):
        fetch_latest_hashes(HOST, PATTERN, client=client)


def test_run_refresh_writes_changed_hash(tmp_path: Path):
    p = tmp_path / "entain.yaml"
    p.write_text(_SPEC_TEXT + "\n")
    spec = _spec(("HomeSportsScreen", OLD), ("RacingRace", SAME))
    bundle_url = f"{HOST}/assets/vendor-graphql-ops-web-ABC123.js"
    landing = httpx.Response(200, html='<script src="/assets/vendor-graphql-ops-web-ABC123.js"></script>')
    bundle = httpx.Response(200, text=f'{{name:"HomeSportsScreen",hash:"{NEW}"}},{{name:"RacingRace",hash:"{SAME}"}}')
    client = _mock_client({HOST: landing, bundle_url: bundle})

    result = run_refresh(spec, p, client=client, echo=lambda _s: None)
    assert [c.name for c in result.changed] == ["HomeSportsScreen"]
    assert result.unchanged == ["RacingRace"]
    assert f'sha256: "{NEW}"' in p.read_text()
