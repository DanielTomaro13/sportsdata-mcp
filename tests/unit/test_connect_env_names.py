"""Every connector must save to an env var its provider actually reads.

`connect espnfantasy` shipped saving `ESPN_S2` while the spec read
`ESPN_FANTASY_COOKIE`. Nothing errored: the wizard said "connected", wrote the file,
and every private-league call still went out anonymous and 401'd. A wizard whose whole
job is to remove a manual step is the worst place for a silent mismatch, so the link
between the two names is asserted rather than assumed.
"""

from __future__ import annotations

import pytest

from sportsdata_mcp.connect import CONNECTORS
from sportsdata_mcp.spec import auth_env_names
from sportsdata_mcp.spec_loader import load_all_specs


@pytest.fixture(scope="module")
def providers():
    return {s.provider.id: s.provider for s in load_all_specs()}


@pytest.mark.parametrize("name", sorted(CONNECTORS))
def test_connector_targets_an_env_var_its_provider_reads(name, providers):
    conn = CONNECTORS[name]
    provider = providers.get(conn.provider)
    assert provider is not None, f"connector {name} names a provider that does not exist"
    reads = auth_env_names(provider)
    assert conn.env_var in reads, (
        f"`connect {name}` saves {conn.env_var}, but provider {conn.provider} reads "
        f"{sorted(reads)} — the credential would be written and never used"
    )
