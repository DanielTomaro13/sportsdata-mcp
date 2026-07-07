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


# ─── document flow: printed docs → self-consistent hashes → sidecar + registration ──

_AST_LITERAL = (
    "{kind:`Document`,definitions:[{kind:`OperationDefinition`,operation:`query`,"
    "name:{kind:`Name`,value:`HomeSportsScreen`},selectionSet:{kind:`SelectionSet`,"
    "selections:[{kind:`Field`,name:{kind:`Name`,value:`ping`}}]}}]}"
)
_PRINTED = "query HomeSportsScreen {\n  ping\n}"


def _spec_with_dispatcher(*ops: tuple[str, str]) -> Spec:
    from sportsdata_mcp.spec import Dispatcher

    spec = _spec(*ops)
    return spec.model_copy(
        update={
            "dispatchers": [
                Dispatcher(
                    name="entain_graphql_call",
                    group="entain.graphql",
                    kind="graphql_persisted",
                    summary="x",
                    endpoint="/gql/router",
                    catalog_resource="entain://graphql/operations",
                )
            ]
        }
    )


def test_run_refresh_document_flow_writes_sidecar_and_registers(tmp_path: Path):
    import hashlib
    import json as _json

    p = tmp_path / "entain.yaml"
    p.write_text(_SPEC_TEXT + "\n")
    spec = _spec_with_dispatcher(("HomeSportsScreen", OLD), ("RacingRace", SAME))
    doc_sha = hashlib.sha256(_PRINTED.encode()).hexdigest()

    bundle_url = f"{HOST}/assets/vendor-graphql-ops-web-ABC123.js"
    # HomeSportsScreen ships as an AST literal; RacingRace only in the manifest.
    bundle_js = f"x={_AST_LITERAL};y={{name:\"RacingRace\",hash:\"{SAME}\"}}"
    gateway_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == HOST:
            return httpx.Response(200, html='<script src="/assets/vendor-graphql-ops-web-ABC123.js"></script>')
        if url == bundle_url:
            return httpx.Response(200, text=bundle_js)
        if request.url.path == "/gql/router":
            gateway_calls.append(request)
            return httpx.Response(200, json={"data": {}})
        raise AssertionError(f"unexpected request: {url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = run_refresh(spec, p, client=client, echo=lambda _s: None)

    # The hash is sha256(printed document), not any manifest value.
    assert [c.name for c in result.changed] == ["HomeSportsScreen"]
    assert result.changed[0].new == doc_sha
    assert result.unchanged == ["RacingRace"]  # manifest fallback still matched
    assert f'sha256: "{doc_sha}"' in p.read_text()

    # The pair was registered with the gateway (POST) and probed (GET).
    assert [r.method for r in gateway_calls] == ["POST", "GET"]
    posted = _json.loads(gateway_calls[0].content)
    assert posted["query"] == _PRINTED
    assert posted["extensions"]["persistedQuery"]["sha256Hash"] == doc_sha
    assert result.register_failed == []

    # The sidecar carries the printed document for runtime self-heal.
    sidecar = tmp_path / "entain.documents.json"
    assert result.documents_written == 1
    assert _json.loads(sidecar.read_text()) == {"HomeSportsScreen": _PRINTED}


def test_run_refresh_dry_run_touches_nothing(tmp_path: Path):
    p = tmp_path / "entain.yaml"
    p.write_text(_SPEC_TEXT + "\n")
    spec = _spec_with_dispatcher(("HomeSportsScreen", OLD))
    bundle_url = f"{HOST}/assets/vendor-graphql-ops-web-ABC123.js"
    landing = httpx.Response(200, html='<script src="/assets/vendor-graphql-ops-web-ABC123.js"></script>')
    bundle = httpx.Response(200, text=f"x={_AST_LITERAL}")
    client = _mock_client({HOST: landing, bundle_url: bundle})  # no gateway route: any POST would KeyError

    result = run_refresh(spec, p, write=False, client=client, echo=lambda _s: None)
    assert [c.name for c in result.changed] == ["HomeSportsScreen"]
    assert result.documents == {"HomeSportsScreen": _PRINTED}
    assert result.documents_written == 0
    assert p.read_text() == _SPEC_TEXT + "\n"
    assert not (tmp_path / "entain.documents.json").exists()


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
