"""list_available_groups now reports per-provider auth requirements (env names +
required/optional) so a client can show 'ready / needs-key' without probing live."""

from sportsdata_mcp.server import _provider_auth
from sportsdata_mcp.spec_loader import load_all_specs


def test_required_optional_and_open_providers() -> None:
    pa = _provider_auth(load_all_specs())

    # a required key (DataGolf rides ?key=)
    assert pa["datagolf"]["auth_required"] is True
    assert pa["datagolf"]["auth_optional"] is False
    assert "DATAGOLF_KEY" in pa["datagolf"]["auth_env"]

    # optional: Kalshi works anonymously, a key only raises limits
    assert pa["kalshi"]["auth_required"] is False
    assert pa["kalshi"]["auth_optional"] is True
    assert any(e.startswith("KALSHI_") for e in pa["kalshi"]["auth_env"])

    # OAuth provider: client id + secret required
    assert pa["tab"]["auth_required"] is True
    assert {"TAB_CLIENT_ID", "TAB_CLIENT_SECRET"} <= set(pa["tab"]["auth_env"])

    # an open, scraped provider needs nothing
    assert pa["espn"]["auth_required"] is False
    assert pa["espn"]["auth_env"] == []


def test_every_provider_has_an_entry() -> None:
    specs = load_all_specs()
    pa = _provider_auth(specs)
    assert {s.provider.id for s in specs} == set(pa)
    for entry in pa.values():
        assert set(entry) == {"auth_env", "auth_required", "auth_optional"}
        assert isinstance(entry["auth_env"], list)
