"""Lint rules + capability index."""

from __future__ import annotations

from sportsdata_mcp.spec_loader import build_provider_index, lint, load_all_specs


def test_lint_passes_on_valid_specs(specs_dir):
    errors, _warnings = lint(specs_dir)
    assert errors == []


def test_lint_flags_undefined_capability(write_spec):
    spec = """
    provider:
      id: bad
      display_name: "Bad"
      base_urls: {default: https://x.test}
      auth: {default: {type: none}}
    endpoints:
      - name: bad_tool
        group: bad.public.core
        capabilities: [sport.nonexistent]
        summary: "uses a bogus capability"
        base: default
        path: /x
    """
    d = write_spec({"bad.yaml": spec})
    errors, _ = lint(d)
    assert any("sport.nonexistent" in e and "not in _capabilities.yaml" in e for e in errors)


def test_lint_duplicate_description_is_error(write_spec):
    caps = """
    capabilities:
      - id: a.one
        description: "Same text."
      - id: a.two
        description: "Same text."
    """
    d = write_spec({"_capabilities.yaml": caps}, with_capabilities=False)
    errors, _ = lint(d)
    assert any("duplicate capability description" in e for e in errors)


def test_lint_single_provider_warning(write_spec):
    # demo exposes sport.match_detail via exactly one provider → warning, not error
    errors, warnings = lint(write_spec({"demo.yaml": _DEMO}))
    assert errors == []
    assert any("sport.match_detail" in w and "only one provider" in w for w in warnings)


def test_single_provider_flag_suppresses_warning(write_spec):
    # stats.shot_chart is marked single_provider: true in the catalogue
    spec = _DEMO.replace("sport.match_detail", "stats.shot_chart")
    _errors, warnings = lint(write_spec({"demo.yaml": spec}))
    assert not any("stats.shot_chart" in w and "only one provider" in w for w in warnings)


def test_build_provider_index_respects_enabled_groups(specs_dir):
    specs = load_all_specs(specs_dir)
    idx = build_provider_index(specs, {"demo.public.core"})
    assert idx["sport.match_detail"] == [("demo", "demo_match_get")]
    # disabled group → empty
    assert build_provider_index(specs, set()) == {}


_DEMO = """
provider:
  id: demo
  display_name: "Demo"
  base_urls: {default: https://api.demo.test}
  auth: {default: {type: none}}
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
