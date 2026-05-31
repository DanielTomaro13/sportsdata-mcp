"""Specs resolve via importlib.resources — not a cwd-relative ./specs/."""

from __future__ import annotations

import os

from sportsdata_mcp.spec_loader import (
    load_all_specs,
    load_capabilities,
    packaged_specs_dir,
)


def test_packaged_specs_dir_contains_catalogue():
    d = packaged_specs_dir()
    assert (d / "_capabilities.yaml").exists()
    assert (d / "_template.yaml").exists()


def test_loads_from_arbitrary_cwd(tmp_path, monkeypatch):
    # No ./specs/ in this cwd; loader must still find the packaged catalogue.
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "specs").exists()
    catalogue = load_capabilities()  # default → packaged dir
    assert any(c.id == "sport.match_detail" for c in catalogue.capabilities)
    # load_all_specs over the package: no provider specs yet, but must not raise
    assert isinstance(load_all_specs(), list)


def test_template_is_skipped_by_loader():
    specs = load_all_specs()
    assert all(s.provider.id != "example" for s in specs)
    assert os.path.exists(packaged_specs_dir() / "_template.yaml")
