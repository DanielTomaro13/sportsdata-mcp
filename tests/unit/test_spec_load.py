"""Spec loading + validation."""

from __future__ import annotations

import logging

import pytest

from sportsdata_mcp.errors import SpecValidationError
from sportsdata_mcp.spec import Spec
from sportsdata_mcp.spec_loader import load_all_specs, load_spec


def test_loads_provider_spec(specs_dir):
    specs = load_all_specs(specs_dir)
    assert len(specs) == 1
    assert specs[0].provider.id == "demo"
    assert specs[0].endpoints[0].name == "demo_match_get"


def test_skips_underscore_files(write_spec):
    d = write_spec({"demo.yaml": _DEMO})
    # _capabilities.yaml and _template-style files are ignored by the loader
    (d / "_template.yaml").write_text(_DEMO.replace("demo", "tmpl"))
    specs = load_all_specs(d)
    assert [s.provider.id for s in specs] == ["demo"]


def test_path_param_forced_required():
    spec = load_spec_from_string(_DEMO)
    match_get = spec.endpoints[0]
    matchid = next(p for p in match_get.params if p.name == "matchId")
    assert matchid.required is True


def test_undeclared_path_param_raises():
    bad = _DEMO.replace(
        "      - { name: matchId, in: path, type: string }\n", ""
    )
    with pytest.raises(SpecValidationError):
        load_spec_from_string(bad)


def test_duplicate_tool_names_across_specs_raise(write_spec):
    d = write_spec({"demo.yaml": _DEMO, "demo2.yaml": _DEMO.replace("id: demo", "id: demo2")})
    with pytest.raises(SpecValidationError, match="duplicate tool name"):
        load_all_specs(d)


def test_future_spec_version_warns(write_spec, caplog):
    d = write_spec({"demo.yaml": "spec_version: 99\n" + _DEMO})
    with caplog.at_level(logging.WARNING, logger="sportsdata_mcp.specs"):
        load_all_specs(d)
    assert any("spec_version=99" in r.message for r in caplog.records)


def test_templated_operation_rejects_unknown_key():
    """extra='forbid' turns a dispatcher-op typo into a hard error, not a silent drop."""
    from pydantic import ValidationError

    from sportsdata_mcp.spec import TemplatedOperation

    TemplatedOperation(name="x", path="/x", query_defaults={"a": "b"})  # valid baseline
    with pytest.raises(ValidationError):
        TemplatedOperation(name="x", path="/x", query_defualts={"a": "b"})  # typo'd key


def test_graphql_operation_rejects_unknown_key():
    from pydantic import ValidationError

    from sportsdata_mcp.spec import GraphQLOperation

    with pytest.raises(ValidationError):
        GraphQLOperation(name="X", sha256="a" * 64, verfied=True)  # typo'd key


# ── helpers / fixtures-as-text ──

_DEMO = """
provider:
  id: demo
  display_name: "Demo"
  base_urls:
    default: https://api.demo.test
  auth:
    default:
      type: none
endpoints:
  - name: demo_match_get
    group: demo.public.core
    capabilities: [sport.match_detail]
    summary: "Get a match by id"
    base: default
    path: /v2/matches/{matchId}
    params:
      - { name: matchId, in: path, type: string }
"""


def load_spec_from_string(text: str) -> Spec:
    import textwrap
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.yaml"
        p.write_text(textwrap.dedent(text).strip())
        return load_spec(p)
